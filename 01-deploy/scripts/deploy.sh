#!/usr/bin/env bash
# Deploy a Hindsight Compose profile from this repository.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
MODE="basic"
while (($#)); do
  case "$1" in
    --mode)
      [[ $# -ge 2 ]] || { echo "Missing value for --mode" >&2; exit 2; }
      MODE="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 [--mode basic|production]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$MODE" in
  basic|production) ;;
  *) echo "Invalid mode: $MODE (choose basic or production)" >&2; exit 2 ;;
esac

COMPOSE_DIR="$REPO_ROOT/01-deploy/compose/$MODE"
COMPOSE_FILE="$COMPOSE_DIR/hindsight.yaml"
ENV_FILE="$COMPOSE_DIR/.env"
[[ -f "$COMPOSE_FILE" ]] || { echo "Compose file not found: $COMPOSE_FILE" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || {
  echo "Missing $ENV_FILE. Copy .env.example to .env and configure required values." >&2
  exit 1
}
chmod 600 "$ENV_FILE"
command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose V2 is required." >&2; exit 1; }

cd "$COMPOSE_DIR"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
echo "Deployment requested for profile: $MODE"
echo "API endpoint: use the host port declared in $COMPOSE_FILE"
