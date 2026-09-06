"""
Tests for Experience Store storage, configuration, SQLite migrations, and data integrity.
"""

import os
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path
import unittest

from runtime.experience.config import (
    ExperienceConfig,
    get_default_experience_dir,
    resolve_experience_dir,
    ENV_EXPERIENCE_DIR,
)
from runtime.experience.schema import CURRENT_SCHEMA_VERSION, apply_migrations
from runtime.experience.store import ExperienceStore, ExperiencePersistenceException
from runtime.experience.models import (
    SessionExperienceRecord,
    ExperienceScope,
)


class TestExperienceStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="exp_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)

    def test_default_path_resolution(self):
        """Verifies canonical platform default path resolution."""
        default_dir = get_default_experience_dir()
        self.assertTrue(isinstance(default_dir, Path))
        self.assertIn("DesktopWebViewReviewer", str(default_dir))
        self.assertIn("experience", str(default_dir))
        if os.name == "nt":
            self.assertTrue(
                "appdata" in str(default_dir).lower() or "local" in str(default_dir).lower(),
                f"Expected AppData/Local in default Windows path: {default_dir}",
            )

    def test_custom_path_resolution_and_precedence(self):
        """Verifies precedence: custom parameter > environment variable > platform default."""
        explicit_path = Path(self.temp_dir) / "explicit"
        env_path = Path(self.temp_dir) / "from_env"

        # 1. Platform default when no args or env
        orig_env = os.environ.get(ENV_EXPERIENCE_DIR)
        try:
            if ENV_EXPERIENCE_DIR in os.environ:
                del os.environ[ENV_EXPERIENCE_DIR]
            self.assertEqual(resolve_experience_dir(), get_default_experience_dir())

            # 2. Environment override
            os.environ[ENV_EXPERIENCE_DIR] = str(env_path)
            self.assertEqual(resolve_experience_dir(), env_path.resolve())

            # 3. Explicit parameter overrides environment
            self.assertEqual(resolve_experience_dir(explicit_path), explicit_path.resolve())
        finally:
            if orig_env is not None:
                os.environ[ENV_EXPERIENCE_DIR] = orig_env
            elif ENV_EXPERIENCE_DIR in os.environ:
                del os.environ[ENV_EXPERIENCE_DIR]

    def test_directory_and_installation_creation(self):
        """Verifies directory creation and durable installation ID generation."""
        custom_base = Path(self.temp_dir) / "custom_store"
        config = ExperienceConfig(base_dir=custom_base)

        self.assertFalse(custom_base.exists())
        config.ensure_directories()
        self.assertTrue(custom_base.exists())

        inst_id = config.get_or_create_installation_id()
        self.assertTrue(inst_id.startswith("inst_"))
        self.assertTrue(config.installation_id_path.exists())

        # Second call returns the same persistent ID
        inst_id_2 = config.get_or_create_installation_id()
        self.assertEqual(inst_id, inst_id_2)

    def test_database_initialization_and_wal_mode(self):
        """Verifies SQLite database initialization, WAL journal mode, and schema version."""
        config = ExperienceConfig(base_dir=Path(self.temp_dir) / "db_init", fail_safe_mode=False)
        store = ExperienceStore(config=config)
        self.addCleanup(store.close)

        self.assertTrue(config.database_path.exists())

        conn = sqlite3.connect(str(config.database_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0].lower()
        self.assertEqual(mode, "wal")

        cursor.execute("PRAGMA user_version;")
        ver = cursor.fetchone()[0]
        self.assertEqual(ver, CURRENT_SCHEMA_VERSION)

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        expected_tables = {
            "schema_migrations",
            "installation_metadata",
            "projects",
            "review_sessions",
            "missions",
            "action_references",
            "trace_references",
            "evidence_references",
            "experience_outcomes",
        }
        self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")
        conn.close()

    def test_schema_migrations_tracking(self):
        """Verifies schema migrations are tracked in schema_migrations table."""
        config = ExperienceConfig(base_dir=Path(self.temp_dir) / "migration_test", fail_safe_mode=False)
        store = ExperienceStore(config=config)
        self.addCleanup(store.close)

        conn = sqlite3.connect(str(config.database_path))
        cursor = conn.cursor()
        cursor.execute("SELECT version, description FROM schema_migrations ORDER BY version ASC;")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), CURRENT_SCHEMA_VERSION)
        self.assertEqual(rows[0][0], 1)
        conn.close()

        # Running apply_migrations again is idempotent and applies 0 migrations
        conn2 = sqlite3.connect(str(config.database_path))
        applied = apply_migrations(conn2)
        self.assertEqual(applied, 0)
        conn2.close()

    def test_integrity_check_and_corruption_detection(self):
        """Verifies PRAGMA integrity_check on clean and corrupted databases."""
        config = ExperienceConfig(base_dir=Path(self.temp_dir) / "integrity_test", fail_safe_mode=False)
        store = ExperienceStore(config=config)

        is_ok, msg = store.run_integrity_check()
        self.assertTrue(is_ok)
        self.assertEqual(msg, "ok")
        store.close()

        # Corrupt database header bytes
        db_file = config.database_path
        with open(db_file, "r+b") as f:
            f.seek(16)
            f.write(b"\xFF" * 16)

        # 1. Reopening with fail_safe_mode=False raises ExperiencePersistenceException
        with self.assertRaises(ExperiencePersistenceException):
            ExperienceStore(config=config)

        # 2. Reopening with fail_safe_mode=True handles gracefully with DEGRADED status
        safe_config = ExperienceConfig(base_dir=Path(self.temp_dir) / "integrity_test", fail_safe_mode=True)
        broken_store = ExperienceStore(config=safe_config)
        self.addCleanup(broken_store.close)
        is_ok_broken, broken_msg = broken_store.run_integrity_check()
        self.assertFalse(is_ok_broken)
        self.assertIn("not a database", broken_msg)
        health = broken_store.get_health_report()
        self.assertEqual(health.health, "DEGRADED")

    def test_multithreaded_concurrent_writes(self):
        """Verifies concurrent multithreaded writes without SQLite database locks or corruption."""
        config = ExperienceConfig(base_dir=Path(self.temp_dir) / "concurrent_test", fail_safe_mode=False)
        store = ExperienceStore(config=config)
        self.addCleanup(store.close)

        num_threads = 8
        sessions_per_thread = 10
        errors = []

        def worker(thread_idx: int):
            for i in range(sessions_per_thread):
                sid = f"sess_th_{thread_idx}_{i}"
                record = SessionExperienceRecord(
                    session_id=sid,
                    created_at="2026-09-06T12:00:00Z",
                    status="SUCCESS",
                    runtime_version="2.0.0b1",
                    metadata={"thread": thread_idx, "idx": i},
                )
                try:
                    res = store.record_session(record)
                    if res is None:
                        errors.append(f"Null return for {sid}")
                except Exception as e:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        counts = store.get_record_counts()
        self.assertEqual(counts["sessions"], num_threads * sessions_per_thread)

        is_healthy, health_msg = store.run_integrity_check()
        self.assertTrue(is_healthy, f"Integrity check failed: {health_msg}")

    def test_not_in_source_repository_by_default(self):
        """Guarantees the default Experience Data Directory is never inside the source repository."""
        repo_root = Path(__file__).resolve().parent.parent
        default_dir = get_default_experience_dir().resolve()
        self.assertFalse(
            str(default_dir).startswith(str(repo_root)),
            f"Default experience dir {default_dir} must not be inside repo root {repo_root}",
        )


if __name__ == "__main__":
    unittest.main()
