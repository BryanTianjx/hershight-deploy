"""CLI for manifest validation, Bank provisioning, drift checks and reports."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional
import typer
from .app import settings
from .memory.api_client import HindsightClient
from .memory.lifecycle import ManifestError, drift, load_manifests, load_state, provision, save_state, seed_refresh

app=typer.Typer(help="Hindsight External Memory Bank lifecycle")

@app.callback()
def configure(api_url:str=typer.Option("http://127.0.0.1:8888","--api-url",envvar="HINDSIGHT_API_URL"),
              timeout:int=typer.Option(120,"--timeout")):
    """Select the Hindsight External API endpoint."""
    settings.api_url=api_url
    settings.timeout=timeout

def client()->HindsightClient:
    return HindsightClient(base_url=settings.api_url,timeout=float(settings.timeout or 120))

def emit(data:dict,path:Optional[Path]=None)->None:
    rendered=json.dumps(data,ensure_ascii=False,indent=2)
    if path:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(rendered+"\n",encoding="utf-8")
    typer.echo(rendered)

@app.command("validate")
def validate(manifest_dir:Path=typer.Option(Path("03-memory-bank"),"--manifest-dir")):
    banks=load_manifests(manifest_dir)
    typer.echo(f"Schema validation passed: {len(banks)} bank(s)")
    for b in banks: typer.echo(f"  ✓ {b.bank_id} (v{b.version})")

@app.command("provision")
def provision_cmd(seed:bool=typer.Option(True,"--seed/--no-seed"),
                  manifest_dir:Path=typer.Option(Path("03-memory-bank"),"--manifest-dir"),
                  state_file:Path=typer.Option(Path.home()/".hindsight/state/provisioning-state.json","--state-file"),
                  report_file:Optional[Path]=typer.Option(None,"--report-file")):
    banks=load_manifests(manifest_dir)
    if not banks: raise typer.BadParameter("No manifest files found")
    report=provision(client(),banks,state_file,seed)
    data=report.to_dict(); emit(data,report_file)
    if data["summary"]["failed"]: raise typer.Exit(1)

@app.command("drift")
def drift_cmd(manifest_dir:Path=typer.Option(Path("03-memory-bank"),"--manifest-dir"),
              report_file:Optional[Path]=typer.Option(None,"--report-file")):
    banks=load_manifests(manifest_dir); api=client(); rows=drift(api,banks)
    data={"api_healthy":api.is_healthy(),"drifted":[x["bank_id"] for x in rows if x["drift"]],"banks":rows}
    emit(data,report_file)
    if data["drifted"]: raise typer.Exit(2)

@app.command("seed-status")
def seed_status(state_file:Path=typer.Option(Path.home()/".hindsight/state/provisioning-state.json","--state-file"),
                refresh:bool=typer.Option(True,"--refresh/--no-refresh")):
    state=load_state(state_file)
    if refresh: seed_refresh(client(),state); save_state(state,state_file)
    emit(state)

@app.command("report")
def report_cmd(manifest_dir:Path=typer.Option(Path("03-memory-bank"),"--manifest-dir"),
               state_file:Path=typer.Option(Path.home()/".hindsight/state/provisioning-state.json","--state-file"),
               output:Optional[Path]=typer.Option(None,"--output")):
    banks=load_manifests(manifest_dir); api=client(); rows=drift(api,banks); state=load_state(state_file)
    by_id={x["bank_id"]:x for x in rows}; results=[]
    for b in banks:
        remote=by_id[b.bank_id]; revisions=state.get("seeds",{}).get(b.bank_id,{})
        mission_drift=any(x["field"]=="mission" for x in remote["drift"])
        results.append({"bank_id":b.bank_id,"manifest_version":b.version,
          "creation":"existing" if remote["present"] else "missing",
          "initialization":"completed" if remote["present"] and not mission_drift else "pending",
          "seed_revisions":revisions,"verification":"passed" if remote["present"] else "failed",
          "drift":remote["drift"],"unmanaged_manifest_fields":remote["unmanaged_manifest_fields"]})
    data={"report_version":"1.0","api_healthy":api.is_healthy(),
      "summary":{"banks":len(results),"present":sum(x["creation"]=="existing" for x in results),
      "missing":sum(x["creation"]=="missing" for x in results),"drifted":sum(bool(x["drift"]) for x in results)},
      "banks":results}
    emit(data,output)

if __name__=="__main__": app()
