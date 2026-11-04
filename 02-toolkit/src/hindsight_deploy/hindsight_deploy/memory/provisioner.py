"""Memory Bank provisioning and seeding.

The manifest in 03-memory-bank/ is the source of truth for which banks exist
and what their initial content is. Provisioning is IDEMPOTENT:

    read manifest -> query server -> create missing -> validate existing
    -> seed only what was never seeded -> verify -> report

Seeding state is tracked in a state file so a repeated run never re-imports
the same template.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .api_client import HindsightAPIError, HindsightClient

REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFEST_ROOT = REPO_ROOT / "03-memory-bank"
STATE_PATH = Path.home() / ".hindsight" / "state" / "provisioning-state.json"

# Disposition values the external API accepts for a bank's temperament.
DEFAULT_DISPOSITION = {"skepticism": 3, "literalism": 3, "empathy": 3}


@dataclass
class BankSpec:
    """One bank's declaration in the manifest."""

    bank_id: str
    purpose: str = ""
    mission: str = ""
    template: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    manifest_dir: Optional[str] = None

    @property
    def template_path(self) -> Optional[Path]:
        if not self.template:
            return None
        return MANIFEST_ROOT / (self.manifest_dir or self.bank_id) / self.template


@dataclass
class ProvisionReport:
    """Outcome of one provisioning run."""

    created: List[str] = field(default_factory=list)
    existing: List[str] = field(default_factory=list)
    seeded: List[str] = field(default_factory=list)
    skipped_seeds: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)
    fact_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created": self.created,
            "existing": self.existing,
            "seeded": self.seeded,
            "skipped_seeds": self.skipped_seeds,
            "failed": self.failed,
            "fact_counts": self.fact_counts,
        }


# ──────────────────────────────────────────────────────────────────────
# Manifest
# ──────────────────────────────────────────────────────────────────────

def load_manifest(root: Optional[Path] = None) -> List[BankSpec]:
    """Read the bank manifest from 03-memory-bank/.

    Each bank owns a directory; a `manifest.json` inside it declares the
    bank id, purpose, mission and (optionally) the template file to seed.
    """
    root = root or MANIFEST_ROOT
    specs: List[BankSpec] = []
    if not root.exists():
        return specs
    for bank_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest_file = bank_dir / "manifest.json"
        if not manifest_file.exists():
            continue
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        specs.append(
            BankSpec(
                bank_id=data.get("bank_id") or bank_dir.name,
                purpose=data.get("purpose", ""),
                mission=data.get("mission", ""),
                template=data.get("template"),
                tags=list(data.get("tags", [])),
                manifest_dir=bank_dir.name,
            )
        )
    return specs


def template_hash(path: Path) -> str:
    """Content hash of a seed template, used to detect a changed template."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Seeding state
# ──────────────────────────────────────────────────────────────────────

def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the seeding state file (empty state when absent)."""
    path = path or STATE_PATH
    if not path.exists():
        return {"version": 1, "seeds": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "seeds": {}}


def save_state(state: Dict[str, Any], path: Optional[Path] = None) -> None:
    """Persist the seeding state file atomically."""
    path = path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _seed_already_applied(state: Dict[str, Any], bank_id: str, digest: str) -> bool:
    """True when this exact template content was already imported."""
    entry = state.get("seeds", {}).get(bank_id)
    return bool(entry and entry.get("template_sha256") == digest)


def _record_seed(state: Dict[str, Any], bank_id: str, digest: str, count: int) -> None:
    """Record that a template was imported."""
    state.setdefault("seeds", {})[bank_id] = {
        "template_sha256": digest,
        "seeded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seeded_facts": count,
    }


# ──────────────────────────────────────────────────────────────────────
# Provisioning
# ──────────────────────────────────────────────────────────────────────

def provision(
    client: HindsightClient,
    specs: Optional[List[BankSpec]] = None,
    state_path: Optional[Path] = None,
    do_seed: bool = True,
    verbose: bool = False,
) -> ProvisionReport:
    """Create missing banks, validate existing ones and seed templates.

    Idempotent: banks that already exist are left alone, and a template whose
    content hash matches the recorded seed is not imported a second time.
    """
    report = ProvisionReport()
    specs = specs if specs is not None else load_manifest()
    state = load_state(state_path)

    try:
        existing_ids = set(client.bank_ids())
    except HindsightAPIError as exc:
        report.failed["__api__"] = str(exc)
        return report

    for spec in specs:
        # 1. create what is missing
        if spec.bank_id not in existing_ids:
            try:
                client.create_bank(spec.bank_id, spec.mission, DEFAULT_DISPOSITION)
                report.created.append(spec.bank_id)
                if verbose:
                    print(f"  + created bank {spec.bank_id}")
            except HindsightAPIError as exc:
                report.failed[spec.bank_id] = f"create failed: {exc}"
                continue
        else:
            report.existing.append(spec.bank_id)
            if verbose:
                print(f"  = bank {spec.bank_id} already exists")

        # 2. keep the mission in sync with the manifest
        if spec.mission:
            try:
                current = client.get_bank(spec.bank_id) or {}
                if current.get("mission") != spec.mission:
                    client.update_bank(spec.bank_id, spec.mission)
                    if verbose:
                        print(f"  ~ updated mission for {spec.bank_id}")
            except HindsightAPIError:
                pass

        # 3. seed, but only what was never seeded
        template = spec.template_path
        if do_seed and template and template.exists():
            digest = template_hash(template)
            if _seed_already_applied(state, spec.bank_id, digest):
                report.skipped_seeds.append(spec.bank_id)
                if verbose:
                    print(f"  = seed for {spec.bank_id} already applied, skipped")
            else:
                try:
                    content = template.read_text(encoding="utf-8").strip()
                    if content:
                        client.retain(
                            spec.bank_id,
                            content,
                            context=spec.purpose or "seed",
                            tags=spec.tags,
                            async_=True,
                        )
                        _record_seed(state, spec.bank_id, digest, 1)
                        report.seeded.append(spec.bank_id)
                        if verbose:
                            print(f"  * seeded {spec.bank_id} from {template.name}")
                except (HindsightAPIError, OSError) as exc:
                    report.failed[spec.bank_id] = f"seed failed: {exc}"

        # 4. verify the server actually knows the bank
        try:
            report.fact_counts[spec.bank_id] = client.count_memories(spec.bank_id)
        except HindsightAPIError:
            report.fact_counts[spec.bank_id] = -1

    save_state(state, state_path)
    return report


def verify(client: HindsightClient, specs: Optional[List[BankSpec]] = None) -> Dict[str, Any]:
    """Check that every manifest bank exists on the server."""
    specs = specs if specs is not None else load_manifest()
    server_ids = set(client.bank_ids())
    result: Dict[str, Any] = {"healthy": client.is_healthy(), "banks": {}}
    for spec in specs:
        present = spec.bank_id in server_ids
        facts = client.count_memories(spec.bank_id) if present else 0
        result["banks"][spec.bank_id] = {"present": present, "fact_count": facts}
    result["missing"] = [
        s.bank_id for s in specs if not result["banks"][s.bank_id]["present"]
    ]
    return result


__all__ = [
    "BankSpec",
    "ProvisionReport",
    "load_manifest",
    "provision",
    "verify",
    "load_state",
    "save_state",
    "MANIFEST_ROOT",
    "STATE_PATH",
]
