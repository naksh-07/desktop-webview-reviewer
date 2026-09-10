import asyncio
import pytest
import shutil
from runtime.evidence_store import EvidenceStore, EvidenceSecurityException

@pytest.fixture
def temp_evidence_dir(tmp_path):
    store_dir = tmp_path / "evidence_store"
    yield store_dir
    if store_dir.exists():
        shutil.rmtree(store_dir)

def test_attempt_lineage_isolation(temp_evidence_dir):
    async def run():
        store = EvidenceStore(base_dir=temp_evidence_dir)
        session_id = "sess_1"
        action_id = "act_1"
        
        att1 = "attempt_1"
        store.store_bytes(session_id, action_id, "data.bin", b"data1", attempt_id=att1)
        
        att2 = "attempt_2"
        store.store_bytes(session_id, action_id, "data.bin", b"data2", attempt_id=att2)
        
        att3 = "attempt_3"
        store.store_bytes(session_id, action_id, "data.bin", b"data3", attempt_id=att3)
        
        b1 = store.load_artifact_bytes(session_id, action_id, "data.bin", attempt_id=att1)
        b2 = store.load_artifact_bytes(session_id, action_id, "data.bin", attempt_id=att2)
        b3 = store.load_artifact_bytes(session_id, action_id, "data.bin", attempt_id=att3)
        
        assert b1 == b"data1"
        assert b2 == b"data2"
        assert b3 == b"data3"
    asyncio.run(run())

def test_same_action_same_attempt_collision(temp_evidence_dir):
    async def run():
        store = EvidenceStore(base_dir=temp_evidence_dir)
        session_id = "sess_2"
        action_id = "act_2"
        att = "attempt_1"
        
        store.store_bytes(session_id, action_id, "data.bin", b"data", attempt_id=att)
        
        with pytest.raises(EvidenceSecurityException, match="Cannot overwrite existing artifact"):
            store.store_bytes(session_id, action_id, "data.bin", b"newdata", attempt_id=att)
            
        b = store.load_artifact_bytes(session_id, action_id, "data.bin", attempt_id=att)
        assert b == b"data"
    asyncio.run(run())

def test_concurrency_evidence_operations(temp_evidence_dir):
    async def run():
        store = EvidenceStore(base_dir=temp_evidence_dir)
        
        async def write_evidence(s_id, a_id, att_id, data_val):
            try:
                await asyncio.sleep(0)
                store.store_bytes(s_id, a_id, f"data_{data_val}.bin", data_val.encode('utf-8'), attempt_id=att_id)
                return True, None
            except Exception as e:
                return False, e

        tasks1 = [write_evidence(f"sess_{i}", f"act_{i}", f"att_{i}", f"val_{i}") for i in range(10)]
        tasks2 = [write_evidence("sess_s1", "act_s1", f"att_{i}", f"val_{i}") for i in range(10)]
        tasks3 = [write_evidence("sess_s2", "act_s2", "att_s2", f"val_{i}") for i in range(10)]
        
        results = await asyncio.gather(*(tasks1 + tasks2 + tasks3), return_exceptions=True)
        
        for res in results:
            assert res[0] is True, f"Failed with {res[1]}"
            
        async def write_same_artifact(s_id, a_id, att_id, file_name, data_val):
            try:
                await asyncio.sleep(0)
                store.store_bytes(s_id, a_id, file_name, data_val.encode('utf-8'), attempt_id=att_id)
                return True, None
            except EvidenceSecurityException as e:
                return False, e

        tasks4 = [write_same_artifact("sess_col", "act_col", "att_col", "shared.bin", f"val_{i}") for i in range(10)]
        results4 = await asyncio.gather(*tasks4, return_exceptions=True)
        
        success_count = sum(1 for r in results4 if r[0] is True)
        assert success_count == 1, "Expected exactly one success, no silent overwrites"
    asyncio.run(run())

