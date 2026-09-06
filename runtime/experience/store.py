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
from runtime.experience.antigravity.contracts import (
    CorrelationConfidence,
    UserCorrectionType,
)
from runtime.experience.antigravity.models import (
    AgentArtifactRecord,
    AgentCorrectionRecord,
    AgentDwrCorrelationRecord,
    AgentSessionRecord,
    AgentSubagentRecord,
    AgentToolCallRecord,
    AgentTurnRecord,
)
from runtime.experience.privacy import PrivacyEnforcer, PrivacyViolationException
from runtime.experience.schema import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
)
from runtime.experience.learning.models import (
    CandidateCategory,
    CandidateStatus,
    DetectedPatternRecord,
    DurableKnowledgeRecord,
    GateResult,
    GovernanceDecision,
    GovernanceRecord,
    ImprovementCandidateRecord,
    KnowledgeStatus,
    ObservationRecord,
    ObservationStatus,
    ObservationType,
    PatternType,
    RiskLevel,
)
from runtime.experience.learning.field_intelligence import FieldIntelligenceEngine
from runtime.experience.learning.safety_gate import LearningSafetyGate

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
    # Antigravity Agent Record Operations (Milestone 2.1 Prompt 3)
    # -------------------------------------------------------------------------

    def record_agent_session(self, record: AgentSessionRecord) -> Optional[AgentSessionRecord]:
        """Persists or updates an Antigravity agent session record."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="agent_session.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_sessions (
                        agent_session_id, conversation_id, agent_id, workspace_id,
                        started_at, completed_at, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_session_id) DO UPDATE SET
                        completed_at = excluded.completed_at,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.agent_session_id,
                        record.conversation_id,
                        record.agent_id,
                        record.workspace_id,
                        record.started_at,
                        record.completed_at,
                        record.status,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent session %s: %s", record.agent_session_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent session: {e}") from e
                return None

    def record_agent_turn(self, record: AgentTurnRecord) -> Optional[AgentTurnRecord]:
        """Persists or updates an Antigravity agent turn record."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="agent_turn.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_turns (
                        turn_id, agent_session_id, conversation_id, parent_turn_id,
                        step_index, timestamp, iso_timestamp, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(turn_id) DO UPDATE SET
                        status = excluded.status,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.turn_id,
                        record.agent_session_id,
                        record.conversation_id,
                        record.parent_turn_id,
                        record.step_index,
                        record.timestamp,
                        record.iso_timestamp,
                        record.status,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent turn %s: %s", record.turn_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent turn: {e}") from e
                return None

    def record_agent_tool_call(self, record: AgentToolCallRecord) -> Optional[AgentToolCallRecord]:
        """Persists an Antigravity tool call with sanitized structural summary."""
        clean_summary = PrivacyEnforcer.check_and_sanitize(record.safe_summary, context="agent_tool_call.safe_summary")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_tool_calls (
                        tool_call_id, turn_id, agent_session_id, conversation_id,
                        tool_name, tool_category, success, error_class, duration_ms,
                        timestamp, iso_timestamp, safe_summary_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tool_call_id) DO UPDATE SET
                        success = excluded.success,
                        error_class = excluded.error_class,
                        duration_ms = excluded.duration_ms,
                        safe_summary_json = excluded.safe_summary_json;
                    """,
                    (
                        record.tool_call_id,
                        record.turn_id,
                        record.agent_session_id,
                        record.conversation_id,
                        record.tool_name,
                        record.tool_category,
                        1 if record.success else 0,
                        record.error_class,
                        record.duration_ms,
                        record.timestamp,
                        record.iso_timestamp,
                        json.dumps(clean_summary, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent tool call %s: %s", record.tool_call_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent tool call: {e}") from e
                return None

    def record_agent_subagent(self, record: AgentSubagentRecord) -> Optional[AgentSubagentRecord]:
        """Persists an Antigravity subagent delegation record."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="agent_subagent.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_subagents (
                        subagent_id, parent_agent_id, delegation_id, conversation_id,
                        agent_session_id, status, created_at, completed_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subagent_id) DO UPDATE SET
                        status = excluded.status,
                        completed_at = excluded.completed_at,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.subagent_id,
                        record.parent_agent_id,
                        record.delegation_id,
                        record.conversation_id,
                        record.agent_session_id,
                        record.status,
                        record.created_at,
                        record.completed_at,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent subagent %s: %s", record.subagent_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent subagent: {e}") from e
                return None

    def record_agent_artifact(self, record: AgentArtifactRecord) -> Optional[AgentArtifactRecord]:
        """Persists a safe Antigravity artifact reference."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="agent_artifact.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_artifacts (
                        artifact_id, artifact_type, safe_reference, agent_session_id,
                        turn_id, timestamp, iso_timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(artifact_id) DO UPDATE SET
                        safe_reference = excluded.safe_reference,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.artifact_id,
                        record.artifact_type,
                        record.safe_reference,
                        record.agent_session_id,
                        record.turn_id,
                        record.timestamp,
                        record.iso_timestamp,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent artifact %s: %s", record.artifact_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent artifact: {e}") from e
                return None

    def record_agent_correction(self, record: AgentCorrectionRecord) -> Optional[AgentCorrectionRecord]:
        """Persists a structured user or agent correction classification."""
        clean_details = PrivacyEnforcer.check_and_sanitize(record.classification_details, context="agent_correction.details")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_corrections (
                        correction_id, correction_type, agent_session_id, conversation_id,
                        turn_id, tool_call_id, related_dwr_session_id, related_action_id,
                        timestamp, iso_timestamp, classification_details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(correction_id) DO UPDATE SET
                        classification_details_json = excluded.classification_details_json;
                    """,
                    (
                        record.correction_id,
                        record.correction_type,
                        record.agent_session_id,
                        record.conversation_id,
                        record.turn_id,
                        record.tool_call_id,
                        record.related_dwr_session_id,
                        record.related_action_id,
                        record.timestamp,
                        record.iso_timestamp,
                        json.dumps(clean_details, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent correction %s: %s", record.correction_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent correction: {e}") from e
                return None

    def record_agent_correlation(self, record: AgentDwrCorrelationRecord) -> Optional[AgentDwrCorrelationRecord]:
        """Persists an explicit relational correlation between Antigravity and DWR."""
        clean_metadata = PrivacyEnforcer.check_and_sanitize(record.metadata, context="agent_correlation.metadata")
        conf_str = record.confidence.value if isinstance(record.confidence, CorrelationConfidence) else str(record.confidence)

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO agent_dwr_correlations (
                        correlation_id, confidence, agent_session_id, conversation_id,
                        turn_id, tool_call_id, dwr_session_id, dwr_mission_id,
                        dwr_action_id, correlation_source, timestamp, iso_timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(correlation_id) DO UPDATE SET
                        confidence = excluded.confidence,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.correlation_id,
                        conf_str,
                        record.agent_session_id,
                        record.conversation_id,
                        record.turn_id,
                        record.tool_call_id,
                        record.dwr_session_id,
                        record.dwr_mission_id,
                        record.dwr_action_id,
                        record.correlation_source,
                        record.timestamp,
                        record.iso_timestamp,
                        json.dumps(clean_metadata, default=str),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record agent correlation %s: %s", record.correlation_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record agent correlation: {e}") from e
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

    # -------------------------------------------------------------------------
    # Antigravity Historical Intelligence Queries (Milestone 2.1 Prompt 3)
    # -------------------------------------------------------------------------

    def get_agent_sessions(self, conversation_id: Optional[str] = None, limit: int = 50) -> List[AgentSessionRecord]:
        """Retrieves agent session records, optionally filtered by conversation_id."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                if conversation_id:
                    cursor.execute(
                        "SELECT * FROM agent_sessions WHERE conversation_id = ? ORDER BY started_at DESC LIMIT ?;",
                        (conversation_id, limit),
                    )
                else:
                    cursor.execute("SELECT * FROM agent_sessions ORDER BY started_at DESC LIMIT ?;", (limit,))
                results: List[AgentSessionRecord] = []
                for row in cursor.fetchall():
                    results.append(
                        AgentSessionRecord(
                            agent_session_id=row["agent_session_id"],
                            conversation_id=row["conversation_id"],
                            agent_id=row["agent_id"],
                            workspace_id=row["workspace_id"],
                            started_at=row["started_at"],
                            completed_at=row["completed_at"],
                            status=row["status"],
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get agent sessions: %s", e)
                return []

    def get_agent_tool_calls(
        self,
        agent_session_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentToolCallRecord]:
        """Retrieves agent tool calls matching optional filters."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM agent_tool_calls"
                clauses: List[str] = []
                params: List[Any] = []

                if agent_session_id:
                    clauses.append("agent_session_id = ?")
                    params.append(agent_session_id)
                if tool_name:
                    clauses.append("tool_name = ?")
                    params.append(tool_name)

                if clauses:
                    query += " WHERE " + " AND ".join(clauses)

                query += " ORDER BY timestamp DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, tuple(params))
                results: List[AgentToolCallRecord] = []
                for row in cursor.fetchall():
                    results.append(
                        AgentToolCallRecord(
                            tool_call_id=row["tool_call_id"],
                            turn_id=row["turn_id"],
                            agent_session_id=row["agent_session_id"],
                            conversation_id=row["conversation_id"],
                            tool_name=row["tool_name"],
                            tool_category=row["tool_category"],
                            success=bool(row["success"]),
                            error_class=row["error_class"],
                            duration_ms=row["duration_ms"],
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                            safe_summary=json.loads(row["safe_summary_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get agent tool calls: %s", e)
                return []

    def get_agent_tool_calls_for_session(self, dwr_session_id: str) -> List[AgentToolCallRecord]:
        """
        Historical Query: Which agent tool calls were associated with a given DWR session?
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT t.*
                    FROM agent_tool_calls t
                    JOIN agent_dwr_correlations c
                      ON (c.tool_call_id IS NOT NULL AND c.tool_call_id != '' AND t.tool_call_id = c.tool_call_id)
                      OR ((c.tool_call_id IS NULL OR c.tool_call_id = '') AND (
                          (c.turn_id IS NOT NULL AND c.turn_id != '' AND t.turn_id = c.turn_id)
                          OR (c.agent_session_id IS NOT NULL AND c.agent_session_id != '' AND t.agent_session_id = c.agent_session_id)
                      ))
                    WHERE c.dwr_session_id = ?
                    ORDER BY t.timestamp ASC;
                    """,
                    (dwr_session_id,),
                )
                results: List[AgentToolCallRecord] = []
                for row in cursor.fetchall():
                    results.append(
                        AgentToolCallRecord(
                            tool_call_id=row["tool_call_id"],
                            turn_id=row["turn_id"],
                            agent_session_id=row["agent_session_id"],
                            conversation_id=row["conversation_id"],
                            tool_name=row["tool_name"],
                            tool_category=row["tool_category"],
                            success=bool(row["success"]),
                            error_class=row["error_class"],
                            duration_ms=row["duration_ms"],
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                            safe_summary=json.loads(row["safe_summary_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get agent tool calls for session %s: %s", dwr_session_id, e)
                return []

    def get_agent_activity_for_dwr_action(self, dwr_action_id: str) -> List[AgentToolCallRecord]:
        """
        Historical Query: Which agent tool call resulted in or preceded a DWR action?
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT t.*
                    FROM agent_tool_calls t
                    JOIN agent_dwr_correlations c
                      ON (c.tool_call_id IS NOT NULL AND c.tool_call_id != '' AND t.tool_call_id = c.tool_call_id)
                      OR ((c.tool_call_id IS NULL OR c.tool_call_id = '') AND (
                          (c.turn_id IS NOT NULL AND c.turn_id != '' AND t.turn_id = c.turn_id)
                      ))
                    WHERE c.dwr_action_id = ?
                    ORDER BY t.timestamp ASC;
                    """,
                    (dwr_action_id,),
                )
                results: List[AgentToolCallRecord] = []
                for row in cursor.fetchall():
                    results.append(
                        AgentToolCallRecord(
                            tool_call_id=row["tool_call_id"],
                            turn_id=row["turn_id"],
                            agent_session_id=row["agent_session_id"],
                            conversation_id=row["conversation_id"],
                            tool_name=row["tool_name"],
                            tool_category=row["tool_category"],
                            success=bool(row["success"]),
                            error_class=row["error_class"],
                            duration_ms=row["duration_ms"],
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                            safe_summary=json.loads(row["safe_summary_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get agent activity for action %s: %s", dwr_action_id, e)
                return []

    def get_agent_tool_calls_by_outcome(self, verdict: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Historical Query: Relates agent tool calls to successful (PASS), failed (FAIL),
        or UNVERIFIED DWR review outcomes.
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT
                        t.tool_call_id,
                        t.tool_name,
                        t.tool_category,
                        t.success as tool_success,
                        o.verdict as review_verdict,
                        c.confidence as correlation_confidence,
                        c.dwr_session_id,
                        t.timestamp
                    FROM agent_tool_calls t
                    JOIN agent_dwr_correlations c
                      ON (c.tool_call_id IS NOT NULL AND c.tool_call_id != '' AND t.tool_call_id = c.tool_call_id)
                      OR ((c.tool_call_id IS NULL OR c.tool_call_id = '') AND (
                          (c.turn_id IS NOT NULL AND c.turn_id != '' AND t.turn_id = c.turn_id)
                          OR (c.agent_session_id IS NOT NULL AND c.agent_session_id != '' AND t.agent_session_id = c.agent_session_id)
                      ))
                    JOIN experience_outcomes o ON c.dwr_session_id = o.session_id
                    WHERE o.verdict = ?
                    ORDER BY t.timestamp DESC
                    LIMIT ?;
                    """,
                    (verdict.upper(), limit),
                )
                results: List[Dict[str, Any]] = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "tool_call_id": row["tool_call_id"],
                            "tool_name": row["tool_name"],
                            "tool_category": row["tool_category"],
                            "tool_success": bool(row["tool_success"]),
                            "review_verdict": row["review_verdict"],
                            "correlation_confidence": row["correlation_confidence"],
                            "dwr_session_id": row["dwr_session_id"],
                            "timestamp": row["timestamp"],
                        }
                    )
                return results
            except Exception as e:
                logger.error("Failed to get tool calls by outcome %s: %s", verdict, e)
                return []

    def get_recovery_frequency_by_agent_tool_category(self) -> List[Dict[str, Any]]:
        """
        Historical Query: How often did a DWR session require recovery after specific agent tool categories?
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        t.tool_category,
                        COUNT(DISTINCT r.recovery_id) as recovery_attempts_count,
                        COUNT(DISTINCT c.dwr_session_id) as affected_sessions_count
                    FROM recovery_attempts r
                    JOIN agent_dwr_correlations c ON r.session_id = c.dwr_session_id
                    JOIN agent_tool_calls t
                      ON (c.tool_call_id IS NOT NULL AND c.tool_call_id != '' AND t.tool_call_id = c.tool_call_id)
                      OR ((c.tool_call_id IS NULL OR c.tool_call_id = '') AND (
                          (c.turn_id IS NOT NULL AND c.turn_id != '' AND t.turn_id = c.turn_id)
                          OR (c.agent_session_id IS NOT NULL AND c.agent_session_id != '' AND t.agent_session_id = c.agent_session_id)
                      ))
                    GROUP BY t.tool_category
                    ORDER BY recovery_attempts_count DESC;
                    """
                )
                results: List[Dict[str, Any]] = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "tool_category": row["tool_category"],
                            "recovery_attempts_count": row["recovery_attempts_count"],
                            "affected_sessions_count": row["affected_sessions_count"],
                        }
                    )
                return results
            except Exception as e:
                logger.error("Failed to get recovery frequency by tool category: %s", e)
                return []

    def get_user_corrections_for_failures(self) -> List[AgentCorrectionRecord]:
        """
        Historical Query: Which agent/user corrections followed reviewer failures?
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT ac.*
                    FROM agent_corrections ac
                    JOIN agent_dwr_correlations c
                      ON ac.related_dwr_session_id = c.dwr_session_id
                      OR ac.agent_session_id = c.agent_session_id
                      OR ac.conversation_id = c.conversation_id
                    JOIN normalized_failures f ON c.dwr_session_id = f.session_id
                    ORDER BY ac.timestamp DESC;
                    """
                )
                results: List[AgentCorrectionRecord] = []
                for row in cursor.fetchall():
                    results.append(
                        AgentCorrectionRecord(
                            correction_id=row["correction_id"],
                            correction_type=row["correction_type"],
                            agent_session_id=row["agent_session_id"],
                            conversation_id=row["conversation_id"],
                            turn_id=row["turn_id"],
                            tool_call_id=row["tool_call_id"],
                            related_dwr_session_id=row["related_dwr_session_id"],
                            related_action_id=row["related_action_id"],
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                            classification_details=json.loads(row["classification_details_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get corrections for failures: %s", e)
                return []

    def get_agent_dwr_correlations(
        self,
        dwr_session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        min_confidence: Optional[Union[str, CorrelationConfidence]] = None,
        limit: int = 100,
    ) -> List[AgentDwrCorrelationRecord]:
        """Retrieves relational correlation records matching filter criteria."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM agent_dwr_correlations"
                clauses: List[str] = []
                params: List[Any] = []

                if dwr_session_id:
                    clauses.append("dwr_session_id = ?")
                    params.append(dwr_session_id)
                if conversation_id:
                    clauses.append("conversation_id = ?")
                    params.append(conversation_id)
                if min_confidence:
                    conf_val = min_confidence.value if isinstance(min_confidence, CorrelationConfidence) else str(min_confidence)
                    clauses.append("confidence = ?")
                    params.append(conf_val)

                if clauses:
                    query += " WHERE " + " AND ".join(clauses)

                query += " ORDER BY timestamp DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, tuple(params))
                results: List[AgentDwrCorrelationRecord] = []
                for row in cursor.fetchall():
                    results.append(
                        AgentDwrCorrelationRecord(
                            correlation_id=row["correlation_id"],
                            confidence=CorrelationConfidence(row["confidence"]),
                            agent_session_id=row["agent_session_id"],
                            conversation_id=row["conversation_id"],
                            turn_id=row["turn_id"],
                            tool_call_id=row["tool_call_id"],
                            dwr_session_id=row["dwr_session_id"],
                            dwr_mission_id=row["dwr_mission_id"],
                            dwr_action_id=row["dwr_action_id"],
                            correlation_source=row["correlation_source"],
                            timestamp=float(row["timestamp"]),
                            iso_timestamp=row["iso_timestamp"],
                            metadata=json.loads(row["metadata_json"] or "{}"),
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to get correlations: %s", e)
                return []

    def get_agent_experience_summary(self) -> Dict[str, Any]:
        """Computes aggregate metrics of Antigravity agent interactions with DWR."""
        counts = self.get_record_counts()
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT tool_category, COUNT(*) as cnt FROM agent_tool_calls GROUP BY tool_category ORDER BY cnt DESC;"
                )
                category_counts = {row["tool_category"]: row["cnt"] for row in cursor.fetchall()}

                cursor.execute(
                    "SELECT confidence, COUNT(*) as cnt FROM agent_dwr_correlations GROUP BY confidence;"
                )
                confidence_distribution = {row["confidence"]: row["cnt"] for row in cursor.fetchall()}

                return {
                    "agent_sessions": counts.get("agent_sessions", 0),
                    "agent_tool_calls": counts.get("agent_tool_calls", 0),
                    "correlations": counts.get("agent_dwr_correlations", 0),
                    "corrections": counts.get("agent_corrections", 0),
                    "subagents": counts.get("agent_subagents", 0),
                    "artifacts": counts.get("agent_artifacts", 0),
                    "tool_categories": category_counts,
                    "confidence_distribution": confidence_distribution,
                }
            except Exception as e:
                logger.error("Failed to get agent experience summary: %s", e)
                return {
                    "agent_sessions": counts.get("agent_sessions", 0),
                    "agent_tool_calls": counts.get("agent_tool_calls", 0),
                    "correlations": counts.get("agent_dwr_correlations", 0),
                    "corrections": counts.get("agent_corrections", 0),
                }

    # -------------------------------------------------------------------------
    # Learning, Governance, and Durable Knowledge Operations (Milestone 2.1 Prompt 4)
    # -------------------------------------------------------------------------

    def record_observation(self, record: ObservationRecord) -> Optional[ObservationRecord]:
        """Persists or updates an empirical observation record."""
        validate_scope_promotion(record.scope)
        clean_details = LearningSafetyGate.validate_learning_payload(record.details, context="observation.details")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                prov_dict = record.provenance.to_dict() if record.provenance else {}

                # Check if observation already exists by observation_id or (signature, scope, project_id)
                cursor.execute(
                    "SELECT observation_id, occurrence_count, source_refs_json FROM observations WHERE observation_id = ? OR (signature = ? AND scope = ? AND (project_id = ? OR (project_id IS NULL AND ? IS NULL)));",
                    (record.observation_id, record.signature, record.scope.value if isinstance(record.scope, ExperienceScope) else str(record.scope), record.project_id, record.project_id),
                )
                existing = cursor.fetchone()
                if existing:
                    existing_id, existing_count, existing_refs_json = existing
                    existing_refs = json.loads(existing_refs_json) if existing_refs_json else []
                    merged_refs = list(dict.fromkeys(existing_refs + record.source_refs))
                    new_count = existing_count + record.occurrence_count
                    cursor.execute(
                        """
                        UPDATE observations SET
                            occurrence_count = ?,
                            confidence = ?,
                            status = ?,
                            last_observed_at = ?,
                            last_observed_ts = ?,
                            source_refs_json = ?,
                            details_json = ?
                        WHERE observation_id = ?;
                        """,
                        (
                            new_count,
                            record.confidence,
                            record.status.value if isinstance(record.status, ObservationStatus) else str(record.status),
                            record.last_observed_at,
                            record.last_observed_ts,
                            json.dumps(merged_refs),
                            json.dumps(clean_details),
                            existing_id,
                        ),
                    )
                    record.observation_id = existing_id
                    record.occurrence_count = new_count
                    record.source_refs = merged_refs
                else:
                    cursor.execute(
                        """
                        INSERT INTO observations (
                            observation_id, observation_type, scope, project_id, session_id,
                            signature, occurrence_count, confidence, status,
                            first_observed_at, last_observed_at, first_observed_ts, last_observed_ts,
                            source_refs_json, provenance_json, details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            record.observation_id,
                            record.observation_type.value if isinstance(record.observation_type, ObservationType) else str(record.observation_type),
                            record.scope.value if isinstance(record.scope, ExperienceScope) else str(record.scope),
                            record.project_id,
                            record.session_id,
                            record.signature,
                            record.occurrence_count,
                            record.confidence,
                            record.status.value if isinstance(record.status, ObservationStatus) else str(record.status),
                            record.first_observed_at,
                            record.last_observed_at,
                            record.first_observed_ts,
                            record.last_observed_ts,
                            json.dumps(record.source_refs),
                            json.dumps(prov_dict),
                            json.dumps(clean_details),
                        ),
                    )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record observation %s: %s", record.observation_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record observation: {e}") from e
                return None

    def get_observations(
        self,
        signature: Optional[str] = None,
        observation_type: Optional[Union[str, ObservationType]] = None,
        scope: Optional[Union[str, ExperienceScope]] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[ObservationRecord]:
        """Retrieves observations with optional filtering."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM observations WHERE 1=1"
                params: List[Any] = []
                if signature:
                    query += " AND signature = ?"
                    params.append(signature)
                if observation_type:
                    ot = observation_type.value if isinstance(observation_type, ObservationType) else str(observation_type)
                    query += " AND observation_type = ?"
                    params.append(ot)
                if scope:
                    sc = scope.value if isinstance(scope, ExperienceScope) else str(scope)
                    query += " AND scope = ?"
                    params.append(sc)
                if project_id:
                    query += " AND (project_id = ? OR project_id IS NULL)"
                    params.append(project_id)
                query += " ORDER BY last_observed_ts DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    source_refs = json.loads(r["source_refs_json"]) if r["source_refs_json"] else []
                    prov = json.loads(r["provenance_json"]) if r["provenance_json"] else None
                    details = json.loads(r["details_json"]) if r["details_json"] else {}
                    results.append(
                        ObservationRecord(
                            observation_id=r["observation_id"],
                            observation_type=ObservationType(r["observation_type"]),
                            signature=r["signature"],
                            scope=ExperienceScope(r["scope"]),
                            project_id=r["project_id"],
                            session_id=r["session_id"],
                            occurrence_count=r["occurrence_count"],
                            confidence=r["confidence"],
                            status=ObservationStatus(r["status"]),
                            first_observed_at=r["first_observed_at"],
                            last_observed_at=r["last_observed_at"],
                            first_observed_ts=r["first_observed_ts"],
                            last_observed_ts=r["last_observed_ts"],
                            source_refs=source_refs,
                            provenance=ProvenanceRecord.from_dict(prov) if prov else None,
                            details=details,
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to query observations: %s", e)
                return []

    def record_pattern(self, record: DetectedPatternRecord) -> Optional[DetectedPatternRecord]:
        """Persists or updates a detected pattern record."""
        validate_scope_promotion(record.scope)
        clean_details = LearningSafetyGate.validate_learning_payload(record.details, context="pattern.details")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO detected_patterns (
                        pattern_id, pattern_type, signature, scope, project_id,
                        occurrence_count, session_count, confidence,
                        first_seen_at, last_seen_at, first_seen_ts, last_seen_ts,
                        observation_refs_json, summary, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pattern_id) DO UPDATE SET
                        occurrence_count = excluded.occurrence_count,
                        session_count = excluded.session_count,
                        confidence = excluded.confidence,
                        last_seen_at = excluded.last_seen_at,
                        last_seen_ts = excluded.last_seen_ts,
                        observation_refs_json = excluded.observation_refs_json,
                        summary = excluded.summary,
                        details_json = excluded.details_json;
                    """,
                    (
                        record.pattern_id,
                        record.pattern_type.value if isinstance(record.pattern_type, PatternType) else str(record.pattern_type),
                        record.signature,
                        record.scope.value if isinstance(record.scope, ExperienceScope) else str(record.scope),
                        record.project_id,
                        record.occurrence_count,
                        record.session_count,
                        record.confidence,
                        record.first_seen_at,
                        record.last_seen_at,
                        record.first_seen_ts,
                        record.last_seen_ts,
                        json.dumps(record.observation_refs),
                        record.summary,
                        json.dumps(clean_details),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record pattern %s: %s", record.pattern_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record pattern: {e}") from e
                return None

    def get_patterns(
        self,
        pattern_type: Optional[Union[str, PatternType]] = None,
        scope: Optional[Union[str, ExperienceScope]] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[DetectedPatternRecord]:
        """Retrieves detected patterns with optional filtering."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM detected_patterns WHERE 1=1"
                params: List[Any] = []
                if pattern_type:
                    pt = pattern_type.value if isinstance(pattern_type, PatternType) else str(pattern_type)
                    query += " AND pattern_type = ?"
                    params.append(pt)
                if scope:
                    sc = scope.value if isinstance(scope, ExperienceScope) else str(scope)
                    query += " AND scope = ?"
                    params.append(sc)
                if project_id:
                    query += " AND (project_id = ? OR project_id IS NULL)"
                    params.append(project_id)
                query += " ORDER BY occurrence_count DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    obs_refs = json.loads(r["observation_refs_json"]) if r["observation_refs_json"] else []
                    details = json.loads(r["details_json"]) if r["details_json"] else {}
                    results.append(
                        DetectedPatternRecord(
                            pattern_id=r["pattern_id"],
                            pattern_type=PatternType(r["pattern_type"]),
                            signature=r["signature"],
                            summary=r["summary"],
                            scope=ExperienceScope(r["scope"]),
                            project_id=r["project_id"],
                            occurrence_count=r["occurrence_count"],
                            session_count=r["session_count"],
                            confidence=r["confidence"],
                            first_seen_at=r["first_seen_at"],
                            last_seen_at=r["last_seen_at"],
                            first_seen_ts=r["first_seen_ts"],
                            last_seen_ts=r["last_seen_ts"],
                            observation_refs=obs_refs,
                            details=details,
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to query patterns: %s", e)
                return []

    def record_improvement_candidate(self, record: ImprovementCandidateRecord) -> Optional[ImprovementCandidateRecord]:
        """Persists or updates an improvement candidate."""
        validate_scope_promotion(record.scope)
        clean_metadata = LearningSafetyGate.validate_learning_payload(record.metadata, context="candidate.metadata")
        gates_dict = {k: v.to_dict() for k, v in record.gate_results.items()}
        prov_dict = record.provenance.to_dict() if record.provenance else {}

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO improvement_candidates (
                        candidate_id, scope, project_id, category, affected_subsystem, pattern_id,
                        evidence_count, session_count, confidence, risk_level, status,
                        rationale_summary, first_seen_at, last_seen_at, created_at, updated_at,
                        gate_results_json, provenance_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                        evidence_count = excluded.evidence_count,
                        session_count = excluded.session_count,
                        confidence = excluded.confidence,
                        risk_level = excluded.risk_level,
                        status = excluded.status,
                        rationale_summary = excluded.rationale_summary,
                        last_seen_at = excluded.last_seen_at,
                        updated_at = excluded.updated_at,
                        gate_results_json = excluded.gate_results_json,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.candidate_id,
                        record.scope.value if isinstance(record.scope, ExperienceScope) else str(record.scope),
                        record.project_id,
                        record.category.value if isinstance(record.category, CandidateCategory) else str(record.category),
                        record.affected_subsystem,
                        record.pattern_id,
                        record.evidence_count,
                        record.session_count,
                        record.confidence,
                        record.risk_level.value if isinstance(record.risk_level, RiskLevel) else str(record.risk_level),
                        record.status.value if isinstance(record.status, CandidateStatus) else str(record.status),
                        record.rationale_summary,
                        record.first_seen_at,
                        record.last_seen_at,
                        record.created_at,
                        record.updated_at,
                        json.dumps(gates_dict),
                        json.dumps(prov_dict),
                        json.dumps(clean_metadata),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record improvement candidate %s: %s", record.candidate_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record improvement candidate: {e}") from e
                return None

    def get_improvement_candidates(
        self,
        status: Optional[Union[str, CandidateStatus]] = None,
        category: Optional[Union[str, CandidateCategory]] = None,
        scope: Optional[Union[str, ExperienceScope]] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[ImprovementCandidateRecord]:
        """Retrieves improvement candidates with optional filtering."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM improvement_candidates WHERE 1=1"
                params: List[Any] = []
                if status:
                    st = status.value if isinstance(status, CandidateStatus) else str(status)
                    query += " AND status = ?"
                    params.append(st)
                if category:
                    cat = category.value if isinstance(category, CandidateCategory) else str(category)
                    query += " AND category = ?"
                    params.append(cat)
                if scope:
                    sc = scope.value if isinstance(scope, ExperienceScope) else str(scope)
                    query += " AND scope = ?"
                    params.append(sc)
                if project_id:
                    query += " AND (project_id = ? OR project_id IS NULL)"
                    params.append(project_id)
                query += " ORDER BY evidence_count DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    gates_raw = json.loads(r["gate_results_json"]) if r["gate_results_json"] else {}
                    gates = {k: GateResult.from_dict(v) for k, v in gates_raw.items()}
                    prov = json.loads(r["provenance_json"]) if r["provenance_json"] else None
                    metadata = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
                    results.append(
                        ImprovementCandidateRecord(
                            candidate_id=r["candidate_id"],
                            scope=ExperienceScope(r["scope"]),
                            project_id=r["project_id"],
                            category=CandidateCategory(r["category"]),
                            affected_subsystem=r["affected_subsystem"],
                            pattern_id=r["pattern_id"],
                            evidence_count=r["evidence_count"],
                            session_count=r["session_count"],
                            confidence=r["confidence"],
                            risk_level=RiskLevel(r["risk_level"]),
                            status=CandidateStatus(r["status"]),
                            rationale_summary=r["rationale_summary"],
                            first_seen_at=r["first_seen_at"],
                            last_seen_at=r["last_seen_at"],
                            created_at=r["created_at"],
                            updated_at=r["updated_at"],
                            gate_results=gates,
                            provenance=ProvenanceRecord.from_dict(prov) if prov else None,
                            metadata=metadata,
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to query improvement candidates: %s", e)
                return []

    def get_improvement_candidate(self, candidate_id: str) -> Optional[ImprovementCandidateRecord]:
        """Looks up a single candidate by ID."""
        candidates = self.get_improvement_candidates(limit=1000)
        for c in candidates:
            if c.candidate_id == candidate_id:
                return c
        return None

    def record_governance_decision(self, record: GovernanceRecord) -> Optional[GovernanceRecord]:
        """Persists a human governance decision."""
        validate_scope_promotion(record.decision_scope)
        clean_metadata = LearningSafetyGate.validate_learning_payload(record.metadata, context="governance.metadata")

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO governance_records (
                        governance_id, candidate_id, decision, decision_scope, reviewer,
                        decision_timestamp, iso_timestamp, rationale, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(governance_id) DO UPDATE SET
                        decision = excluded.decision,
                        rationale = excluded.rationale,
                        metadata_json = excluded.metadata_json;
                    """,
                    (
                        record.governance_id,
                        record.candidate_id,
                        record.decision.value if isinstance(record.decision, GovernanceDecision) else str(record.decision),
                        record.decision_scope.value if isinstance(record.decision_scope, ExperienceScope) else str(record.decision_scope),
                        record.reviewer,
                        record.decision_timestamp,
                        record.iso_timestamp,
                        record.rationale,
                        json.dumps(clean_metadata),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record governance decision %s: %s", record.governance_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record governance decision: {e}") from e
                return None

    def get_governance_records(self, candidate_id: Optional[str] = None, limit: int = 100) -> List[GovernanceRecord]:
        """Queries governance decisions."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM governance_records WHERE 1=1"
                params: List[Any] = []
                if candidate_id:
                    query += " AND candidate_id = ?"
                    params.append(candidate_id)
                query += " ORDER BY decision_timestamp DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    metadata = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
                    results.append(
                        GovernanceRecord(
                            governance_id=r["governance_id"],
                            candidate_id=r["candidate_id"],
                            decision=GovernanceDecision(r["decision"]),
                            decision_scope=ExperienceScope(r["decision_scope"]),
                            reviewer=r["reviewer"],
                            decision_timestamp=r["decision_timestamp"],
                            iso_timestamp=r["iso_timestamp"],
                            rationale=r["rationale"],
                            metadata=metadata,
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to query governance records: %s", e)
                return []

    def record_durable_knowledge(self, record: DurableKnowledgeRecord) -> Optional[DurableKnowledgeRecord]:
        """Persists or updates durable knowledge item."""
        validate_scope_promotion(record.scope)
        prov_dict = record.provenance.to_dict() if record.provenance else {}

        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO durable_knowledge (
                        knowledge_id, version, scope, project_id, candidate_id,
                        normalized_statement, supporting_evidence_refs_json, validation_metadata_json,
                        approval_metadata_json, confidence, status,
                        created_at, updated_at, review_due_at, last_confirmed_at, last_used_at,
                        superseded_by, contradiction_count, provenance_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(knowledge_id) DO UPDATE SET
                        version = excluded.version,
                        normalized_statement = excluded.normalized_statement,
                        supporting_evidence_refs_json = excluded.supporting_evidence_refs_json,
                        validation_metadata_json = excluded.validation_metadata_json,
                        approval_metadata_json = excluded.approval_metadata_json,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        review_due_at = excluded.review_due_at,
                        last_confirmed_at = excluded.last_confirmed_at,
                        last_used_at = excluded.last_used_at,
                        superseded_by = excluded.superseded_by,
                        contradiction_count = excluded.contradiction_count;
                    """,
                    (
                        record.knowledge_id,
                        record.version,
                        record.scope.value if isinstance(record.scope, ExperienceScope) else str(record.scope),
                        record.project_id,
                        record.candidate_id,
                        record.normalized_statement,
                        json.dumps(record.supporting_evidence_refs),
                        json.dumps(record.validation_metadata),
                        json.dumps(record.approval_metadata),
                        record.confidence,
                        record.status.value if isinstance(record.status, KnowledgeStatus) else str(record.status),
                        record.created_at,
                        record.updated_at,
                        record.review_due_at,
                        record.last_confirmed_at,
                        record.last_used_at,
                        record.superseded_by,
                        record.contradiction_count,
                        json.dumps(prov_dict),
                    ),
                )
                conn.commit()
                self._last_write_iso = datetime.now(timezone.utc).isoformat()
                return record
            except Exception as e:
                logger.error("Failed to record durable knowledge %s: %s", record.knowledge_id, e)
                if not self.config.fail_safe_mode:
                    raise ExperiencePersistenceException(f"Failed to record durable knowledge: {e}") from e
                return None

    def get_durable_knowledge(
        self,
        status: Optional[Union[str, KnowledgeStatus]] = None,
        scope: Optional[Union[str, ExperienceScope]] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[DurableKnowledgeRecord]:
        """Queries durable knowledge items."""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                query = "SELECT * FROM durable_knowledge WHERE 1=1"
                params: List[Any] = []
                if status:
                    st = status.value if isinstance(status, KnowledgeStatus) else str(status)
                    query += " AND status = ?"
                    params.append(st)
                if scope:
                    sc = scope.value if isinstance(scope, ExperienceScope) else str(scope)
                    query += " AND scope = ?"
                    params.append(sc)
                if project_id:
                    query += " AND (project_id = ? OR project_id IS NULL)"
                    params.append(project_id)
                query += " ORDER BY updated_at DESC LIMIT ?;"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                results = []
                for r in rows:
                    supp = json.loads(r["supporting_evidence_refs_json"]) if r["supporting_evidence_refs_json"] else []
                    val_meta = json.loads(r["validation_metadata_json"]) if r["validation_metadata_json"] else {}
                    app_meta = json.loads(r["approval_metadata_json"]) if r["approval_metadata_json"] else {}
                    prov = json.loads(r["provenance_json"]) if r["provenance_json"] else None
                    results.append(
                        DurableKnowledgeRecord(
                            knowledge_id=r["knowledge_id"],
                            normalized_statement=r["normalized_statement"],
                            version=r["version"],
                            scope=ExperienceScope(r["scope"]),
                            project_id=r["project_id"],
                            candidate_id=r["candidate_id"],
                            supporting_evidence_refs=supp,
                            validation_metadata=val_meta,
                            approval_metadata=app_meta,
                            confidence=r["confidence"],
                            status=KnowledgeStatus(r["status"]),
                            created_at=r["created_at"],
                            updated_at=r["updated_at"],
                            review_due_at=r["review_due_at"],
                            last_confirmed_at=r["last_confirmed_at"],
                            last_used_at=r["last_used_at"],
                            superseded_by=r["superseded_by"],
                            contradiction_count=r["contradiction_count"],
                            provenance=ProvenanceRecord.from_dict(prov) if prov else None,
                        )
                    )
                return results
            except Exception as e:
                logger.error("Failed to query durable knowledge: %s", e)
                return []

    def get_durable_knowledge_item(self, knowledge_id: str) -> Optional[DurableKnowledgeRecord]:
        """Looks up a single durable knowledge item by ID."""
        items = self.get_durable_knowledge(limit=1000)
        for it in items:
            if it.knowledge_id == knowledge_id:
                return it
        return None

    def get_field_intelligence_engine(self) -> FieldIntelligenceEngine:
        """Returns a FieldIntelligenceEngine bound to this store's database connection."""
        return FieldIntelligenceEngine(conn_provider=self._get_connection)

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
            "agent_sessions": 0,
            "agent_turns": 0,
            "agent_tool_calls": 0,
            "agent_subagents": 0,
            "agent_artifacts": 0,
            "agent_corrections": 0,
            "agent_dwr_correlations": 0,
            "observations": 0,
            "detected_patterns": 0,
            "improvement_candidates": 0,
            "governance_records": 0,
            "durable_knowledge": 0,
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
                    ("agent_sessions", "agent_sessions"),
                    ("agent_turns", "agent_turns"),
                    ("agent_tool_calls", "agent_tool_calls"),
                    ("agent_subagents", "agent_subagents"),
                    ("agent_artifacts", "agent_artifacts"),
                    ("agent_corrections", "agent_corrections"),
                    ("agent_dwr_correlations", "agent_dwr_correlations"),
                    ("observations", "observations"),
                    ("detected_patterns", "detected_patterns"),
                    ("improvement_candidates", "improvement_candidates"),
                    ("governance_records", "governance_records"),
                    ("durable_knowledge", "durable_knowledge"),
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
