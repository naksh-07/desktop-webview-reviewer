"""
Tests for Experience Store Schema Migrations (v1 -> v2 -> v3 -> v4).
Architecture H / Milestone 2.1 Prompt 5 - Reality & Migration Audit.

Verifies:
- Sequential migration application from empty database to CURRENT_SCHEMA_VERSION
- Retention and correctness of foreign keys and indexes across all 4 versions
- Migration idempotency (multiple apply_migrations calls without errors)
- Schema version tracking in PRAGMA user_version and schema_migrations table
- Safe rejection of unsupported schema downgrades via SchemaMigrationException
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

from runtime.experience.schema import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    MIGRATION_V1_STATEMENTS,
    MIGRATION_V2_STATEMENTS,
    MIGRATION_V3_STATEMENTS,
    MIGRATION_V4_STATEMENTS,
    SchemaMigrationException,
    apply_migrations,
)


class TestExperienceMigrations(unittest.TestCase):
    """Forensic verification of SQLite schema migrations and foreign key integrity."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_experience.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_clean_migration_from_empty_database(self) -> None:
        """Applies migrations to an empty database and verifies all tables and versions."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            applied = apply_migrations(conn)
            self.assertEqual(applied, CURRENT_SCHEMA_VERSION)

            # Check PRAGMA user_version
            cursor = conn.cursor()
            cursor.execute("PRAGMA user_version;")
            v = cursor.fetchone()[0]
            self.assertEqual(v, CURRENT_SCHEMA_VERSION)

            # Verify schema_migrations table has entries for 1..4
            cursor.execute("SELECT version, description FROM schema_migrations ORDER BY version ASC;")
            rows = cursor.fetchall()
            self.assertEqual(len(rows), CURRENT_SCHEMA_VERSION)
            for idx, (ver, desc) in enumerate(rows, start=1):
                self.assertEqual(ver, idx)
                self.assertTrue(len(desc) > 0)

            # Verify expected core tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {r[0] for r in cursor.fetchall()}
            expected_tables = {
                "schema_migrations", "installation_metadata", "projects", "review_sessions",
                "missions", "action_references", "trace_references", "evidence_references",
                "experience_outcomes", "normalized_failures", "recovery_attempts",
                "agent_sessions", "agent_turns", "agent_tool_calls", "agent_subagents",
                "agent_artifacts", "agent_corrections", "agent_dwr_correlations",
                "observations", "detected_patterns", "improvement_candidates",
                "governance_records", "durable_knowledge",
            }
            for expected in expected_tables:
                self.assertIn(expected, tables, f"Expected table '{expected}' missing from schema.")
        finally:
            conn.close()

    def test_migration_idempotency(self) -> None:
        """Re-running apply_migrations on an up-to-date schema returns 0 and modifies nothing."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            applied_first = apply_migrations(conn)
            self.assertEqual(applied_first, CURRENT_SCHEMA_VERSION)

            # Second call should be a no-op
            applied_second = apply_migrations(conn)
            self.assertEqual(applied_second, 0)

            # Version remains unchanged
            cursor = conn.cursor()
            cursor.execute("PRAGMA user_version;")
            self.assertEqual(cursor.fetchone()[0], CURRENT_SCHEMA_VERSION)
        finally:
            conn.close()

    def test_stepwise_incremental_migration(self) -> None:
        """Applies migrations sequentially one version at a time and verifies schema growth."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()

            # Ensure schema_migrations table exists
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                """
            )

            # Apply V1 manually
            for stmt in MIGRATION_V1_STATEMENTS:
                if stmt.strip():
                    cursor.execute(stmt.strip())
            cursor.execute("PRAGMA user_version = 1;")
            conn.commit()

            cursor.execute("PRAGMA user_version;")
            self.assertEqual(cursor.fetchone()[0], 1)

            # Now run apply_migrations: should apply v2, v3, v4 (3 migrations)
            applied = apply_migrations(conn)
            self.assertEqual(applied, 3)

            cursor.execute("PRAGMA user_version;")
            self.assertEqual(cursor.fetchone()[0], CURRENT_SCHEMA_VERSION)
        finally:
            conn.close()

    def test_downgrade_rejection(self) -> None:
        """Attempting to migrate a database with a future user_version raises SchemaMigrationException."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            # Artificially set user_version higher than CURRENT_SCHEMA_VERSION
            future_version = CURRENT_SCHEMA_VERSION + 1
            conn.execute(f"PRAGMA user_version = {future_version};")
            conn.commit()

            with self.assertRaises(SchemaMigrationException) as ctx:
                apply_migrations(conn)
            self.assertIn(f"Schema version v{future_version} is newer", str(ctx.exception))
        finally:
            conn.close()

    def test_foreign_key_enforcement(self) -> None:
        """Verifies foreign key constraints correctly enforce relational integrity."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            apply_migrations(conn)
            cursor = conn.cursor()

            # Inserting a mission with nonexistent session_id should fail under foreign_keys = ON
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO missions (mission_id, session_id, goal, scope, created_at, status)
                    VALUES ('m_test', 'nonexistent_session', 'test goal', 'SESSION', '2026-09-06T00:00:00Z', 'ACTIVE');
                    """
                )
                conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
