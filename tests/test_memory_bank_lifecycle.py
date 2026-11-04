import json
from pathlib import Path
import pytest
from hindsight_deploy.memory.lifecycle import ManifestError, drift, load_manifests, load_state, provision

ROOT=Path(__file__).resolve().parents[1]
MANIFESTS=ROOT/"03-memory-bank"

class FakeClient:
    def __init__(self): self.banks={}; self.memories={}; self.retain_calls=0
    def is_healthy(self): return True
    def bank_ids(self): return list(self.banks)
    def get_bank(self,bid):
        if bid not in self.banks:
            from hindsight_deploy.memory.api_client import HindsightAPIError
            raise HindsightAPIError("missing",404)
        return dict(self.banks[bid])
    def create_bank(self,bid,mission="",disposition=None):
        self.banks[bid]={"bank_id":bid,"mission":mission}; return dict(self.banks[bid])
    def update_bank(self,bid,mission=""): self.banks[bid]["mission"]=mission
    def retain(self,bid,content,context="general",tags=None,async_=False):
        self.retain_calls+=1; self.memories.setdefault(bid,[]).append(content); return {"operation_id":"op-1"}
    def operation(self,bid,op): return {"status":"completed"}
    def count_memories(self,bid): return len(self.memories.get(bid,[]))

def test_manifest_schema_and_seed_path():
    banks=load_manifests(MANIFESTS)
    assert [b.bank_id for b in banks]==["example-project"]
    assert banks[0].seed_path.name=="seed.md"

def test_schema_rejects_unsafe_bank_id(tmp_path):
    folder=tmp_path/"bad"; folder.mkdir()
    data=json.loads((MANIFESTS/"default/manifest.json").read_text())
    data["bank_id"]="../unsafe"
    (folder/"manifest.json").write_text(json.dumps(data))
    (folder/"seed.md").write_text("seed")
    (tmp_path/"manifest.schema.json").write_text((MANIFESTS/"manifest.schema.json").read_text())
    with pytest.raises(ManifestError): load_manifests(tmp_path)

def test_provision_is_idempotent_per_seed_revision(tmp_path):
    api=FakeClient(); state=tmp_path/"state.json"; banks=load_manifests(MANIFESTS)
    first=provision(api,banks,state)
    second=provision(api,banks,state)
    assert first.banks[0].creation=="created"
    assert second.banks[0].creation=="existing"
    assert second.banks[0].seed=="skipped"
    assert api.retain_calls==1
    assert load_state(state)["version"]==1

def test_drift_reports_missing_and_mission_difference():
    api=FakeClient(); banks=load_manifests(MANIFESTS)
    assert drift(api,banks)[0]["drift"][0]["field"]=="bank"
    api.create_bank(banks[0].bank_id,"wrong")
    assert drift(api,banks)[0]["drift"][0]["field"]=="mission"
