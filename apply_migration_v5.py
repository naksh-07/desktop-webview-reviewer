import sys
import os

SCHEMA_V5_ADDITIONS = """
MIGRATION_V5_STATEMENTS: List[str] = [
    # 1. process_incarnations
    \"\"\"
    CREATE TABLE IF NOT EXISTS process_incarnations (
        incarnation_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        pid INTEGER NOT NULL,
        process_creation_time REAL NOT NULL,
        binary_path TEXT NOT NULL,
        command_line_json TEXT,
        is_elevated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    \"\"\",
    
    # 2. targets
    \"\"\"
    CREATE TABLE IF NOT EXISTS targets (
        target_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        incarnation_id TEXT,
        target_type TEXT NOT NULL,
        title TEXT,
        url TEXT,
        engine TEXT,
        native_hwnd TEXT,
        cdp_target_id TEXT,
        bounds_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (incarnation_id) REFERENCES process_incarnations(incarnation_id) ON DELETE SET NULL
    );
    \"\"\",

    # 3. action_attempts
    \"\"\"
    CREATE TABLE IF NOT EXISTS action_attempts (
        attempt_id TEXT PRIMARY KEY,
        action_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        target_id TEXT,
        attempt_number INTEGER NOT NULL,
        dispatch_method TEXT NOT NULL,
        dispatch_status TEXT NOT NULL,
        preconditions_passed INTEGER NOT NULL DEFAULT 0,
        duration_ms REAL,
        error_message TEXT,
        receipt_json TEXT,
        created_at TEXT NOT NULL,
        iso_timestamp TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (target_id) REFERENCES targets(target_id) ON DELETE SET NULL
    );
    \"\"\",

    # 4. capture_artifacts
    \"\"\"
    CREATE TABLE IF NOT EXISTS capture_artifacts (
        artifact_id TEXT PRIMARY KEY,
        evidence_id TEXT,
        session_id TEXT NOT NULL,
        attempt_id TEXT,
        capture_backend TEXT NOT NULL,
        coordinate_space TEXT NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        pixel_format TEXT NOT NULL DEFAULT 'RGBA',
        dpi_scaling REAL NOT NULL DEFAULT 1.0,
        capture_duration_ms REAL,
        checksum_sha256 TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        is_authoritative INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (attempt_id) REFERENCES action_attempts(attempt_id) ON DELETE SET NULL
    );
    \"\"\",

    # 5. verification_claims
    \"\"\"
    CREATE TABLE IF NOT EXISTS verification_claims (
        claim_id TEXT PRIMARY KEY,
        outcome_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        attempt_id TEXT,
        claim_type TEXT NOT NULL,
        status TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        unverified_reason TEXT,
        expected_json TEXT,
        actual_json TEXT,
        evaluation_details TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (outcome_id) REFERENCES experience_outcomes(outcome_id) ON DELETE CASCADE,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (attempt_id) REFERENCES action_attempts(attempt_id) ON DELETE SET NULL
    );
    \"\"\",

    # 6. verification_evidence
    \"\"\"
    CREATE TABLE IF NOT EXISTS verification_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        outcome_id TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        claim_id TEXT,
        role TEXT NOT NULL DEFAULT 'PRIMARY_PROOF',
        linked_at TEXT NOT NULL,
        FOREIGN KEY (outcome_id) REFERENCES experience_outcomes(outcome_id) ON DELETE CASCADE,
        FOREIGN KEY (claim_id) REFERENCES verification_claims(claim_id) ON DELETE CASCADE
    );
    \"\"\",

    # 7. evidence_lifecycle_transitions
    \"\"\"
    CREATE TABLE IF NOT EXISTS evidence_lifecycle_transitions (
        transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
        evidence_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        from_stage TEXT NOT NULL,
        to_stage TEXT NOT NULL,
        transitioned_by TEXT NOT NULL,
        reason TEXT,
        transition_timestamp REAL NOT NULL,
        iso_timestamp TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES review_sessions(session_id) ON DELETE CASCADE
    );
    \"\"\",

    # Add columns to existing tables
    \"ALTER TABLE review_sessions ADD COLUMN target_creation_time REAL;\",
    \"ALTER TABLE review_sessions ADD COLUMN process_incarnation_id TEXT;\",

    \"ALTER TABLE action_references ADD COLUMN attempt_id TEXT NOT NULL DEFAULT 'att_0';\",
    \"ALTER TABLE action_references ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1;\",
    \"ALTER TABLE action_references ADD COLUMN lifecycle_stage TEXT NOT NULL DEFAULT 'DISPATCHED';\",
    \"ALTER TABLE action_references ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'INTERACTIVE';\",

    \"ALTER TABLE evidence_references ADD COLUMN attempt_id TEXT;\",
    \"ALTER TABLE evidence_references ADD COLUMN evidence_type TEXT NOT NULL DEFAULT 'NATIVE_SCREENSHOT';\",
    \"ALTER TABLE evidence_references ADD COLUMN proof_level TEXT NOT NULL DEFAULT 'LEVEL_3_DUAL_PERSPECTIVE_PROOF';\",
    \"ALTER TABLE evidence_references ADD COLUMN is_authoritative INTEGER NOT NULL DEFAULT 0;\",
    \"ALTER TABLE evidence_references ADD COLUMN lifecycle_stage TEXT NOT NULL DEFAULT 'VALIDATED';\",
    \"ALTER TABLE evidence_references ADD COLUMN process_creation_time REAL NOT NULL DEFAULT 0.0;\",
    \"ALTER TABLE evidence_references ADD COLUMN target_hwnd TEXT;\",

    \"ALTER TABLE experience_outcomes ADD COLUMN action_id TEXT;\",
    \"ALTER TABLE experience_outcomes ADD COLUMN attempt_id TEXT;\",
    \"ALTER TABLE experience_outcomes ADD COLUMN proof_level TEXT NOT NULL DEFAULT 'LEVEL_3_DUAL_PERSPECTIVE_PROOF';\",
    \"ALTER TABLE experience_outcomes ADD COLUMN unverified_reason TEXT;\",

    # Add constraints via indexes
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_process_incarnation ON process_incarnations(pid, process_creation_time, session_id);\",
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_action_attempt ON action_attempts(action_id, attempt_id);\",
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_action_attempt_number ON action_attempts(action_id, attempt_number);\",
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_artifact ON evidence_references(session_id, action_id, attempt_id, artifact_id);\",
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_capture_path ON capture_artifacts(session_id, relative_path);\",
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_attempt ON verification_claims(outcome_id, attempt_id, claim_type);\",
    \"CREATE UNIQUE INDEX IF NOT EXISTS uq_verif_evidence_link ON verification_evidence(outcome_id, evidence_id, claim_id);\",

    # Performance indexes
    \"CREATE INDEX IF NOT EXISTS idx_proc_inc_pid_time ON process_incarnations(pid, process_creation_time);\",
    \"CREATE INDEX IF NOT EXISTS idx_proc_inc_session ON process_incarnations(session_id);\",

    \"CREATE INDEX IF NOT EXISTS idx_targets_session ON targets(session_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_targets_hwnd ON targets(native_hwnd);\",

    \"CREATE INDEX IF NOT EXISTS idx_attempts_action ON action_attempts(action_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_attempts_session ON action_attempts(session_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_attempts_status ON action_attempts(dispatch_status);\",

    \"CREATE INDEX IF NOT EXISTS idx_ev_ref_attempt ON evidence_references(attempt_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_ev_ref_sha256 ON evidence_references(checksum_sha256);\",
    \"CREATE INDEX IF NOT EXISTS idx_ev_ref_auth ON evidence_references(is_authoritative, lifecycle_stage);\",

    \"CREATE INDEX IF NOT EXISTS idx_artifacts_session ON capture_artifacts(session_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON capture_artifacts(checksum_sha256);\",
    \"CREATE INDEX IF NOT EXISTS idx_artifacts_backend ON capture_artifacts(capture_backend);\",

    \"CREATE INDEX IF NOT EXISTS idx_claims_outcome ON verification_claims(outcome_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_claims_attempt ON verification_claims(attempt_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_claims_type_status ON verification_claims(claim_type, status);\",

    \"CREATE INDEX IF NOT EXISTS idx_verif_ev_outcome ON verification_evidence(outcome_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_verif_ev_evidence ON verification_evidence(evidence_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_verif_ev_claim ON verification_evidence(claim_id);\",

    \"CREATE INDEX IF NOT EXISTS idx_ev_lifecycle_ev_id ON evidence_lifecycle_transitions(evidence_id);\",
    \"CREATE INDEX IF NOT EXISTS idx_ev_lifecycle_stage ON evidence_lifecycle_transitions(to_stage);\"
]
"""

target_file = r'c:\Users\Suraj\Documents\Antigravity\Desktop-priview\runtime\experience\schema.py'

with open(target_file, 'r') as f:
    content = f.read()

content = content.replace("CURRENT_SCHEMA_VERSION = 4", "CURRENT_SCHEMA_VERSION = 5")

insert_idx = content.find("MIGRATIONS: Dict[int, Tuple[str, List[str]]] = {")
content = content[:insert_idx] + SCHEMA_V5_ADDITIONS + "\n" + content[insert_idx:]

content = content.replace(
    "4: (\"Learning, governance, and field intelligence schema v4\", MIGRATION_V4_STATEMENTS),",
    "4: (\"Learning, governance, and field intelligence schema v4\", MIGRATION_V4_STATEMENTS),\n    5: (\"Forensic persistence and evidence lifecycle schema v5\", MIGRATION_V5_STATEMENTS),"
)

with open(target_file, 'w') as f:
    f.write(content)

print("Schema V5 applied successfully")
