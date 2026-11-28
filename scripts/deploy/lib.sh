#!/usr/bin/env bash
# Shared helpers for InfraPulse deployment and rollback scripts.

set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/infrapulse}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-infrapulse}"
STATE_DIR="${STATE_DIR:-${DEPLOY_ROOT}/state}"
BACKUP_DIR="${BACKUP_DIR:-${DEPLOY_ROOT}/backups}"
LOCK_DIR="${LOCK_DIR:-${DEPLOY_ROOT}/locks}"
LOG_DIR="${LOG_DIR:-${DEPLOY_ROOT}/logs}"
STATE_FILE="${STATE_DIR}/release.json"
LOCK_FILE="${LOCK_DIR}/deploy.lock"
ENV_FILE="${ENV_FILE:-${DEPLOY_ROOT}/.env}"
COMPOSE_BASE="${COMPOSE_BASE:-${DEPLOY_ROOT}/compose.yml}"
COMPOSE_DEPLOY="${COMPOSE_DEPLOY:-${DEPLOY_ROOT}/compose.deploy.yml}"
COMPOSE_TELEGRAM="${COMPOSE_TELEGRAM:-${DEPLOY_ROOT}/compose.telegram.yml}"

export IMAGE_REPO="ghcr.io/luciddie/infrapulse"
readonly TRUSTED_REPO="luciddie/infrapulse"
readonly TRUSTED_SIGNER_WORKFLOW="luciddie/infrapulse/.github/workflows/ci.yml"
readonly TRUSTED_SOURCE_REF="refs/heads/main"

MIN_FREE_KB="${MIN_FREE_KB:-2097152}"
HEALTH_DEADLINE_SECS="${HEALTH_DEADLINE_SECS:-60}"
PROM_DEADLINE_SECS="${PROM_DEADLINE_SECS:-45}"
SCHED_DEADLINE_SECS="${SCHED_DEADLINE_SECS:-75}"
BACKUP_RETENTION_COUNT="${BACKUP_RETENTION_COUNT:-10}"
TELEGRAM_FORCE_DISABLE="${TELEGRAM_FORCE_DISABLE:-true}"

# Populated by verify_server_attestations and create_and_validate_backup
export VERIFIED_SOURCE_COMMIT=""
export BACKUP_PATH=""
export BACKUP_SHA256=""

log_info() {
    printf '[%s] [INFO] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

log_warn() {
    printf '[%s] [WARN] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

log_error() {
    printf '[%s] [ERROR] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

ensure_directories() {
    mkdir -p "${STATE_DIR}" "${BACKUP_DIR}" "${LOCK_DIR}" "${LOG_DIR}"
    chmod 700 "${STATE_DIR}" "${BACKUP_DIR}" "${LOCK_DIR}"
}

acquire_deploy_lock() {
    ensure_directories
    exec 9>"${LOCK_FILE}"
    if ! flock -n 9; then
        log_error "Another deployment or rollback holds lock ${LOCK_FILE}."
        exit 1
    fi
}

validate_digest_format() {
    local digest="$1"
    if ! printf '%s' "${digest}" | grep -Eq '^sha256:[0-9a-f]{64}$'; then
        log_error "Invalid digest '${digest}'. Expected ^sha256:[0-9a-f]{64}$."
        return 1
    fi
}

verify_server_attestations() {
    local image_ref="$1"
    if ! command -v gh >/dev/null 2>&1; then
        log_error "gh CLI is required for server-side attestation verification."
        return 1
    fi

    log_info "Verifying SLSA provenance and SPDX SBOM attestations for ${image_ref}..."
    local prov_json=""
    if ! prov_json="$(timeout 30 gh attestation verify "oci://${image_ref}" \
        --repo "${TRUSTED_REPO}" \
        --signer-workflow "${TRUSTED_SIGNER_WORKFLOW}" \
        --source-ref "${TRUSTED_SOURCE_REF}" \
        --predicate-type "https://slsa.dev/provenance/v1" \
        --format json)"; then
        log_error "SLSA provenance attestation verification failed for ${image_ref}."
        return 1
    fi

    if ! timeout 30 gh attestation verify "oci://${image_ref}" \
        --repo "${TRUSTED_REPO}" \
        --signer-workflow "${TRUSTED_SIGNER_WORKFLOW}" \
        --source-ref "${TRUSTED_SOURCE_REF}" \
        --predicate-type "https://spdx.dev/Document" \
        --format json >/dev/null; then
        log_error "SPDX SBOM attestation verification failed for ${image_ref}."
        return 1
    fi

    local commit=""
    if ! commit="$(printf '%s' "${prov_json}" | python3 -c '
import json, sys
items = json.load(sys.stdin)
commit = ""
if isinstance(items, list) and items:
    stmt = items[0].get("verificationResult", {}).get("statement", {})
    deps = stmt.get("predicate", {}).get("buildDefinition", {}).get("resolvedDependencies", [])
    for dep in deps:
        dig = dep.get("digest", {})
        if "gitCommit" in dig:
            commit = dig["gitCommit"]
            break
print(commit)
')"; then
        log_error "Failed to parse source commit from SLSA provenance."
        return 1
    fi

    if ! printf '%s' "${commit}" | grep -Eq '^[0-9a-f]{40}$'; then
        log_error "Provenance missing valid 40-char gitCommit (got '${commit}')."
        return 1
    fi
    VERIFIED_SOURCE_COMMIT="${commit}"
}

compose_cmd() {
    local -a args=(
        timeout "${COMPOSE_CMD_TIMEOUT:-60}"
        docker compose
        --project-name "${COMPOSE_PROJECT_NAME}"
        --env-file "${ENV_FILE}"
        -f "${COMPOSE_BASE}"
        -f "${COMPOSE_DEPLOY}"
    )
    if [[ "${TELEGRAM_FORCE_DISABLE}" != "true" ]] && [[ -f "${COMPOSE_TELEGRAM}" ]]; then
        args+=(-f "${COMPOSE_TELEGRAM}")
    fi
    "${args[@]}" "$@"
}

validate_compose_effective_config() {
    local expected_ref="$1"
    compose_cmd config -q

    local cfg_json
    cfg_json="$(compose_cmd config --format json)"
    printf '%s' "${cfg_json}" | python3 -c '
import json, sys
expected = sys.argv[1]
cfg = json.load(sys.stdin)
svcs = cfg.get("services", {})
for name in ("app", "migrate"):
    svc = svcs.get(name, {})
    if "build" in svc and svc["build"] is not None:
        raise SystemExit(f"Service {name} still defines build:")
    img = svc.get("image", "")
    if img != expected:
        raise SystemExit(f"Service {name} image {img!r} != expected {expected!r}")
' "${expected_ref}"
}

check_disk_space() {
    local avail_kb
    avail_kb="$(df -Pk "${BACKUP_DIR}" | awk 'NR==2 {print $4}')"
    if [[ -z "${avail_kb}" ]] || (( avail_kb < MIN_FREE_KB )); then
        log_error "Insufficient disk space in ${BACKUP_DIR}: ${avail_kb:-0} KB < ${MIN_FREE_KB} KB."
        return 1
    fi
}

read_state_field() {
    local expr="$1"
    if [[ ! -f "${STATE_FILE}" ]]; then
        return 0
    fi
    python3 -c '
import json, sys
path, expr = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
cur = data
for part in expr.split("."):
    if isinstance(cur, dict) and part in cur:
        cur = cur[part]
    else:
        cur = ""
        break
print(cur if cur is not None else "")
' "${STATE_FILE}" "${expr}"
}

write_state_atomic() {
    local mode="$1"
    shift
    python3 - "${STATE_FILE}" "${mode}" "$@" <<'PY'
import json
import os
import sys

state_path = sys.argv[1]
mode = sys.argv[2]
kv_pairs = dict(arg.split("=", 1) for arg in sys.argv[3:])

if os.path.exists(state_path):
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
else:
    state = {
        "last_successful_release": {},
        "currently_running_image": {},
        "previous_successful_image": {},
        "active_attempt": {},
    }

if mode == "new_attempt":
    state["active_attempt"] = dict(kv_pairs)
elif mode == "attempt":
    attempt = state.setdefault("active_attempt", {})
    attempt.update(kv_pairs)
elif mode == "running_image":
    state["currently_running_image"] = {
        "digest": kv_pairs.get("digest", ""),
        "image_id": kv_pairs.get("image_id", ""),
    }
elif mode == "commit_success":
    prev = state.get("last_successful_release") or {}
    if prev.get("digest") and prev.get("digest") != kv_pairs.get("digest"):
        state["previous_successful_image"] = prev
    success_rec = {
        "digest": kv_pairs.get("digest", ""),
        "image_id": kv_pairs.get("image_id", ""),
        "source_commit": kv_pairs.get("source_commit", ""),
        "alembic_revision": kv_pairs.get("alembic_revision", ""),
        "completed_at": kv_pairs.get("completed_at", ""),
    }
    state["last_successful_release"] = success_rec
    state["currently_running_image"] = {
        "digest": kv_pairs.get("digest", ""),
        "image_id": kv_pairs.get("image_id", ""),
    }
    state.setdefault("active_attempt", {}).update({
        "phase": "succeeded",
        "result": "succeeded",
        "completed_at": kv_pairs.get("completed_at", ""),
    })
elif mode == "rollback_success":
    state["currently_running_image"] = {
        "digest": kv_pairs.get("digest", ""),
        "image_id": kv_pairs.get("image_id", ""),
    }
    state.setdefault("active_attempt", {}).update({
        "phase": "rolled_back",
        "rollback_result": "succeeded",
        "completed_at": kv_pairs.get("completed_at", ""),
    })

tmp_path = f"{state_path}.tmp.{os.getpid()}"
old_umask = os.umask(0o077)
try:
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, state_path)
finally:
    os.umask(old_umask)
PY
}

get_db_alembic_revision() {
    local rev=""
    if ! rev="$(COMPOSE_CMD_TIMEOUT=15 compose_cmd run --rm --no-deps --entrypoint python migrate -c "
from sqlalchemy import text
from app.database import engine
with engine.connect() as c:
    exists = c.execute(text(\"SELECT to_regclass('public.alembic_version')\")).scalar_one()
    if not exists:
        print('uninitialized')
    else:
        rows = [r[0] for r in c.execute(text('SELECT version_num FROM alembic_version')).fetchall()]
        if len(rows) == 0:
            raise SystemExit('alembic_version table is empty')
        if len(rows) > 1:
            raise SystemExit(f'Multiple alembic_version rows detected: {rows}')
        print(rows[0])
" | tr -d '[:space:]')"; then
        log_error "Failed to query Alembic revision from database."
        return 1
    fi
    if [[ -z "${rev}" ]]; then
        log_error "Empty Alembic revision returned by database query."
        return 1
    fi
    printf '%s' "${rev}"
}

get_image_alembic_head() {
    local heads=""
    if ! heads="$(COMPOSE_CMD_TIMEOUT=15 compose_cmd run --rm --no-deps --entrypoint alembic migrate heads | awk '{print $1}')"; then
        log_error "Failed to inspect target image Alembic heads."
        return 1
    fi
    local count
    count="$(printf '%s\n' "${heads}" | sed '/^$/d' | wc -l | tr -d '[:space:]')"
    if [[ "${count}" != "1" ]]; then
        log_error "Expected exactly 1 Alembic head in target image, found ${count}: ${heads}"
        return 1
    fi
    printf '%s' "${heads}" | tr -d '[:space:]'
}

wait_for_postgres_healthy() {
    local deadline=$(( $(date +%s) + HEALTH_DEADLINE_SECS ))
    while (( $(date +%s) < deadline )); do
        local pg_cid health
        pg_cid="$(COMPOSE_CMD_TIMEOUT=10 compose_cmd ps -q postgres 2>/dev/null || true)"
        if [[ -n "${pg_cid}" ]]; then
            health="$(timeout 10 docker inspect --format='{{.State.Health.Status}}' "${pg_cid}" 2>/dev/null || true)"
            if [[ "${health}" == "healthy" ]]; then
                return 0
            fi
        fi
        sleep 2
    done
    log_error "PostgreSQL did not become healthy within ${HEALTH_DEADLINE_SECS}s."
    return 1
}

validate_app_and_monitoring() {
    local expected_image_id="$1"
    local expected_rev="$2"
    local deadline=$(( $(date +%s) + HEALTH_DEADLINE_SECS ))
    local app_cid=""
    local app_ok="false"
    local metrics_body=""

    while (( $(date +%s) < deadline )); do
        app_cid="$(COMPOSE_CMD_TIMEOUT=10 compose_cmd ps -q app 2>/dev/null || true)"
        if [[ -n "${app_cid}" ]]; then
            local state health running_id
            state="$(timeout 10 docker inspect --format='{{.State.Status}}' "${app_cid}" 2>/dev/null || true)"
            health="$(timeout 10 docker inspect --format='{{.State.Health.Status}}' "${app_cid}" 2>/dev/null || true)"
            running_id="$(timeout 10 docker inspect --format='{{.Image}}' "${app_cid}" 2>/dev/null || true)"

            if [[ "${state}" == "running" ]] && [[ "${health}" == "healthy" ]] && [[ "${running_id}" == "${expected_image_id}" ]]; then
                if metrics_body="$(COMPOSE_CMD_TIMEOUT=10 compose_cmd exec -T app python -c "
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5) as r:
    assert r.status == 200
    assert json.loads(r.read().decode()).get('status') == 'healthy'
with urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5) as r:
    assert r.status == 200
    assert json.loads(r.read().decode()).get('database') == 'connected'
with urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=5) as r:
    assert r.status == 200
    body = r.read().decode()
    assert 'infrapulse_monitoring_enabled' in body
    print(body)
" 2>/dev/null)"; then
                    local actual_rev
                    actual_rev="$(get_db_alembic_revision || echo "")"
                    if [[ "${actual_rev}" == "${expected_rev}" ]]; then
                        log_info "Application health, readiness, metrics, and schema (${actual_rev}) verified."
                        app_ok="true"
                        break
                    fi
                fi
            fi
        fi
        sleep 3
    done

    if [[ "${app_ok}" != "true" ]]; then
        log_error "Application health/readiness validation timed out after ${HEALTH_DEADLINE_SECS}s."
        return 1
    fi

    # Mandatory Prometheus scrape validation
    local prom_cid
    prom_cid="$(COMPOSE_CMD_TIMEOUT=10 compose_cmd ps -q prometheus 2>/dev/null || true)"
    if [[ -z "${prom_cid}" ]]; then
        log_error "Prometheus container is missing; scrape health cannot be verified."
        return 1
    fi

    local prom_deadline=$(( $(date +%s) + PROM_DEADLINE_SECS ))
    local prom_ok="false"
    while (( $(date +%s) < prom_deadline )); do
        if COMPOSE_CMD_TIMEOUT=10 compose_cmd exec -T app python -c "
import json, urllib.request
with urllib.request.urlopen('http://prometheus:9090/api/v1/targets', timeout=5) as r:
    data = json.loads(r.read().decode())
targets = [t for t in data['data']['activeTargets'] if t['labels'].get('job') == 'infrapulse']
assert targets and targets[0]['health'] == 'up'
" >/dev/null 2>&1; then
            prom_ok="true"
            break
        fi
        sleep 3
    done
    if [[ "${prom_ok}" != "true" ]]; then
        log_error "Prometheus target infrapulse did not become UP within ${PROM_DEADLINE_SECS}s."
        return 1
    fi
    log_info "Prometheus scrape target infrapulse is UP."

    # If monitoring scheduler is enabled, verify a successful cycle
    if printf '%s\n' "${metrics_body}" | grep -Eq '^infrapulse_monitoring_enabled 1(\.0)?$'; then
        local sched_deadline=$(( $(date +%s) + SCHED_DEADLINE_SECS ))
        local sched_ok="false"
        while (( $(date +%s) < sched_deadline )); do
            if COMPOSE_CMD_TIMEOUT=10 compose_cmd exec -T app python -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=5) as r:
    body = r.read().decode()
for line in body.splitlines():
    if line.startswith('infrapulse_monitoring_cycles_total{status=\"success\"}'):
        val = float(line.split()[-1])
        if val >= 1.0:
            raise SystemExit(0)
raise SystemExit(1)
" >/dev/null 2>&1; then
                sched_ok="true"
                break
            fi
            sleep 3
        done
        if [[ "${sched_ok}" != "true" ]]; then
            log_error "Monitoring scheduler did not record a successful cycle within ${SCHED_DEADLINE_SECS}s."
            return 1
        fi
        log_info "Monitoring scheduler recorded a successful cycle."
    fi
}

create_and_validate_backup() {
    local attempt_id="$1"
    local db_user="${POSTGRES_USER:-infrapulse}"
    local db_name="${POSTGRES_DB:-infrapulse}"
    local ts dump_file tmp_file sha_file

    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    dump_file="${BACKUP_DIR}/infrapulse_${ts}_${attempt_id}.dump"
    tmp_file="${dump_file}.tmp"
    sha_file="${dump_file}.sha256"

    if ! (umask 077 && COMPOSE_CMD_TIMEOUT=120 compose_cmd exec -T postgres pg_dump -U "${db_user}" -Fc -d "${db_name}" > "${tmp_file}"); then
        rm -f "${tmp_file}"
        log_error "pg_dump failed while creating ${tmp_file}."
        return 1
    fi

    if [[ ! -s "${tmp_file}" ]]; then
        rm -f "${tmp_file}"
        log_error "PostgreSQL backup produced an empty file."
        return 1
    fi

    if ! COMPOSE_CMD_TIMEOUT=60 compose_cmd exec -T postgres pg_restore --list < "${tmp_file}" >/dev/null 2>&1; then
        rm -f "${tmp_file}"
        log_error "PostgreSQL backup failed pg_restore --list integrity validation."
        return 1
    fi

    if ! sha256sum "${tmp_file}" | awk -v f="$(basename "${dump_file}")" '{print $1 "  " f}' > "${sha_file}.tmp"; then
        rm -f "${tmp_file}" "${sha_file}.tmp"
        log_error "Failed to compute SHA-256 checksum for backup."
        return 1
    fi

    if ! chmod 600 "${tmp_file}" "${sha_file}.tmp" \
        || ! mv -f "${tmp_file}" "${dump_file}" \
        || ! mv -f "${sha_file}.tmp" "${sha_file}"; then
        rm -f "${tmp_file}" "${sha_file}.tmp"
        log_error "Failed to finalize backup files atomically."
        return 1
    fi

    if ! (cd "${BACKUP_DIR}" && sha256sum -c "$(basename "${sha_file}")" >/dev/null 2>&1); then
        log_error "Backup SHA-256 verification failed after move."
        return 1
    fi

    BACKUP_PATH="${dump_file}"
    BACKUP_SHA256="$(awk '{print $1}' "${sha_file}")"
}

prune_old_backups() {
    local keep="${BACKUP_RETENTION_COUNT}"
    local protected="${1:-}"
    local -a files=()
    while IFS= read -r f; do
        files+=("${f}")
    done < <(find "${BACKUP_DIR}" -maxdepth 1 -name 'infrapulse_*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -nr | cut -d' ' -f2- || true)

    local idx=0
    for f in "${files[@]}"; do
        idx=$(( idx + 1 ))
        if (( idx > keep )) && [[ "${f}" != "${protected}" ]]; then
            rm -f "${f}" "${f}.sha256"
        fi
    done
}
