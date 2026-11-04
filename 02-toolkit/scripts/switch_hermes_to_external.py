#!/usr/bin/env python3
"""Switch Hermes Hindsight config files to a configurable external API URL.

Set HERMES_HOME to the target Hermes configuration directory and
HINDSIGHT_API_URL to the reachable Hindsight API endpoint before running.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
API_URL = os.environ.get("HINDSIGHT_API_URL", "http://127.0.0.1:8888").rstrip("/")


def config_paths() -> list[Path]:
    paths: list[Path] = []
    main = HERMES_HOME / "hindsight" / "config.json"
    if main.is_file():
        paths.append(main)
    profiles = HERMES_HOME / "profiles"
    if profiles.is_dir():
        paths.extend(sorted(profiles.glob("*/hindsight/config.json")))
    return paths


def main() -> int:
    paths = config_paths()
    if not paths:
        print(f"No Hindsight config files found under {HERMES_HOME}")
        return 1

    for path in paths:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["mode"] = "local_external"
        cfg["api_url"] = API_URL
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        check = json.loads(path.read_text(encoding="utf-8"))
        if check.get("mode") != "local_external" or check.get("api_url") != API_URL:
            print(f"[FAIL] {path}")
            return 1
        print(f"[OK] {path}: mode=local_external, api_url={API_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
