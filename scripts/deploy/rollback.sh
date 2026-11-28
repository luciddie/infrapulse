#!/usr/bin/env bash
# InfraPulse Stage 13 conservative manual rollback script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

TARGET_DIGEST=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --digest)
            TARGET_DIGEST="${2:-}"
            shift 2
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 2
            ;;
    esac
done

ATTEMPT_ID="rb-$(date -u +%Y%m%d%H%M%S)-$$"
CURRENT_PHASE="preflight"

acquire_deploy_lock

on_signal() {
    log_error "Rollback ${ATTEMPT_ID} interrupted during phase '${CURRENT_PHASE}'."
    write_state_atomic attempt \
        "attempt_id=${ATTEMPT_ID}" \
        "phase=${CURRENT_PHASE}" \
        "result=interrupted" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" || true
    exit 130
}
trap on_signal INT TERM HUP

if [[ ! -f "${ENV_FILE}" ]] || [[ ! -f "${COMPOSE_BASE}" ]] || [[ ! -f "${COMPOSE_DEPLOY}" ]]; then
    log_error "Missing required configuration in ${DEPLOY_ROOT}."
    exit 1
fi

if [[ "${TELEGRAM_FORCE_DISABLE}" == "true" ]]; then
    export DEPLOY_TELEGRAM_ENABLED=false
    export DEPLOY_TELEGRAM_BOT_TOKEN=""
    export DEPLOY_TELEGRAM_CHAT_ID=""
fi

PREV_PHASE="$(read_state_field "active_attempt.phase")"
PREV_RESULT="$(read_state_field "active_attempt.result")"
if [[ -n "${PREV_PHASE}" ]] && [[ "${PREV_RESULT}" == "in_progress" || "${PREV_RESULT}" == "interrupted" || "${PREV_RESULT}" == "recovery_required" || "${PREV_PHASE}" == "recovery_required" ]]; then
    log_error "Unresolved previous attempt (phase=${PREV_PHASE}, result=${PREV_RESULT}). Inspect database and recover manually before rolling back."
    exit 1
fi

if [[ -z "${TARGET_DIGEST}" ]]; then
    TARGET_DIGEST="$(read_state_field "previous_successful_image.digest")"
fi

if [[ -z "${TARGET_DIGEST}" ]]; then
    log_error "No target rollback digest provided and no previous_successful_image recorded."
    exit 1
fi

validate_digest_format "${TARGET_DIGEST}"
export INFRAPULSE_DIGEST="${TARGET_DIGEST}"
IMAGE_REF="${IMAGE_REPO}@${TARGET_DIGEST}"
verify_server_attestations "${IMAGE_REF}"

write_state_atomic new_attempt \
    "attempt_id=${ATTEMPT_ID}" \
    "type=rollback" \
    "requested_digest=${TARGET_DIGEST}" \
    "source_commit=${VERIFIED_SOURCE_COMMIT}" \
    "phase=preflight" \
    "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "result=in_progress"

log_info "Ensuring rollback image ${IMAGE_REF} is available..."
if ! docker inspect "${IMAGE_REF}" >/dev/null 2>&1; then
    if ! timeout 180 docker pull "${IMAGE_REF}"; then
        log_error "Failed to pull rollback image ${IMAGE_REF}."
        write_state_atomic attempt "phase=preflight" "result=failed" "rollback_result=failed" "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        exit 1
    fi
fi

TARGET_IMAGE_ID="$(docker inspect --format='{{.Id}}' "${IMAGE_REF}")"
TARGET_ARCH="$(docker inspect --format='{{.Os}}/{{.Architecture}}' "${IMAGE_REF}")"
if [[ "${TARGET_ARCH}" != "linux/amd64" ]]; then
    log_error "Unexpected rollback image architecture: ${TARGET_ARCH}"
    write_state_atomic attempt "phase=preflight" "result=failed" "rollback_result=failed" "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

validate_compose_effective_config "${IMAGE_REF}"
wait_for_postgres_healthy

CURRENT_DB_REV="$(get_db_alembic_revision)"
TARGET_IMAGE_HEAD="$(get_image_alembic_head)"

if [[ "${CURRENT_DB_REV}" == "uninitialized" ]] || [[ "${CURRENT_DB_REV}" != "${TARGET_IMAGE_HEAD}" ]]; then
    log_error "Rollback blocked: current DB revision '${CURRENT_DB_REV}' != rollback image Alembic head '${TARGET_IMAGE_HEAD}'."
    write_state_atomic attempt \
        "phase=recovery_required" \
        "schema_before=${CURRENT_DB_REV}" \
        "result=recovery_required" \
        "rollback_result=blocked_schema_mismatch" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

CURRENT_PHASE="application_stopped"
write_state_atomic attempt "phase=application_stopped" "schema_before=${CURRENT_DB_REV}"
log_info "Stopping current application container and rolling back to ${IMAGE_REF}..."
compose_cmd stop app || true

CURRENT_PHASE="application_started"
write_state_atomic attempt "phase=application_started"
if ! compose_cmd up -d --no-build --no-deps app || ! validate_app_and_monitoring "${TARGET_IMAGE_ID}" "${CURRENT_DB_REV}"; then
    log_error "Rollback startup or post-rollback health validation failed. Stopping unhealthy container..."
    compose_cmd stop app || true
    write_state_atomic attempt \
        "phase=recovery_required" \
        "result=recovery_required" \
        "rollback_result=failed" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

COMPLETED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
write_state_atomic rollback_success \
    "digest=${TARGET_DIGEST}" \
    "image_id=${TARGET_IMAGE_ID}" \
    "completed_at=${COMPLETED_AT}"
write_state_atomic attempt "result=succeeded"

log_info "Manual rollback to ${TARGET_DIGEST} succeeded (revision=${CURRENT_DB_REV})."
