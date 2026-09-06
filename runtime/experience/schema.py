"""
SQLite Schema Definitions, Tables, and Migration Engine for Experience Store.

Implements Milestone 2.1 Prompt 1 schema:
- Schema migrations tracking
- Installation metadata
- Projects
- Review sessions
- Review missions
- Action references
- Desktop Trace event references
- Forensic Evidence references (metadata & hashes only, never binary blobs)
- Experience outcomes & tripartite verdicts
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.experience.schema")

CURRENT_SCHEMA_VERSION = 4


class SchemaMigrationException(DesktopAutomationException):
    """Raised when schema migration or unsupported downgrade fails."""
    pass

MIGRATION_V1_STATEMENTS: List[str] = [
    # 1. Schema Migrations Log
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL,
        description TEXT NOT NULL
    );
    """,

    # 2. Installation Metadata
    """
    CREATE TABLE IF NOT EXISTS installation_metadata (
        installation_id TEXT PRIMARY KEY,
        runtime_version TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        metadata_json TEXT
    );
    """,

    # 3. Projects
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT,
        created_at TEXT NOT NULL,
        metadata_json TEXT
    );
    """,

    # 4. Review Sessions
    """
    CREATE TABLE IF NOT EXISTS review_sessions (
        session_id TEXT PRIMARY KEY,
        project_id TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        target_executable TEXT,
        target_pid INTEGER,
        target_hwnd TEXT,
        target_plane TEXT,
        runtime_version TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'SESSION',
        metadata_json TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_project ON review_sessions(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_created ON review_sessions(created_at);",

    # 5. Review Missions
    """
    CREATE TABLE IF NOT EXISTS missions (
        mission_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        project_id TEXT,
        goal TEXT NOT NULL,
        scope TEXT NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_missions_session ON missions(session_id);",

    # 6. Action References
    """
    CREATE TABLE IF NOT EXISTS action_references (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        action_type TEXT NOT NULL,
        plane TEXT NOT NULL,
        target TEXT,
        status TEXT NOT NULL,
        duration_ms REAL,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'FACT',
        confidence REAL NOT NULL DEFAULT 1.0,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        evidence_reference TEXT,
        trace_reference TEXT,
        metadata_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_action_ref_session ON action_references(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_action_ref_action ON action_references(action_id);",

    # 7. Trace References
    """
    CREATE TABLE IF NOT EXISTS trace_references (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        sequence_monotonic INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        plane TEXT NOT NULL,
        source TEXT NOT NULL,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_ref_session ON trace_references(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_trace_ref_event ON trace_references(event_id);",

    # 8. Forensic Evidence References (Only paths & SHA-256 hashes, NO binary blobs)
    """
    CREATE TABLE IF NOT EXISTS evidence_references (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evidence_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        action_id TEXT,
        artifact_id TEXT NOT NULL,
        artifact_type TEXT NOT NULL,
        checksum_sha256 TEXT NOT NULL,
        relative_path_or_uri TEXT NOT NULL,
        source TEXT NOT NULL,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_evidence_ref_session ON evidence_references(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_evidence_ref_evidence ON evidence_references(evidence_id);",

    # 9. Experience Outcomes & Verdicts
    """
    CREATE TABLE IF NOT EXISTS experience_outcomes (
        outcome_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        verdict TEXT NOT NULL,
        confidence REAL NOT NULL,
        error_category TEXT,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'FACT',
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        evidence_reference TEXT,
        trace_reference TEXT,
        details_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_outcomes_session ON experience_outcomes(session_id);",
]

MIGRATION_V2_STATEMENTS: List[str] = [
    # 10. Normalized Failures (Milestone 2.1 Prompt 2)
    """
    CREATE TABLE IF NOT EXISTS normalized_failures (
        failure_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        mission_id TEXT,
        action_id TEXT,
        category TEXT NOT NULL,
        original_classification TEXT NOT NULL,
        signature TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'FACT',
        recovery_reference TEXT,
        trace_reference TEXT,
        evidence_reference TEXT,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        safe_context_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_failures_session ON normalized_failures(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_failures_category ON normalized_failures(category);",
    "CREATE INDEX IF NOT EXISTS idx_failures_signature ON normalized_failures(signature);",
    "CREATE INDEX IF NOT EXISTS idx_failures_timestamp ON normalized_failures(timestamp);",

    # 11. Recovery Attempts (Milestone 2.1 Prompt 2)
    """
    CREATE TABLE IF NOT EXISTS recovery_attempts (
        recovery_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        action_id TEXT,
        failure_id TEXT,
        failure_category TEXT NOT NULL,
        recovery_action TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        max_attempts INTEGER NOT NULL,
        result TEXT NOT NULL,
        duration_ms REAL NOT NULL,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'FACT',
        error TEXT,
        evidence_refs_json TEXT,
        trace_event_id TEXT,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_recovery_session ON recovery_attempts(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_recovery_category ON recovery_attempts(failure_category);",
    "CREATE INDEX IF NOT EXISTS idx_recovery_result ON recovery_attempts(result);",
    "CREATE INDEX IF NOT EXISTS idx_recovery_timestamp ON recovery_attempts(timestamp);",
]

MIGRATION_V3_STATEMENTS: List[str] = [
    # 12. Agent Sessions (Milestone 2.1 Prompt 3)
    """
    CREATE TABLE IF NOT EXISTS agent_sessions (
        agent_session_id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        agent_id TEXT,
        workspace_id TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        metadata_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_sess_conv ON agent_sessions(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_sess_started ON agent_sessions(started_at);",

    # 13. Agent Turns
    """
    CREATE TABLE IF NOT EXISTS agent_turns (
        turn_id TEXT PRIMARY KEY,
        agent_session_id TEXT NOT NULL,
        conversation_id TEXT,
        parent_turn_id TEXT,
        step_index INTEGER,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        status TEXT NOT NULL,
        metadata_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_turns_sess ON agent_turns(agent_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_turns_conv ON agent_turns(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_turns_ts ON agent_turns(timestamp);",

    # 14. Agent Tool Calls
    """
    CREATE TABLE IF NOT EXISTS agent_tool_calls (
        tool_call_id TEXT PRIMARY KEY,
        turn_id TEXT,
        agent_session_id TEXT,
        conversation_id TEXT,
        tool_name TEXT NOT NULL,
        tool_category TEXT NOT NULL,
        success INTEGER NOT NULL,
        error_class TEXT,
        duration_ms REAL,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        safe_summary_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_tools_sess ON agent_tool_calls(agent_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_tools_conv ON agent_tool_calls(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_tools_name ON agent_tool_calls(tool_name);",
    "CREATE INDEX IF NOT EXISTS idx_agent_tools_cat ON agent_tool_calls(tool_category);",
    "CREATE INDEX IF NOT EXISTS idx_agent_tools_ts ON agent_tool_calls(timestamp);",

    # 15. Agent Subagents
    """
    CREATE TABLE IF NOT EXISTS agent_subagents (
        subagent_id TEXT PRIMARY KEY,
        parent_agent_id TEXT,
        delegation_id TEXT,
        conversation_id TEXT,
        agent_session_id TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        metadata_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_sub_parent ON agent_subagents(parent_agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_sub_conv ON agent_subagents(conversation_id);",

    # 16. Agent Artifacts
    """
    CREATE TABLE IF NOT EXISTS agent_artifacts (
        artifact_id TEXT PRIMARY KEY,
        artifact_type TEXT NOT NULL,
        safe_reference TEXT NOT NULL,
        agent_session_id TEXT,
        turn_id TEXT,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        metadata_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_art_sess ON agent_artifacts(agent_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_art_type ON agent_artifacts(artifact_type);",

    # 17. Agent Corrections
    """
    CREATE TABLE IF NOT EXISTS agent_corrections (
        correction_id TEXT PRIMARY KEY,
        correction_type TEXT NOT NULL,
        agent_session_id TEXT,
        conversation_id TEXT,
        turn_id TEXT,
        tool_call_id TEXT,
        related_dwr_session_id TEXT,
        related_action_id TEXT,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        classification_details_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_corr_type ON agent_corrections(correction_type);",
    "CREATE INDEX IF NOT EXISTS idx_agent_corr_dwr_sess ON agent_corrections(related_dwr_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_corr_ts ON agent_corrections(timestamp);",

    # 18. DWR <-> Antigravity Correlations
    """
    CREATE TABLE IF NOT EXISTS agent_dwr_correlations (
        correlation_id TEXT PRIMARY KEY,
        confidence TEXT NOT NULL,
        agent_session_id TEXT,
        conversation_id TEXT,
        turn_id TEXT,
        tool_call_id TEXT,
        dwr_session_id TEXT,
        dwr_mission_id TEXT,
        dwr_action_id TEXT,
        correlation_source TEXT NOT NULL,
        timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (dwr_session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_corr_dwr_sess ON agent_dwr_correlations(dwr_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_corr_dwr_act ON agent_dwr_correlations(dwr_action_id);",
    "CREATE INDEX IF NOT EXISTS idx_corr_conv ON agent_dwr_correlations(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_corr_conf ON agent_dwr_correlations(confidence);",
    "CREATE INDEX IF NOT EXISTS idx_corr_ts ON agent_dwr_correlations(timestamp);",
]

MIGRATION_V4_STATEMENTS: List[str] = [
    # 19. Observations (Milestone 2.1 Prompt 4)
    """
    CREATE TABLE IF NOT EXISTS observations (
        observation_id TEXT PRIMARY KEY,
        observation_type TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'SESSION',
        project_id TEXT,
        session_id TEXT,
        signature TEXT NOT NULL,
        occurrence_count INTEGER NOT NULL DEFAULT 1,
        confidence REAL NOT NULL DEFAULT 1.0,
        status TEXT NOT NULL DEFAULT 'OBSERVED',
        first_observed_at TEXT NOT NULL,
        last_observed_at TEXT NOT NULL,
        first_observed_ts REAL NOT NULL,
        last_observed_ts REAL NOT NULL,
        source_refs_json TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        details_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(observation_type);",
    "CREATE INDEX IF NOT EXISTS idx_obs_sig ON observations(signature);",
    "CREATE INDEX IF NOT EXISTS idx_obs_scope ON observations(scope);",
    "CREATE INDEX IF NOT EXISTS idx_obs_proj ON observations(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_obs_sess ON observations(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(last_observed_ts);",

    # 20. Detected Patterns
    """
    CREATE TABLE IF NOT EXISTS detected_patterns (
        pattern_id TEXT PRIMARY KEY,
        pattern_type TEXT NOT NULL,
        signature TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'PROJECT',
        project_id TEXT,
        occurrence_count INTEGER NOT NULL,
        session_count INTEGER NOT NULL,
        confidence REAL NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        first_seen_ts REAL NOT NULL,
        last_seen_ts REAL NOT NULL,
        observation_refs_json TEXT NOT NULL,
        summary TEXT NOT NULL,
        details_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pat_type ON detected_patterns(pattern_type);",
    "CREATE INDEX IF NOT EXISTS idx_pat_sig ON detected_patterns(signature);",
    "CREATE INDEX IF NOT EXISTS idx_pat_scope ON detected_patterns(scope);",
    "CREATE INDEX IF NOT EXISTS idx_pat_proj ON detected_patterns(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_pat_ts ON detected_patterns(last_seen_ts);",

    # 21. Improvement Candidates
    """
    CREATE TABLE IF NOT EXISTS improvement_candidates (
        candidate_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL DEFAULT 'PROJECT',
        project_id TEXT,
        category TEXT NOT NULL,
        affected_subsystem TEXT NOT NULL,
        pattern_id TEXT,
        evidence_count INTEGER NOT NULL,
        session_count INTEGER NOT NULL,
        confidence REAL NOT NULL,
        risk_level TEXT NOT NULL,
        status TEXT NOT NULL,
        rationale_summary TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        gate_results_json TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        metadata_json TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_cand_status ON improvement_candidates(status);",
    "CREATE INDEX IF NOT EXISTS idx_cand_cat ON improvement_candidates(category);",
    "CREATE INDEX IF NOT EXISTS idx_cand_subsys ON improvement_candidates(affected_subsystem);",
    "CREATE INDEX IF NOT EXISTS idx_cand_pat ON improvement_candidates(pattern_id);",
    "CREATE INDEX IF NOT EXISTS idx_cand_scope ON improvement_candidates(scope);",
    "CREATE INDEX IF NOT EXISTS idx_cand_proj ON improvement_candidates(project_id);",

    # 22. Governance Records
    """
    CREATE TABLE IF NOT EXISTS governance_records (
        governance_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        decision_scope TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        decision_timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        rationale TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (candidate_id) REFERENCES improvement_candidates(candidate_id) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_gov_cand ON governance_records(candidate_id);",
    "CREATE INDEX IF NOT EXISTS idx_gov_decision ON governance_records(decision);",
    "CREATE INDEX IF NOT EXISTS idx_gov_ts ON governance_records(decision_timestamp);",

    # 23. Durable Knowledge
    """
    CREATE TABLE IF NOT EXISTS durable_knowledge (
        knowledge_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL DEFAULT 1,
        scope TEXT NOT NULL DEFAULT 'PROJECT',
        project_id TEXT,
        candidate_id TEXT,
        normalized_statement TEXT NOT NULL,
        supporting_evidence_refs_json TEXT NOT NULL,
        validation_metadata_json TEXT NOT NULL,
        approval_metadata_json TEXT NOT NULL,
        confidence REAL NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        review_due_at TEXT,
        last_confirmed_at TEXT,
        last_used_at TEXT,
        superseded_by TEXT,
        contradiction_count INTEGER NOT NULL DEFAULT 0,
        provenance_json TEXT NOT NULL,
        FOREIGN KEY (candidate_id) REFERENCES improvement_candidates(candidate_id) ON DELETE SET NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_dur_status ON durable_knowledge(status);",
    "CREATE INDEX IF NOT EXISTS idx_dur_scope ON durable_knowledge(scope);",
    "CREATE INDEX IF NOT EXISTS idx_dur_proj ON durable_knowledge(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_dur_cand ON durable_knowledge(candidate_id);",
    "CREATE INDEX IF NOT EXISTS idx_dur_review ON durable_knowledge(review_due_at);",
]

MIGRATIONS: Dict[int, Tuple[str, List[str]]] = {
    1: ("Baseline Experience Store schema v1", MIGRATION_V1_STATEMENTS),
    2: ("Failure normalization and recovery attempt tracking schema v2", MIGRATION_V2_STATEMENTS),
    3: ("Antigravity agent experience and DWR correlation bridge schema v3", MIGRATION_V3_STATEMENTS),
    4: ("Learning, governance, and field intelligence schema v4", MIGRATION_V4_STATEMENTS),
}



def apply_migrations(conn: sqlite3.Connection) -> int:
    """
    Applies all pending forward migrations safely within transaction blocks.
    Updates PRAGMA user_version upon successful completion.
    Returns the number of applied migrations.
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version;")
    current_version = cursor.fetchone()[0]

    if current_version > CURRENT_SCHEMA_VERSION:
        raise SchemaMigrationException(
            f"Schema version v{current_version} is newer than current supported version v{CURRENT_SCHEMA_VERSION}; "
            "schema downgrade is safely unsupported."
        )

    applied_count = 0

    for version in sorted(MIGRATIONS.keys()):
        if version > current_version:
            desc, statements = MIGRATIONS[version]
            logger.info("Applying Experience Store migration v%d: %s", version, desc)

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

            for stmt in statements:
                stmt_clean = stmt.strip()
                if stmt_clean:
                    cursor.execute(stmt_clean)

            # Record migration in schema_migrations
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO schema_migrations (version, applied_at, description)
                VALUES (?, ?, ?);
                """,
                (version, now_iso, desc),
            )

            # Set user_version
            cursor.execute(f"PRAGMA user_version = {version};")
            conn.commit()
            applied_count += 1
            current_version = version

    return applied_count
