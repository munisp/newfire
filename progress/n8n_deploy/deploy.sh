#!/usr/bin/env bash
# Deploy n8n for a client onto Minisforum (america) via SCP + remote docker compose
# Usage:
#   ./deploy.sh sherifah --dry-run
#   ./deploy.sh sherifah
#
# Honors the SCP workflow rule: no multi-line heredocs over SSH, just file
# transfers plus short single-line commands.

set -euo pipefail

CLIENT="${1:-}"
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1

if [[ -z "$CLIENT" ]]; then
  echo "usage: $0 <client> [--dry-run]" >&2
  exit 1
fi

ENV_FILE=".env.${CLIENT}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE, copy .env.template first" >&2
  exit 1
fi

if [[ "$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")" != "600" ]]; then
  echo "$ENV_FILE must be chmod 600" >&2
  exit 1
fi

HOST="newwaveclaw@america"
REMOTE_DIR="/home/newwaveclaw/n8n/${CLIENT}"

# SECURITY FIX: Replace eval with direct command execution
# eval can inject arbitrary code through crafted command strings
run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "DRY: $*"
  else
    # Execute the command directly without eval
    "$@"
  fi
}

echo "==> [1/6] create remote dir"
run ssh "$HOST" "mkdir -p $REMOTE_DIR"

echo "==> [2/6] scp compose + env"
run scp docker-compose.yml "$HOST:$REMOTE_DIR/docker-compose.yml"
run scp "$ENV_FILE" "$HOST:$REMOTE_DIR/.env"
run ssh "$HOST" "chmod 600 $REMOTE_DIR/.env"

echo "==> [3/6] ensure postgres role + database exist"
# Target Postgres runs in container newfire-db with superuser newfire.
run ssh "$HOST" "docker exec newfire-db psql -U newfire -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='n8n_${CLIENT}'\"" \
  | grep -q 1 || { echo "missing db n8n_${CLIENT}"; exit 2; }

echo "==> [4/6] docker compose up"
run ssh "$HOST" "cd $REMOTE_DIR && docker compose --env-file .env up -d"

echo "==> [5/6] wait for healthy"
run ssh "$HOST" 'for i in $(seq 1 20); do s=$(docker inspect -f "{{.State.Health.Status}}" n8n-${CLIENT} 2>/dev/null || echo none); [ "$s" = healthy ] && exit 0; sleep 3; done; exit 1'

echo "==> [6/6] verify loopback + no public binding"
run ssh "$HOST" "curl -fsS http://127.0.0.1:\$(grep N8N_PORT $REMOTE_DIR/.env | cut -d= -f2)/healthz"
run ssh "$HOST" 'ss -tln | grep -E ":567[0-9] " | grep -v 127.0.0.1 && { echo FAIL: n8n bound to non-loopback; exit 3; } || true'

echo "done. next: apply APISIX route + Caddy vhost + Ziti service. see PLAN.md."