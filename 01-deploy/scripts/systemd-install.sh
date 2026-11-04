#!/usr/bin/env bash
# Install a user-level systemd unit for the selected Compose profile.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
MODE="${HINDSIGHT_DEPLOY_MODE:-basic}"
SERVICE_NAME="hindsight"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/$SERVICE_NAME.service"
UNINSTALL=false

while (($#)); do
  case "$1" in
    --mode) [[ $# -ge 2 ]] || { echo "Missing mode" >&2; exit 2; }; MODE="$2"; shift 2 ;;
    --uninstall) UNINSTALL=true; shift ;;
    -h|--help) echo "Usage: $0 [--mode basic|production] [--uninstall]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$UNINSTALL" == true ]]; then
  systemctl --user disable --now "$SERVICE_NAME.service" 2>/dev/null || true
  rm -f "$UNIT_FILE"
  systemctl --user daemon-reload
  echo "Removed $UNIT_FILE"
  exit 0
fi

[[ "$MODE" == basic || "$MODE" == production ]] || { echo "Mode must be basic or production" >&2; exit 2; }
[[ "$REPO_ROOT" != *[[:space:]]* ]] || { echo "Repository path must not contain whitespace for this systemd unit generator" >&2; exit 1; }
COMPOSE_DIR="$REPO_ROOT/01-deploy/compose/$MODE"
COMPOSE_FILE="$COMPOSE_DIR/hindsight.yaml"
ENV_FILE="$COMPOSE_DIR/.env"
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing compose file: $COMPOSE_FILE" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Missing env file: $ENV_FILE (copy .env.example first)" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon unavailable" >&2; exit 1; }

DOCKER_BIN="$(command -v docker)"
mkdir -p "$UNIT_DIR"
chmod 700 "$UNIT_DIR"
chmod 600 "$ENV_FILE"

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Hindsight Compose Deployment ($MODE)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$COMPOSE_DIR
ExecStart=$DOCKER_BIN compose --env-file $ENV_FILE -f $COMPOSE_FILE up -d
ExecStop=$DOCKER_BIN compose --env-file $ENV_FILE -f $COMPOSE_FILE stop
TimeoutStartSec=300
TimeoutStopSec=120

[Install]
WantedBy=default.target
EOF
chmod 600 "$UNIT_FILE"
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME.service"
echo "Installed and started $UNIT_FILE"
echo "Check: systemctl --user status $SERVICE_NAME.service"
echo "Logs:  journalctl --user -u $SERVICE_NAME.service"
echo "For boot without an active login, enable user lingering if appropriate."
