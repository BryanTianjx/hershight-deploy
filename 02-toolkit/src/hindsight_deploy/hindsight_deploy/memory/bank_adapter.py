"""Memory Bank adapter for Hindsight Deploy.

Provides unified interface for Bank operations (init, validate, permissions).
Does not depend on infrastructure module - uses direct subprocess calls
where needed, or placeholder logic for V1.0.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Bank configuration
# ──────────────────────────────────────────────────────────────────────

BANKS_CONFIG_PATH = Path(typer.get_app_dir("hindsight-deploy")) / "banks.yaml"

DEFAULT_BANKS_CONFIG: Dict[str, Any] = {
    "banks": [
        {"id": "personal-core", "purpose": "personal_long_term_context"},
        {"id": "personal-learning", "purpose": "learning_progress"},
        {"id": "personal-workspace", "purpose": "environment_and_troubleshooting"},
        {"id": "wifi-codec", "purpose": "wifi_protocol_codec"},
        {"id": "3gpp-codec", "purpose": "3gpp_protocol_codec"},
        {"id": "protocol-knowledge", "purpose": "protocol_knowledge_engineering"},
    ]
}


# ──────────────────────────────────────────────────────────────────────
# Bank configuration management
# ──────────────────────────────────────────────────────────────────────

def load_banks_config() -> Dict[str, Any]:
    """Load the banks configuration file, creating a default if missing."""
    if not BANKS_CONFIG_PATH.exists():
        typer.echo("📝 Creating default banks configuration...")
        BANKS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        save_banks_config(DEFAULT_BANKS_CONFIG)
    with open(BANKS_CONFIG_PATH, "r") as f:
        return json.load(f)


def save_banks_config(config: Dict[str, Any]) -> None:
    """Persist the banks configuration file."""
    BANKS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BANKS_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# ──────────────────────────────────────────────────────────────────────
# Bank operations
# ──────────────────────────────────────────────────────────────────────

def list_banks() -> List[Dict[str, Any]]:
    """Return the list of configured Memory Banks."""
    config = load_banks_config()
    return config.get("banks", [])


def init_bank(bank_id: str, purpose: str) -> Dict[str, Any]:
    """Initialize (register) a new Memory Bank."""
    config = load_banks_config()
    banks = config.get("banks", [])

    # Check if bank already exists
    for bank in banks:
        if bank["id"] == bank_id:
            logger.info("Bank %s already registered", bank_id)
            return bank

    # Add new bank
    new_bank = {"id": bank_id, "purpose": purpose}
    banks.append(new_bank)
    config["banks"] = banks
    save_banks_config(config)

    logger.info("Bank %s initialized", bank_id)
    return new_bank


def validate_bank(bank_id: str) -> bool:
    """Validate that a Bank exists and is accessible."""
    banks = list_banks()
    bank_ids = [b["id"] for b in banks]
    if bank_id in bank_ids:
        logger.info("Bank %s validated", bank_id)
        return True
    logger.warning("Bank %s not found in configuration", bank_id)
    return False


def check_bank_permissions(
    bank_id: str, required_actions: List[str]
) -> Dict[str, bool]:
    """Check whether a Bank grants the requested actions."""
    result: Dict[str, bool] = {}
    for action in required_actions:
        # Default: grant read for personal banks, deny otherwise
        result[action] = bank_id in {"personal-core", "personal-learning"}
    return result


# ──────────────────────────────────────────────────────────────────────
# MCP integration helpers
# ──────────────────────────────────────────────────────────────────────

def build_mcp_capabilities(bank_ids: List[str]) -> Dict[str, Any]:
    """Build the MCP capability advertisement for the given Banks."""
    capabilities: Dict[str, Any] = {
        "remember": {"banks": bank_ids, "requires_auth": True},
        "recall": {"banks": bank_ids, "requires_auth": True},
        "list_banks": {"banks": [], "requires_auth": False},
    }
    return capabilities