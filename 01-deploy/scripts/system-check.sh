#!/usr/bin/env bash
# Generic prerequisite check for this deployment repository.
set -Eeuo pipefail

fail=0
ok()   { printf '[ OK ] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }
bad()  { printf '[FAIL] %s\n' "$*"; fail=1; }

printf '%s\n' "Hindsight deployment prerequisite check"
if command -v docker >/dev/null 2>&1; then
  ok "$(docker --version)"
  docker info >/dev/null 2>&1 && ok "Docker daemon reachable" || bad "Docker daemon unavailable"
  docker compose version >/dev/null 2>&1 && ok "Docker Compose V2 available" || bad "Docker Compose V2 unavailable"
else
  bad "Docker CLI not found"
fi

if command -v python3 >/dev/null 2>&1; then
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)' \
    && ok "Python 3.12+ available ($(python3 --version 2>&1))" \
    || warn "Python 3.12+ is required only for the Python toolkit"
else
  warn "Python 3 not found (required only for the Python toolkit)"
fi

avail_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
if [[ -n "$avail_kb" && "$avail_kb" -ge 5242880 ]]; then
  ok "At least 5 GiB free on the repository filesystem"
else
  warn "Less than 5 GiB free on the repository filesystem"
fi

if command -v free >/dev/null 2>&1; then
  mem_mb="$(free -m | awk '/^Mem:/ {print $2}')"
  if [[ -n "$mem_mb" && "$mem_mb" -ge 4096 ]]; then
    ok "Memory: ${mem_mb} MiB"
  else
    warn "Memory below 4 GiB (reported: ${mem_mb:-unknown} MiB)"
  fi
fi

exit "$fail"
