"""Manifest schema validation and Hindsight External Bank lifecycle."""
from __future__ import annotations
import hashlib, json, os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from jsonschema import Draft202012Validator
from .api_client import HindsightAPIError, HindsightClient

ROOT = Path(__file__).resolve().parents[5]
MANIFEST_ROOT = ROOT / "03-memory-bank"
SCHEMA = MANIFEST_ROOT / "manifest.schema.json"
STATE = Path.home() / ".hindsight/state/provisioning-state.json"

class ManifestError(ValueError): pass

def now() -> str: return datetime.now(timezone.utc).isoformat()
def digest(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

@dataclass
class Bank:
    bank_id: str
    name: str
    purpose: str
    mission: str
    version: int
    manifest_hash: str
    folder: Path
    template: Optional[str]
    seed_enabled: bool
    seed_mode: str
    tags: list[str] = field(default_factory=list)
    ownership: dict[str, str] = field(default_factory=dict)
    @property
    def seed_path(self) -> Optional[Path]:
        if not self.template: return None
        base=self.folder.resolve(); path=(base/self.template).resolve()
        if path.parent != base or not path.is_file():
            raise ManifestError(f"{self.bank_id}: invalid or missing seed source {self.template}")
        return path

def validate(data: Any, schema_path: Path = SCHEMA) -> None:
    if not schema_path.is_file(): raise ManifestError(f"Schema not found: {schema_path}")
    schema=json.loads(schema_path.read_text(encoding="utf-8"))
    errors=sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e:list(map(str,e.path)))
    if errors: raise ManifestError("; ".join(f"{'.'.join(map(str,e.path)) or '<root>'}: {e.message}" for e in errors))

def load_manifests(root: Path = MANIFEST_ROOT) -> list[Bank]:
    root=root.resolve()
    if not root.is_dir(): raise ManifestError(f"Manifest directory not found: {root}")
    schema=root/"manifest.schema.json"
    if not schema.is_file(): schema=SCHEMA
    result=[]; ids=set()
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        file=folder/"manifest.json"
        if not file.is_file(): continue
        try: raw=file.read_bytes(); data=json.loads(raw)
        except (OSError,json.JSONDecodeError) as exc: raise ManifestError(f"{file}: {exc}") from exc
        validate(data,schema)
        bid=data["bank_id"]
        if bid in ids: raise ManifestError(f"Duplicate bank_id: {bid}")
        ids.add(bid); seed=data["provisioning"]["seed"]
        if seed["source"] != data["template"]: raise ManifestError(f"{file}: seed.source must equal template")
        item=Bank(bid,data["name"],data["purpose"],data["mission"],data["version"],digest(raw),folder,
                  data["template"] if seed["enabled"] and seed["mode"]!="disabled" else None,
                  seed["enabled"],seed["mode"],data["tags"],data["ownership"])
        _=item.seed_path
        result.append(item)
    return result

def load_state(path: Path = STATE) -> dict:
    if not path.exists(): return {"version":1,"seeds":{}}
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise ManifestError(f"Invalid state file: {exc}") from exc
    if not isinstance(data,dict) or not isinstance(data.get("seeds",{}),dict): raise ManifestError("Invalid state structure")
    return data

def save_state(data: dict, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,path)
    try: os.chmod(path,0o600)
    except OSError: pass

@dataclass
class BankResult:
    bank_id: str
    creation: str="pending"
    initialization: str="pending"
    seed: str="not_requested"
    verification: str="pending"
    fact_count: Optional[int]=None
    drift: list[dict]=field(default_factory=list)
    error: Optional[str]=None
    def to_dict(self): return self.__dict__

@dataclass
class DeploymentReport:
    banks: list[BankResult]=field(default_factory=list)
    api_healthy: Optional[bool]=None
    generated_at: str=field(default_factory=now)
    def to_dict(self):
        rows=[b.to_dict() for b in self.banks]
        return {"report_version":"1.0","generated_at":self.generated_at,"api_healthy":self.api_healthy,
                "summary":{"total":len(rows),"created":sum(x["creation"]=="created" for x in rows),
                "existing":sum(x["creation"]=="existing" for x in rows),
                "initialized":sum(x["initialization"] in {"completed","matched","updated"} for x in rows),
                "verified":sum(x["verification"]=="passed" for x in rows),
                "failed":sum(bool(x["error"]) or x["verification"]=="failed" for x in rows),
                "drifted":sum(bool(x["drift"]) for x in rows)},"banks":rows}

def seed_refresh(client: HindsightClient, state: dict) -> None:
    for bid,revisions in state.get("seeds",{}).items():
        for sha,entry in revisions.items():
            if entry.get("status")!="submitted" or not entry.get("operation_id"): continue
            try: op=client.operation(bid,entry["operation_id"])
            except HindsightAPIError as exc: entry["last_poll_error"]=str(exc); continue
            status=str(op.get("status","")).lower()
            if status in {"completed","complete","succeeded","success"}: entry["status"]="completed"; entry["completed_at"]=now()
            elif status in {"failed","error","cancelled"}: entry["status"]="failed"; entry["error"]=op
            entry["last_operation_status"]=status; entry["updated_at"]=now()

def drift(client: HindsightClient, banks: list[Bank]) -> list[dict]:
    server=set(client.bank_ids()); out=[]
    for b in banks:
        row={"bank_id":b.bank_id,"present":b.bank_id in server,"drift":[],
             "unmanaged_manifest_fields":["ownership","tags","scope","exclusions","recording_policy"]}
        if not row["present"]: row["drift"].append({"field":"bank","desired":"present","actual":"missing"})
        else:
            actual=client.get_bank(b.bank_id).get("mission")
            if actual!=b.mission: row["drift"].append({"field":"mission","desired":b.mission,"actual":actual})
        out.append(row)
    return out

def provision(client: HindsightClient, banks: list[Bank], state_path: Path = STATE, do_seed: bool = True) -> DeploymentReport:
    state=load_state(state_path); seed_refresh(client,state); report=DeploymentReport(api_healthy=client.is_healthy())
    for b in banks:
        r=BankResult(b.bank_id); report.banks.append(r)
        try:
            try: current=client.get_bank(b.bank_id); r.creation="existing"
            except HindsightAPIError as exc:
                if exc.status_code!=404: raise
                current=client.create_bank(b.bank_id,b.mission,{"skepticism":3,"literalism":3,"empathy":3}); r.creation="created"
            if current.get("mission")!=b.mission: client.update_bank(b.bank_id,b.mission); r.initialization="updated"
            else: r.initialization="matched"
            if do_seed and b.seed_path:
                content=b.seed_path.read_text(encoding="utf-8").strip()
                if content:
                    sha=digest(content.encode()); old=state.get("seeds",{}).get(b.bank_id,{}).get(sha,{})
                    status=old.get("status")
                    if status=="completed": r.seed="skipped"
                    elif status=="submitted": r.seed="pending_confirmation"
                    elif status in {"submitting","unknown"}: r.seed="manual_review_required"
                    else:
                        state.setdefault("seeds",{}).setdefault(b.bank_id,{})[sha]={"status":"submitting","updated_at":now(),"manifest_version":b.version}
                        save_state(state,state_path)
                        try: response=client.retain(b.bank_id,content,context=b.purpose,tags=b.tags,async_=True)
                        except HindsightAPIError:
                            state["seeds"][b.bank_id][sha]["status"]="unknown"; save_state(state,state_path); raise
                        state["seeds"][b.bank_id][sha].update({"status":"submitted","operation_id":response.get("operation_id") if isinstance(response,dict) else None,"accepted_response":response,"updated_at":now()})
                        save_state(state,state_path); r.seed="submitted"
            r.fact_count=client.count_memories(b.bank_id); r.verification="passed"
            revisions=state.get("seeds",{}).get(b.bank_id,{})
        except (HindsightAPIError,OSError,ManifestError) as exc:
            r.error=str(exc); r.verification="failed"
        if r.seed=="not_requested" and do_seed and b.seed_path is None: r.seed="disabled"
    save_state(state,state_path)
    return report
