#!/usr/bin/env bash
# Isolated real Docker integration test for Stage 13:
# - Effective compose.yml + compose.deploy.yml config (no build:, Telegram forced disabled)
# - Real end-to-end deploy.sh against verified public GHCR image
# - Idempotent repeat deployment (unchanged container ID, backup count, and DB row)
# - Validated backup containing test data + real pg_restore verification

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROJ="infrapulse-cd-it-$$"
TMP_DIR="$(mktemp -d)"
VERIFIED_DIGEST="sha256:7236ad94dd85e2ba778b3f4e9cff43a7cdaa4c213a0f19dcf48b8496ae8bed1a"
export INFRAPULSE_DIGEST="${VERIFIED_DIGEST}"

cleanup() {
    if [[ -f "${TMP_DIR}/compose.yml" ]]; then
        docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" down -v --remove-orphans >/dev/null 2>&1 || true
    fi
    rm -rf "${TMP_DIR}"
    local rem_c rem_v rem_n
    rem_c="$(docker ps -a --filter "label=com.docker.compose.project=${PROJ}" --format "{{.Names}}" | tr '\n' ',')"
    rem_v="$(docker volume ls --filter "label=com.docker.compose.project=${PROJ}" --format "{{.Name}}" | tr '\n' ',')"
    rem_n="$(docker network ls --filter "label=com.docker.compose.project=${PROJ}" --format "{{.Name}}" | tr '\n' ',')"
    echo "CLEANUP_CHECK: containers=[${rem_c}] volumes=[${rem_v}] networks=[${rem_n}]"
}
trap cleanup EXIT

echo "--- 1. Prepare isolated staging test root with fictional .env and non-conflicting ports ---"
mkdir -p "${TMP_DIR}/monitoring"
cp -r "${REPO_ROOT}/monitoring/." "${TMP_DIR}/monitoring/"
cp "${REPO_ROOT}/compose.deploy.yml" "${TMP_DIR}/compose.deploy.yml"
cp "${REPO_ROOT}/compose.telegram.yml" "${TMP_DIR}/compose.telegram.yml"

python3 - "${REPO_ROOT}/compose.yml" "${TMP_DIR}/compose.yml" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, "r", encoding="utf-8").read()
for old, new in [
    ("127.0.0.1:5432:5432", "127.0.0.1:15432:5432"),
    ("127.0.0.1:8000:8000", "127.0.0.1:18000:8000"),
    ("127.0.0.1:9090:9090", "127.0.0.1:19090:9090"),
    ("127.0.0.1:3000:3000", "127.0.0.1:13000:3000"),
    ("127.0.0.1:9093:9093", "127.0.0.1:19093:9093"),
]:
    text = text.replace(old, new)
lines = [ln for ln in text.splitlines() if "container_name:" not in ln]
open(dst, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY

cat > "${TMP_DIR}/.env" <<'EOF'
POSTGRES_PASSWORD=integration_test_only_password
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=12345:fictional_token_never_used
TELEGRAM_CHAT_ID=999999999
MONITORING_ENABLED=false
EOF

echo "--- 2. Verify Telegram isolation & no build: in effective Compose config ---"
CFG_JSON="$(DEPLOY_TELEGRAM_ENABLED=false DEPLOY_TELEGRAM_BOT_TOKEN="" DEPLOY_TELEGRAM_CHAT_ID="" \
    docker compose --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" config --format json)"

printf '%s' "${CFG_JSON}" | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
expected = "ghcr.io/luciddie/infrapulse@sha256:7236ad94dd85e2ba778b3f4e9cff43a7cdaa4c213a0f19dcf48b8496ae8bed1a"
for svc in ("app", "migrate"):
    s = cfg["services"][svc]
    assert "build" not in s or s["build"] is None, f"{svc} still has build"
    assert s["image"] == expected, f"{svc} image mismatch"
app_env = cfg["services"]["app"]["environment"]
assert app_env.get("TELEGRAM_ENABLED") == "false", f"TELEGRAM_ENABLED not false: {app_env}"
assert app_env.get("TELEGRAM_BOT_TOKEN") == "", "TELEGRAM_BOT_TOKEN leaked"
assert app_env.get("TELEGRAM_CHAT_ID") == "", "TELEGRAM_CHAT_ID leaked"
print("COMPOSE_AND_TELEGRAM_ISOLATION_OK")
'

echo "--- 3. Run real deploy.sh (first deployment + idempotent repeat) ---"
export DEPLOY_ROOT="${TMP_DIR}"
export COMPOSE_PROJECT_NAME="${PROJ}"
export ENV_FILE="${TMP_DIR}/.env"
export COMPOSE_BASE="${TMP_DIR}/compose.yml"
export COMPOSE_DEPLOY="${TMP_DIR}/compose.deploy.yml"
export COMPOSE_TELEGRAM="${TMP_DIR}/compose.telegram.yml"
export STATE_DIR="${TMP_DIR}/state"
export BACKUP_DIR="${TMP_DIR}/backups"
export LOCK_DIR="${TMP_DIR}/locks"
export LOG_DIR="${TMP_DIR}/logs"
export MIN_FREE_KB=102400
export TELEGRAM_FORCE_DISABLE=true

bash "${REPO_ROOT}/scripts/deploy/deploy.sh" --digest "${VERIFIED_DIGEST}" --commit "5d6e16fc3343184af03e697443905af614ca252f"

APP_CID_1="$(docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" ps -q app)"
BACKUP_COUNT_1="$(find "${BACKUP_DIR}" -maxdepth 1 -name 'infrapulse_*.dump' | wc -l | tr -d '[:space:]')"
test -n "${APP_CID_1}"
test "${BACKUP_COUNT_1}" = "1"

# Seed fictional device and run idempotent repeat deployment
docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" exec -T postgres \
    psql -U infrapulse -d infrapulse -c "INSERT INTO devices (ip_address, status) VALUES ('192.0.2.10', 'online');"

bash "${REPO_ROOT}/scripts/deploy/deploy.sh" --digest "${VERIFIED_DIGEST}" --commit "5d6e16fc3343184af03e697443905af614ca252f"

APP_CID_2="$(docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" ps -q app)"
BACKUP_COUNT_2="$(find "${BACKUP_DIR}" -maxdepth 1 -name 'infrapulse_*.dump' | wc -l | tr -d '[:space:]')"
test "${APP_CID_2}" = "${APP_CID_1}"
test "${BACKUP_COUNT_2}" = "${BACKUP_COUNT_1}"

PERSISTED_IP="$(docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" exec -T postgres \
    psql -U infrapulse -d infrapulse -tAc "SELECT ip_address FROM devices WHERE ip_address='192.0.2.10';" | tr -d '[:space:]')"
test "${PERSISTED_IP}" = "192.0.2.10"
echo "IDEMPOTENCY_AND_PERSISTENCE_OK"

echo "--- 4. Create validated backup containing fictional device and restore into disposable DB ---"
# shellcheck source=scripts/deploy/lib.sh
source "${REPO_ROOT}/scripts/deploy/lib.sh"
create_and_validate_backup "restore-verify"

docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" exec -T postgres \
    createdb -U infrapulse infrapulse_restore_test

docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" exec -T postgres \
    pg_restore -U infrapulse -d infrapulse_restore_test < "${BACKUP_PATH}"

RESTORED_IP="$(docker compose -p "${PROJ}" --env-file "${TMP_DIR}/.env" -f "${TMP_DIR}/compose.yml" -f "${TMP_DIR}/compose.deploy.yml" exec -T postgres \
    psql -U infrapulse -d infrapulse_restore_test -tAc "SELECT ip_address FROM devices WHERE ip_address='192.0.2.10';" | tr -d '[:space:]')"
test "${RESTORED_IP}" = "192.0.2.10"
echo "REAL_DEPLOY_AND_RESTORE_OK (restored_ip=${RESTORED_IP})"
