"""
Authoritative Experience Store Implementation for Desktop WebView Reviewer 2.0 / 2.1.

Durable, transactional, local SQLite store for:
- Sessions & Missions
- Action, Trace, and Evidence References
- Tripartite Outcomes & Verdicts
- Provenance tracking & scope management
- Health, sizing, and PRAGMA integrity inspection

Adheres strictly to Architecture H:
Consumer/persistence layer only; never replaces authoritative runtime/evidence/trace truth.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.version import get_version_info
from runtime.errors import DesktopAutomationException
from runtime.experience.config import ExperienceConfig, get_default_experience_dir
from runtime.experience.models import (
    ActionReferenceRecord,
    EvidenceReferenceRecord,
    ExperienceHealthReport,
    ExperienceScope,
    MissionExperienceRecord,
    NormalizedFailureRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    RecoveryExperienceRecord,
    ScopeValidationException,
    SessionExperienceRecord,
    TraceReferenceRecord,
    FailureSummaryItem,
    FailureSignatureSummary,
    RecoveryStatistics,
    VerificationDistribution,
    validate_scope_promotion,
)
from runtime.experience.privacy import PrivacyEnforcer, PrivacyViolationException
from runtime.experience.schema import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
)

logger = logging.getLogger("desktop_webview.experience.store")


class ExperiencePersistenceException(DesktopAutomationException):
    """Raised when an error occurs during experience storage or query execution."""
    pass


class ExperienceStore:
    """
    Local, durable SQLite Experience Store.
    Thread-safe and WAL-enabled.
    """

    _default_instance: Optional[ExperienceStore] = None
    _default_lock: threading.Lock = threading.Lock()

    def __init__(self, config: Optional[ExperienceConfig] = None):
        self.config = config or ExperienceConfig()
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._installation_id: str = ""
        self._last_write_iso: Optional[str] = None
        self._init_error: Optional[str] = None

        self._initialize()

    @classmethod
    def get_default_store(cls) -> ExperienceStore:
        """Singleton accessor for the default ExperienceStore instance."""
        with cls._default_lock:
            if cls._default_instance is None:
                cls._default_instance = cls()
            return cls._default_instance

    @property
    def installation_id(self) -> str:
        return self._installation_id

    def _initialize(self) -> None:
        """Ensures directory tree exists and initializes the SQLite database with migrations."""
        with self._lock:
            try:
                self.config.ensure_directories()
                self._installation_id = self.config.get_or_create_installation_id()

                db_path = self.config.database_path
                self._conn = sqlite3.connect(
                    str(db_path),
                    timeout=self.config.busy_timeout_ms / 1000.0,
                    check_same_thread=False,
                )
                self._conn.row_factory = sqlite3.Row

                # Configure SQLite performance and safety pragmas
                cursor = self._conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute(f"PRAGMA busy_timeout = {self.config.busy_timeout_ms};")
                if self.config.enable_wal_mode:
                    cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")

                # Execute schema migrations
                apply_migrations(self._conn)

                # Record / update installation metadata
                vinfo = get_version_info()
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO installation_metadata (
                        installation_id, runtime_version, schema_version, created_at, updated_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(installation_id) DO UPDATE SET
                        runtime_version = excluded.runtime_version,
                        schema_version = excluded.schema_version,
                        updated_at = excluded.updated_at;
                    """,
                    (
                        self._installation_id,
                        vinfo.product_version,
                        CURRENT_SCHEMA_VERSION,
                        now_iso,
                        now_iso,
                        json.dumps({"platform": os.name}),
                    ),
                )
                self._conn.commit()
                self._init_error = None
                logger.info("ExperienceStore initialized at %s (installation: %s)", db_path, self._installation_id)

            except Exception as e:
                self._init_error = str(e)
                logger.error("Failed to initialize ExperienceStore at %s: %s", self.config.database_path, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to initialize ExperienceStore: {e}") from e

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._initialize()
        if self._conn is None:
            raise ExperiencePersistenceException(
                f"ExperienceStore connection is unavailable: {self._init_error or 'Unknown error'}"
            )
        return self._conn

    # -------------------------------------------------------------------------
    # Record Operations
    # -------------------------------------------------------------------------

    def record_session(self, record: SessionExperienceRecord) -> Optional[SessionExperienceRecord]:
        """Persists or updates a session experience record."""
        validate_scope_promotion(record.scope)
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="session.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if record.project_id:
                    cursor.execute(
                        "INSERT OR IGNORE INTO projects (project_id, name, created_at) VALUES (?, ?, ?);",
                        (record.project_id, record.project_id, record.created_at),
                    )
                cursor.execute(
                    """
                    INSERT INTO review_sessions (
                        session_id, project_id, created_at, completed_at, status,
                        target_executable, target_pid, target_hwnd, target_plane,
                        runtime_version, scope, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        completed_at = excluded.completed_at,
                        status = excluded.status,
                        target_executable = excluded.target_executable,
                        target_pid = excluded.target_pid,
                        target_hwnd = excluded.target_hwnd,
                        target_plane = excluded.target_plane,
                        scope = excluded.scope,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.session_id,
                        record.project_id,
                        record.created_at,
                        record.completed_at,
                        record.status,
                        record.target_executable,
                        record.target_pid,
                        record.target_hwnd,
                        record.target_plane,
                        record.runtime_version,
                        record.scope.value if isinstance(record.scope, ExperienceScope) else str(record.scope),
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record session %s: %s", record.session_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record session: {e}") from e
                return None

    def record_mission(self, record: MissionExperienceRecord) -> Optional[MissionExperienceRecord]:
        """Persists or updates a review mission record."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="mission.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if record.project_id:
                    cursor.execute(
                        "INSERT OR IGNORE INTO projects (project_id, name, created_at) VALUES (?, ?, ?);",
                        (record.project_id, record.project_id, record.created_at),
                    )
                cursor.execute(
                    """
                    INSERT INTO missions (
                        mission_id, session_id, project_id, goal, scope, created_at, completed_at, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mission_id) DO UPDATE SET
                        completed_at = excluded.completed_at,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.mission_id,
                        record.session_id,
                        record.project_id,
                        record.goal,
                        record.scope,
                        record.created_at,
                        record.completed_at,
                        record.status,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record mission %s: %s", record.mission_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record mission: {e}") from e
                return None

    def record_action_reference(self, record: ActionReferenceRecord) -> Optional[ActionReferenceRecord]:
        """Persists an action reference record."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="action_ref.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM action_references WHERE action_id = ? AND session_id = ? ORDER BY id DESC LIMIT 1;",
                    (record.action_id, record.session_id),
                )
                existing_row = cursor.fetchone()
                if existing_row:
                    cursor.execute(
                        """
                        UPDATE action_references SET
                            action_type = ?, plane = ?, target = ?, status = ?, duration_ms = ?,
                            source = ?, source_type = ?, kind = ?, confidence = ?, timestamp = ?,
                            iso_timestamp = ?, evidence_reference = ?, trace_reference = ?, metadata_json = ?
                        WHERE id = ?;
                        """,
                        (
                            record.action_type,
                            record.plane,
                            record.target,
                            record.status,
                            record.duration_ms,
                            record.provenance.source,
                            record.provenance.source_type.value,
                            record.provenance.kind.value,
                            record.provenance.confidence,
                            record.provenance.timestamp,
                            record.provenance.iso_timestamp,
                            record.provenance.evidence_reference,
                            record.provenance.trace_reference,
                            json.dumps(clean_metadata, default=str),
                            existing_row["id"],
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO action_references (
                            action_id, session_id, action_type, plane, target, status, duration_ms,
                            source, source_type, kind, confidence, timestamp, iso_timestamp,
                            evidence_reference, trace_reference, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            record.action_id,
                            record.session_id,
                            record.action_type,
                            record.plane,
                            record.target,
                            record.status,
                            record.duration_ms,
                            record.provenance.source,
                            record.provenance.source_type.value,
                            record.provenance.kind.value,
                            record.provenance.confidence,
                            record.provenance.timestamp,
                            record.provenance.iso_timestamp,
                            record.provenance.evidence_reference,
                            record.provenance.trace_reference,
                            json.dumps(clean_metadata, default=str),
                        ),
                    )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record action reference %s: %s", record.action_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record action reference: {e}") from e
                return None

    def record_trace_reference(self, record: TraceReferenceRecord) -> Optional[TraceReferenceRecord]:
        """Persists a Desktop Trace event correlation reference."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="trace_ref.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO trace_references (
                        event_id, session_id, sequence_monotonic, event_type, plane,
                        source, timestamp, iso_timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        record.event_id,
                        record.session_id,
                        record.sequence_monotonic,
                        record.event_type,
                        record.plane,
                        record.provenance.source,
                        record.provenance.timestamp,
                        record.provenance.iso_timestamp,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record trace reference %s: %s", record.event_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record trace reference: {e}") from e
                return None

    def record_evidence_reference(self, record: EvidenceReferenceRecord) -> Optional[EvidenceReferenceRecord]:
        """
        Persists a forensic evidence reference (checksum, uri, artifact metadata).
        Never stores raw binary screenshots or blobs in SQLite.
        """
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="evidence_ref.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO evidence_references (
                        evidence_id, session_id, action_id, artifact_id, artifact_type,
                        checksum_sha256, relative_path_or_uri, source, timestamp, iso_timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        record.evidence_id,
                        record.session_id,
                        record.action_id,
                        record.artifact_id,
                        record.artifact_type,
                        record.checksum_sha256,
                        record.relative_path_or_uri,
                        record.provenance.source,
                        record.provenance.timestamp,
                        record.provenance.iso_timestamp,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record evidence reference %s: %s", record.evidence_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record evidence reference: {e}") from e
                return None

    def record_outcome(self, record: OutcomeRecord) -> Optional[OutcomeRecord]:
        """Persists a final review outcome record."""
        clean_details = PrivacyEnforcer.check_and_sanitize(record.details, context="outcome.details")
        prov = record.provenance or ProvenanceRecord(
            source="VerificationEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=record.session_id,
            confidence=record.confidence,
            kind=RecordKind.FACT,
        )

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO experience_outcomes (
                        outcome_id, session_id, verdict, confidence, error_category,
                        source, source_type, kind, timestamp, iso_timestamp,
                        evidence_reference, trace_reference, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(outcome_id) DO UPDATE SET
                        verdict = excluded.verdict,
                        confidence = excluded.confidence,
                        error_category = excluded.error_category,
                        details_json = excluded.details_json;
                    """,
                    (
                        record.outcome_id,
                        record.session_id,
                        record.verdict,
                        record.confidence,
                        record.error_category,
                        prov.source,
                        prov.source_type.value,
                        prov.kind.value,
                        prov.timestamp,
                        prov.iso_timestamp,
                        prov.evidence_reference,
                        prov.trace_reference,
                        json.dumps(clean_details, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record outcome %s: %s", record.outcome_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record outcome: {e}") from e
                return None

    def record_failure(self, record: NormalizedFailureRecord) -> Optional[NormalizedFailureRecord]:
        """Persists a normalized failure record."""
        clean_context = PrivacyEnforcer.check_and_sanitize(record.safe_context, context="failure.safe_context")
        prov = record.provenance or ProvenanceRecord(
            source="FailureNormalizer",
            source_type=RecordSourceType.RUNTIME,
            session_id=record.session_id,
            confidence=record.confidence,
            kind=RecordKind.FACT,
        )

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO normalized_failures (
                        failure_id, session_id, mission_id, action_id, category, original_classification,
                        signature, confidence, source, source_type, kind, recovery_reference,
                        trace_reference, evidence_reference, timestamp, iso_timestamp, safe_context_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(failure_id) DO UPDATE SET
                        category = excluded.category,
                        original_classification = excluded.original_classification,
                        signature = excluded.signature,
                        confidence = excluded.confidence,
                        recovery_reference = excluded.recovery_reference,
                        safe_context_json = excluded.safe_context_json;
                    """,
                    (
                        record.failure_id,
                        record.session_id,
                        record.mission_id,
                        record.action_id,
                        record.category,
                        record.original_classification,
                        record.signature,
                        record.confidence,
                        prov.source,
                        prov.source_type.value,
                        prov.kind.value,
                        record.recovery_reference,
                        record.trace_reference,
                        record.evidence_reference,
                        prov.timestamp,
                        prov.iso_timestamp,
                        json.dumps(clean_context, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record failure %s: %s", record.failure_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record failure: {e}") from e
                return None

    def record_recovery_attempt(self, record: RecoveryExperienceRecord) -> Optional[RecoveryExperienceRecord]:
        """Persists a bounded recovery attempt record."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="recovery.metadata")
        prov = record.provenance or ProvenanceRecord(
            source="RecoveryEngine",
            source_type=RecordSourceType.RUNTIME,
            session_id=record.session_id,
            kind=RecordKind.FACT,
        )

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO recovery_attempts (
                        recovery_id, session_id, action_id, failure_id, failure_category,
                        recovery_action, attempt_number, max_attempts, result, duration_ms,
                        source, source_type, kind, error, evidence_refs_json,
                        trace_event_id, timestamp, iso_timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(recovery_id) DO UPDATE SET
                        result = excluded.result,
                        duration_ms = excluded.duration_ms,
                        error = excluded.error,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.recovery_id,
                        record.session_id,
                        record.action_id,
                        record.failure_id,
                        record.failure_category,
                        record.recovery_action,
                        record.attempt_number,
                        record.max_attempts,
                        record.result,
                        record.duration_ms,
                        prov.source,
                        prov.source_type.value,
                        prov.kind.value,
                        record.error,
                        json.dumps(record.evidence_refs, default=str),
                        record.trace_event_id,
                        record.timestamp,
                        record.iso_timestamp,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record recovery attempt %s: %s", record.recovery_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record recovery attempt: {e}") from e
                return None

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------


    def get_session(self, session_id: str) -> Optional[SessionExperienceRecord]:
        """Retrieves a session record by session_id."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM review_sessions WHERE session_id = ?;", (session_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                return SessionExperienceRecord(
                    session_id=row["session_id"],
                    project_id=row["project_id"],
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                    status=row["status"],
                    target_executable=row["target_executable"],
                    target_pid=row["target_pid"],
                    target_hwnd=row["target_hwnd"],
                    target_plane=row["target_plane"],
                    runtime_version=row["runtime_version"],
                    scope=ExperienceScope(row["scope"]),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
            except Exception as e:
                logger.error("Failed to get session %s: %s", session_id, e)
                return None

    def list_sessions(self, limit: int = 50) -> List[SessionExperienceRecord]:
        """Lists recent session records."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM review_sessions ORDER BY created_at DESC LIMIT ?;",
                    (limit,),
                )
                results = []
                for row in cursor.fetchall():
                    results.append(
                        SessionExperienceRecord(
                            session_id=row["session_id"],
                            project_id=row["project_id"],
                            created_at=row["created_at"],
                            completed_at=row["completed_at"],
                            status=row["status"],
                            target_executable=row["target_executable"],
                            target_pid=row["target_pid"],
                            target_hwnd=row["target_hwnd"],
                            target_plane=row["target_plane"],
                            runtime_version=row["runtime_version"],
                            scope=ExperienceScope(row["scope"]),
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to list sessions: %s", e)
                return []

    def get_missions(self, session_id: Optional[str] = None) -> List[MissionExperienceRecord]:
        """Retrieves mission records, optionally filtered by session_id."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if session_id:
                    cursor.execute(
                        "SELECT * FROM missions WHERE session_id = ? ORDER BY created_at ASC;",
                        (session_id,),
                    )
                else:
                    cursor.execute("SELECT * FROM missions ORDER BY created_at DESC LIMIT 100;")
                results = []
                for row in cursor.fetchall():
                    results.append(
                        MissionExperienceRecord(
                            mission_id=row["mission_id"],
                            session_id=row["session_id"],
                            project_id=row["project_id"],
                            goal=row["goal"],
                            scope=row["scope"],
                            created_at=row["created_at"],
                            completed_at=row["completed_at"],
                            status=row["status"],
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get missions: %s", e)
                return []

    def get_missions_for_session(self, session_id: str) -> List[MissionExperienceRecord]:
        """Convenience alias for get_missions(session_id)."""
        return self.get_missions(session_id=session_id)

    def get_action_references(self, session_id: str) -> List[ActionReferenceRecord]:
        """Retrieves action references for a session."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM action_references WHERE session_id = ? ORDER BY id ASC;",
                    (session_id,),
                )
                vinfo = get_version_info()
                results = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType(row["source_type"]),
                        session_id=row["session_id"],
                        runtime_version=vinfo.product_version,
                        confidence=float(row["confidence"]),
                        evidence_reference=row["evidence_reference"],
                        trace_reference=row["trace_reference"],
                        kind=RecordKind(row["kind"]),
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        ActionReferenceRecord(
                            action_id=row["action_id"],
                            session_id=row["session_id"],
                            action_type=row["action_type"],
                            plane=row["plane"],
                            target=row["target"],
                            status=row["status"],
                            duration_ms=row["duration_ms"],
                            provenance=prov,
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get action references for %s: %s", session_id, e)
                return []

    def get_actions(self, session_id: Optional[str] = None) -> List[ActionReferenceRecord]:
        """Retrieves action references, optionally filtered by session_id."""
        if session_id:
            return self.get_action_references(session_id)
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM action_references ORDER BY id DESC LIMIT 100;")
                vinfo = get_version_info()
                results = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType(row["source_type"]),
                        session_id=row["session_id"],
                        runtime_version=vinfo.product_version,
                        confidence=float(row["confidence"]),
                        evidence_reference=row["evidence_reference"],
                        trace_reference=row["trace_reference"],
                        kind=RecordKind(row["kind"]),
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        ActionReferenceRecord(
                            action_id=row["action_id"],
                            session_id=row["session_id"],
                            action_type=row["action_type"],
                            plane=row["plane"],
                            target=row["target"],
                            status=row["status"],
                            duration_ms=row["duration_ms"],
                            provenance=prov,
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get actions: %s", e)
                return []

    def get_actions_for_session(self, session_id: str) -> List[ActionReferenceRecord]:
        """Convenience alias for get_action_references(session_id)."""
        return self.get_action_references(session_id)

    def get_evidence_references(self, session_id: str) -> List[EvidenceReferenceRecord]:
        """Retrieves evidence references for a session."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM evidence_references WHERE session_id = ? ORDER BY id ASC;",
                    (session_id,),
                )
                vinfo = get_version_info()
                results = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType.EVIDENCE_STORE,
                        session_id=row["session_id"],
                        runtime_version=vinfo.product_version,
                        evidence_reference=row["evidence_id"],
                        kind=RecordKind.FACT,
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        EvidenceReferenceRecord(
                            evidence_id=row["evidence_id"],
                            session_id=row["session_id"],
                            action_id=row["action_id"],
                            artifact_id=row["artifact_id"],
                            artifact_type=row["artifact_type"],
                            checksum_sha256=row["checksum_sha256"],
                            relative_path_or_uri=row["relative_path_or_uri"],
                            provenance=prov,
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get evidence references for %s: %s", session_id, e)
                return []

    def get_evidence_for_session(self, session_id: str) -> List[EvidenceReferenceRecord]:
        """Convenience alias for get_evidence_references(session_id)."""
        return self.get_evidence_references(session_id)

    def get_trace_references(self, session_id: Optional[str] = None) -> List[TraceReferenceRecord]:
        """Retrieves trace references, optionally filtered by session_id."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if session_id:
                    cursor.execute(
                        "SELECT * FROM trace_references WHERE session_id = ? ORDER BY sequence_monotonic ASC;",
                        (session_id,),
                    )
                else:
                    cursor.execute("SELECT * FROM trace_references ORDER BY id DESC LIMIT 100;")
                vinfo = get_version_info()
                results = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType.TRACE_ENGINE,
                        session_id=row["session_id"],
                        runtime_version=vinfo.product_version,
                        trace_reference=row["event_id"],
                        kind=RecordKind.FACT,
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        TraceReferenceRecord(
                            event_id=row["event_id"],
                            session_id=row["session_id"],
                            sequence_monotonic=row["sequence_monotonic"],
                            event_type=row["event_type"],
                            plane=row["plane"],
                            provenance=prov,
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get trace references: %s", e)
                return []

    def get_traces_for_session(self, session_id: str) -> List[TraceReferenceRecord]:
        """Convenience alias for get_trace_references(session_id)."""
        return self.get_trace_references(session_id=session_id)

    def get_outcomes(self, session_id: Optional[str] = None) -> List[OutcomeRecord]:
        """Retrieves review outcomes, optionally filtered by session_id."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if session_id:
                    cursor.execute(
                        "SELECT * FROM experience_outcomes WHERE session_id = ? ORDER BY timestamp DESC;",
                        (session_id,),
                    )
                else:
                    cursor.execute("SELECT * FROM experience_outcomes ORDER BY timestamp DESC LIMIT 100;")

                vinfo = get_version_info()
                results = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType(row["source_type"]),
                        session_id=row["session_id"],
                        runtime_version=vinfo.product_version,
                        confidence=float(row["confidence"]),
                        evidence_reference=row["evidence_reference"],
                        trace_reference=row["trace_reference"],
                        kind=RecordKind(row["kind"]),
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        OutcomeRecord(
                            outcome_id=row["outcome_id"],
                            session_id=row["session_id"],
                            verdict=row["verdict"],
                            confidence=float(row["confidence"]),
                            error_category=row["error_category"],
                            details=json.loads(row["details_json"] or "{}"),
                            provenance=prov,
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get outcomes: %s", e)
                return []

    def get_outcomes_for_session(self, session_id: str) -> List[OutcomeRecord]:
        """Convenience alias for get_outcomes(session_id)."""
        return self.get_outcomes(session_id=session_id)

    def get_failures(
        self,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        signature: Optional[str] = None,
        limit: int = 100,
    ) -> List[NormalizedFailureRecord]:
        """Retrieves normalized failure records matching filter criteria."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT f.* FROM normalized_failures f"
                params: List[Any] = []
                clauses: List[str] = []

                if project_id:
                    query += " JOIN review_sessions s ON f.session_id = s.session_id"
                    clauses.append("s.project_id = ?")
                    params.append(project_id)

                if session_id:
                    clauses.append("f.session_id = ?")
                    params.append(session_id)

                if category:
                    clauses.append("f.category = ?")
                    params.append(category)

                if signature:
                    clauses.append("f.signature = ?")
                    params.append(signature)

                if clauses:
                    query += " WHERE " + " AND ".join(clauses)

                query += " ORDER BY f.timestamp DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, tuple(params))
                vinfo = get_version_info()
                results: List[NormalizedFailureRecord] = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType(row["source_type"]),
                        session_id=row["session_id"],
                        mission_id=row["mission_id"],
                        runtime_version=vinfo.product_version,
                        confidence=float(row["confidence"]),
                        evidence_reference=row["evidence_reference"],
                        trace_reference=row["trace_reference"],
                        kind=RecordKind(row["kind"]),
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        NormalizedFailureRecord(
                            failure_id=row["failure_id"],
                            session_id=row["session_id"],
                            category=row["category"],
                            original_classification=row["original_classification"],
                            signature=row["signature"],
                            confidence=float(row["confidence"]),
                            provenance=prov,
                            mission_id=row["mission_id"],
                            action_id=row["action_id"],
                            recovery_reference=row["recovery_reference"],
                            trace_reference=row["trace_reference"],
                            evidence_reference=row["evidence_reference"],
                            safe_context=json.loads(row["safe_context_json"] or "{}"),
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get failures: %s", e)
                return []

    def get_failure_category_counts(self, project_id: Optional[str] = None) -> List[FailureSummaryItem]:
        """Returns frequency of failures grouped by category, optionally filtered by project_id."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if project_id:
                    cursor.execute(
                        """
                        SELECT f.category, COUNT(*) as cnt
                        FROM normalized_failures f
                        JOIN review_sessions s ON f.session_id = s.session_id
                        WHERE s.project_id = ?
                        GROUP BY f.category
                        ORDER BY cnt DESC;
                        """,
                        (project_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT category, COUNT(*) as cnt
                        FROM normalized_failures
                        GROUP BY category
                        ORDER BY cnt DESC;
                        """
                    )
                return [
                    FailureSummaryItem(category=row["category"], count=row["cnt"])
                    for row in cursor.fetchall()
                ]
            except Exception as e:
                logger.error("Failed to get failure category counts: %s", e)
                return []

    def get_failure_signature_counts(self, limit: int = 20) -> List[FailureSignatureSummary]:
        """Returns frequency of recurring failures grouped by deterministic failure signature."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT signature, category, COUNT(*) as count, MAX(iso_timestamp) as latest_timestamp, MIN(session_id) as sample_session
                    FROM normalized_failures
                    GROUP BY signature
                    ORDER BY count DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
                return [
                    FailureSignatureSummary(
                        signature=row["signature"],
                        count=row["count"],
                        category=row["category"],
                        latest_timestamp=row["latest_timestamp"],
                        sample_session=row["sample_session"],
                    )
                    for row in cursor.fetchall()
                ]
            except Exception as e:
                logger.error("Failed to get failure signature counts: %s", e)
                return []

    def get_recovery_attempts(
        self,
        session_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> List[RecoveryExperienceRecord]:
        """Retrieves recovery attempt records matching filter criteria."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM recovery_attempts"
                params: List[Any] = []
                clauses: List[str] = []

                if session_id:
                    clauses.append("session_id = ?")
                    params.append(session_id)

                if category:
                    clauses.append("failure_category = ?")
                    params.append(category)

                if clauses:
                    query += " WHERE " + " AND ".join(clauses)

                query += " ORDER BY timestamp DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, tuple(params))
                vinfo = get_version_info()
                results: List[RecoveryExperienceRecord] = []
                for row in cursor.fetchall():
                    prov = ProvenanceRecord(
                        source=row["source"],
                        source_type=RecordSourceType(row["source_type"]),
                        session_id=row["session_id"],
                        runtime_version=vinfo.product_version,
                        kind=RecordKind(row["kind"]),
                        timestamp=float(row["timestamp"]),
                        iso_timestamp=row["iso_timestamp"],
                    )
                    results.append(
                        RecoveryExperienceRecord(
                            recovery_id=row["recovery_id"],
                            session_id=row["session_id"],
                            failure_category=row["failure_category"],
                            recovery_action=row["recovery_action"],
                            attempt_number=row["attempt_number"],
                            max_attempts=row["max_attempts"],
                            result=row["result"],
                            duration_ms=row["duration_ms"],
                            provenance=prov,
                            action_id=row["action_id"],
                            failure_id=row["failure_id"],
                            error=row["error"],
                            evidence_refs=json.loads(row["evidence_refs_json"] or "[]"),
                            trace_event_id=row["trace_event_id"],
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get recovery attempts: %s", e)
                return []

    def get_recovery_statistics(self, category: Optional[Any] = None) -> RecoveryStatistics:
        """Computes aggregate recovery success rates and outcome distributions."""
        cat_str = getattr(category, "value", str(category)) if category is not None else None
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                where_clause = "WHERE failure_category = ?" if cat_str else ""
                params = (cat_str,) if cat_str else ()

                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN result = 'SUCCESS' THEN 1 ELSE 0 END) as successful,
                        SUM(CASE WHEN result = 'FAILED' THEN 1 ELSE 0 END) as failed,
                        SUM(CASE WHEN result = 'BLOCKED' THEN 1 ELSE 0 END) as blocked,
                        SUM(CASE WHEN result = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled,
                        AVG(duration_ms) as mean_duration
                    FROM recovery_attempts
                    {where_clause};
                    """,
                    params,
                )
                row = cursor.fetchone()
                total = (row["total"] or 0) if row else 0
                successful = (row["successful"] or 0) if row else 0
                failed = (row["failed"] or 0) if row else 0
                blocked = (row["blocked"] or 0) if row else 0
                cancelled = (row["cancelled"] or 0) if row else 0
                mean_duration = (row["mean_duration"] or 0.0) if row else 0.0
                rate = round(successful / total, 3) if total > 0 else 0.0

                # Per-category breakdown
                cursor.execute(
                    """
                    SELECT
                        failure_category,
                        COUNT(*) as total,
                        SUM(CASE WHEN result = 'SUCCESS' THEN 1 ELSE 0 END) as successful
                    FROM recovery_attempts
                    GROUP BY failure_category;
                    """
                )
                by_cat: Dict[str, Dict[str, Any]] = {}
                for r in cursor.fetchall():
                    c_tot = r["total"]
                    c_succ = r["successful"] or 0
                    by_cat[r["failure_category"]] = {
                        "total": c_tot,
                        "successful": c_succ,
                        "success_rate": round(c_succ / c_tot, 3) if c_tot > 0 else 0.0,
                    }

                return RecoveryStatistics(
                    category=cat_str or "ALL",
                    attempt_count=total,
                    success_count=successful,
                    failed_count=failed,
                    blocked_count=blocked,
                    success_rate=rate,
                    mean_duration_ms=mean_duration,
                    total_attempts=total,
                    successful_attempts=successful,
                    failed_attempts=failed,
                    blocked_attempts=blocked,
                    overall_success_rate=rate,
                    by_category=by_cat,
                )
            except Exception as e:
                logger.error("Failed to get recovery statistics: %s", e)
                return RecoveryStatistics(category=cat_str or "ALL")

    def get_verification_distribution(
        self, category: Optional[str] = None, session_id: Optional[str] = None
    ) -> VerificationDistribution:
        """Computes PASS / FAIL / UNVERIFIED distribution across outcomes."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                clauses: List[str] = []
                params: List[Any] = []
                if category:
                    clauses.append("error_category = ?")
                    params.append(category)
                if session_id:
                    clauses.append("session_id = ?")
                    params.append(session_id)
                where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""

                cursor.execute(
                    f"""
                    SELECT verdict, COUNT(*) as cnt
                    FROM experience_outcomes
                    {where_clause}
                    GROUP BY verdict;
                    """,
                    tuple(params),
                )
                dist = {"PASS": 0, "FAIL": 0, "UNVERIFIED": 0}
                total = 0
                for r in cursor.fetchall():
                    v = r["verdict"]
                    c = r["cnt"]
                    dist[v] = c
                    total += c
                return VerificationDistribution(
                    pass_count=dist["PASS"],
                    fail_count=dist["FAIL"],
                    unverified_count=dist["UNVERIFIED"],
                    total_outcomes=total,
                )
            except Exception as e:
                logger.error("Failed to get verification distribution: %s", e)
                return VerificationDistribution()

    def get_recent_failure_trend(
        self,
        category: Optional[str] = None,
        days: int = 7,
        time_window_seconds: Optional[float] = None,
    ) -> Dict[str, int]:
        """Computes failure trend counts grouped by category over the recent timeframe."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                clauses: List[str] = []
                params: List[Any] = []
                if time_window_seconds is not None:
                    min_ts = time.time() - time_window_seconds
                    clauses.append("timestamp >= ?")
                    params.append(min_ts)
                else:
                    min_ts = time.time() - (days * 86400)
                    clauses.append("timestamp >= ?")
                    params.append(min_ts)

                if category:
                    clauses.append("category = ?")
                    params.append(category)

                where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
                cursor.execute(
                    f"""
                    SELECT category, COUNT(*) as cnt
                    FROM normalized_failures
                    {where_clause}
                    GROUP BY category
                    ORDER BY cnt DESC;
                    """,
                    tuple(params),
                )
                return {r["category"]: r["cnt"] for r in cursor.fetchall()}
            except Exception as e:
                logger.error("Failed to get recent failure trend: %s", e)
                return {}

    def get_failures_by_action_type(self, action_type: Optional[str] = None) -> List[FailureSummaryItem]:
        """Computes failure frequency grouped by action type."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT safe_context_json, action_id FROM normalized_failures;")
                rows = cursor.fetchall()
                counts: Dict[str, int] = {}
                for r in rows:
                    act_type = None
                    if r["safe_context_json"]:
                        try:
                            ctx = json.loads(r["safe_context_json"])
                            act_type = ctx.get("action_type")
                        except Exception:
                            pass
                    if not act_type:
                        act_type = "UNKNOWN"
                    if action_type is None or act_type == action_type:
                        counts[act_type] = counts.get(act_type, 0) + 1

                return [
                    FailureSummaryItem(category=atype, count=cnt)
                    for atype, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True)
                ]
            except Exception as e:
                logger.error("Failed to get failures by action type: %s", e)
                return []

    def get_record_counts(self) -> Dict[str, int]:
        """Returns row counts across all experience tables."""
        counts = {
            "sessions": 0,
            "missions": 0,
            "action_references": 0,
            "trace_references": 0,
            "evidence_references": 0,
            "outcomes": 0,
            "failures": 0,
            "recovery_attempts": 0,
        }
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                for table, key in [
                    ("review_sessions", "sessions"),
                    ("missions", "missions"),
                    ("action_references", "action_references"),
                    ("trace_references", "trace_references"),
                    ("evidence_references", "evidence_references"),
                    ("experience_outcomes", "outcomes"),
                    ("normalized_failures", "failures"),
                    ("recovery_attempts", "recovery_attempts"),
                ]:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table};")
                        counts[key] = cursor.fetchone()[0]
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Failed to get record counts: %s", e)
        return counts

    # -------------------------------------------------------------------------
    # Integrity and Health
    # -------------------------------------------------------------------------

    def run_integrity_check(self) -> Tuple[bool, str]:
        """
        Executes PRAGMA integrity_check and PRAGMA quick_check against the SQLite database.
        Returns (is_healthy, message).
        """
        with self._lock:
            if self._init_error:
                return False, f"Database initialization failed: {self._init_error}"
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                rows = cursor.fetchall()
                results = [r[0] for r in rows]
                if results == ["ok"]:
                    return True, "ok"
                return False, "; ".join(results)
            except Exception as e:
                return False, f"Integrity check failed with error: {e}"

    def get_health_report(self) -> ExperienceHealthReport:
        """Constructs a comprehensive health, integrity, and sizing report."""
        with self._lock:
            vinfo = get_version_info()
            db_path = self.config.database_path
            db_size = db_path.stat().st_size if db_path.exists() else 0

            if self._init_error:
                return ExperienceHealthReport(
                    enabled=True,
                    storage_path=str(self.config.base_dir),
                    database_file=str(db_path),
                    database_size_bytes=db_size,
                    schema_version=0,
                    runtime_version=vinfo.product_version,
                    installation_id=self._installation_id or "unknown",
                    health="DEGRADED",
                    integrity_check=f"Initialization error: {self._init_error}",
                    last_write=self._last_write_iso,
                    record_counts={},
                )

            is_ok, integrity_msg = self.run_integrity_check()
            record_counts = self.get_record_counts()

            # Read schema version from DB
            schema_ver = 0
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("PRAGMA user_version;")
                schema_ver = cursor.fetchone()[0]
            except Exception:
                pass

            health_status = "OK" if is_ok else "DEGRADED"

            return ExperienceHealthReport(
                enabled=True,
                storage_path=str(self.config.base_dir),
                database_file=str(db_path),
                database_size_bytes=db_size,
                schema_version=schema_ver,
                runtime_version=vinfo.product_version,
                installation_id=self._installation_id,
                health=health_status,
                integrity_check=integrity_msg,
                last_write=self._last_write_iso,
                record_counts=record_counts,
            )

    def close(self) -> None:
        """Closes connection cleanly."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __enter__(self) -> ExperienceStore:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
