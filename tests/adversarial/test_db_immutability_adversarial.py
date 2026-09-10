import os
import sqlite3
import pytest
from datetime import datetime, timezone

from runtime.experience.schema import (
    apply_migrations,
    CURRENT_SCHEMA_VERSION,
)
from runtime.experience.store import ExperienceStore
from runtime.experience.config import ExperienceConfig
from runtime.experience.models import (
    ActionReferenceRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordSourceType,
    RecordKind,
    ExperienceScope,
    SessionExperienceRecord
)

def test_adversarial_v4_to_v5_history_immutability(tmp_path):
    """
    Adversarially tests that history is preserved and immutable across attempts,
    specifically focusing on attempts 1 (FAILED), 2 (UNVERIFIED), 3 (PASS).
    """
    db_path = tmp_path / "experience.db"
    config = ExperienceConfig(base_dir=tmp_path)
    store = ExperienceStore(config=config)
    
    # 1. Create a session
    sess = SessionExperienceRecord(
        session_id="sess_adv_1",
        project_id="proj_adv_1",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="ACTIVE",
        runtime_version="2.1.0",
        scope=ExperienceScope.SESSION,
        metadata={}
    )
    store.record_session(sess)
    
    # 2. Add multiple action attempts
    action_id = "act_adv_1"
    
    # Attempt 1: FAILED
    prov_1 = ProvenanceRecord(
        source="Test",
        source_type=RecordSourceType.RUNTIME,
        session_id="sess_adv_1",
        kind=RecordKind.FACT,
        timestamp=100.0,
        iso_timestamp="2026-09-10T10:00:00Z"
    )
    store.record_action_reference(ActionReferenceRecord(
        action_id=action_id,
        session_id="sess_adv_1",
        action_type="CLICK",
        plane="UIA",
        target="btn_1",
        status="FAILED",
        duration_ms=10,
        provenance=prov_1
    ))
    store.record_outcome(OutcomeRecord(
        outcome_id="out_1",
        session_id="sess_adv_1",
        verdict="FAILED",
        confidence=1.0,
        error_category="TARGET_NOT_FOUND",
        provenance=prov_1
    ))
    
    # Attempt 2: UNVERIFIED
    prov_2 = ProvenanceRecord(
        source="Test",
        source_type=RecordSourceType.RUNTIME,
        session_id="sess_adv_1",
        kind=RecordKind.FACT,
        timestamp=200.0,
        iso_timestamp="2026-09-10T10:01:00Z"
    )
    store.record_action_reference(ActionReferenceRecord(
        action_id=action_id, # same action_id
        session_id="sess_adv_1",
        action_type="CLICK",
        plane="UIA",
        target="btn_1",
        status="UNVERIFIED",
        duration_ms=20,
        provenance=prov_2
    ))
    store.record_outcome(OutcomeRecord(
        outcome_id="out_2",
        session_id="sess_adv_1",
        verdict="UNVERIFIED",
        confidence=0.5,
        error_category="STALE_REFERENCE",
        provenance=prov_2
    ))
    
    # Attempt 3: PASS
    prov_3 = ProvenanceRecord(
        source="Test",
        source_type=RecordSourceType.RUNTIME,
        session_id="sess_adv_1",
        kind=RecordKind.FACT,
        timestamp=300.0,
        iso_timestamp="2026-09-10T10:02:00Z"
    )
    store.record_action_reference(ActionReferenceRecord(
        action_id=action_id, # same action_id
        session_id="sess_adv_1",
        action_type="CLICK",
        plane="UIA",
        target="btn_1",
        status="SETTLED",
        duration_ms=30,
        provenance=prov_3
    ))
    store.record_outcome(OutcomeRecord(
        outcome_id="out_3",
        session_id="sess_adv_1",
        verdict="PASS",
        confidence=1.0,
        error_category=None,
        provenance=prov_3
    ))
    
    # 3. Query and Verify
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Verify action_references
    cursor.execute("SELECT status FROM action_references WHERE action_id = ? ORDER BY timestamp ASC", (action_id,))
    action_statuses = [row["status"] for row in cursor.fetchall()]
    assert action_statuses == ["FAILED", "UNVERIFIED", "SETTLED"], "Historical actions were mutated or not preserved!"
    
    # Verify experience_outcomes
    cursor.execute("SELECT verdict FROM experience_outcomes WHERE session_id = ? ORDER BY timestamp ASC", ("sess_adv_1",))
    verdicts = [row["verdict"] for row in cursor.fetchall()]
    assert verdicts == ["FAILED", "UNVERIFIED", "PASS"], "Historical verdicts were mutated or not preserved!"

def test_adversarial_db_schema_no_destructive_updates():
    """
    Search for destructive UPDATEs or ON CONFLICT DO UPDATEs in schema and store.
    """
    with open("runtime/experience/store.py", "r", encoding="utf-8") as f:
        store_code = f.read()
    
    destructive_patterns = [
        "UPDATE action_references",
        "UPDATE experience_outcomes",
        "UPDATE normalized_failures",
        "ON CONFLICT(id) DO UPDATE",
    ]
    
    for pattern in destructive_patterns:
        assert pattern not in store_code, f"Destructive pattern found: {pattern}"

