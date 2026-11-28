#!/usr/bin/env bash
# InfraPulse Stage 13 server-side deployment script.
# Consumes an immutable GHCR digest, backs up PostgreSQL, runs Alembic once, and validates health.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

DIGEST=""
REQUESTED_COMMIT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --digest)
            DIGEST="${2:-}"
            shift 2
            ;;
        --commit)
            REQUESTED_COMMIT="${2:-}"
            shift 2
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 2
            ;;
    esac
done

if [[ -z "${DIGEST}" ]]; then
    log_error "Missing required --digest argument."
    exit 2
fi
if [[ -n "${REQUESTED_COMMIT}" ]] && ! printf '%s' "${REQUESTED_COMMIT}" | grep -Eq '^[0-9a-f]{40}$'; then
    log_error "Invalid --commit '${REQUESTED_COMMIT}'. Expected 40-char lowercase hex SHA."
    exit 2
fi

ATTEMPT_ID="dep-$(date -u +%Y%m%d%H%M%S)-$$"
START_EPOCH="$(date +%s)"
CURRENT_PHASE="preflight"

# 1. Acquire server-side lock before installing signal handlers or mutating state
acquire_deploy_lock

on_signal() {
    log_error "Deployment ${ATTEMPT_ID} interrupted during phase '${CURRENT_PHASE}'."
    write_state_atomic attempt \
        "attempt_id=${ATTEMPT_ID}" \
        "phase=${CURRENT_PHASE}" \
        "result=interrupted" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" || true
    exit 130
}
trap on_signal INT TERM HUP

# 2. Validate configuration and existing release state
if [[ ! -f "${ENV_FILE}" ]] || [[ ! -f "${COMPOSE_BASE}" ]] || [[ ! -f "${COMPOSE_DEPLOY}" ]]; then
    log_error "Missing required configuration (.env, compose.yml, or compose.deploy.yml) in ${DEPLOY_ROOT}."
    exit 1
fi

if [[ "${TELEGRAM_FORCE_DISABLE}" == "true" ]]; then
    export DEPLOY_TELEGRAM_ENABLED=false
    export DEPLOY_TELEGRAM_BOT_TOKEN=""
    export DEPLOY_TELEGRAM_CHAT_ID=""
fi

# 3. Reject any unresolved previous deployment or rollback attempt
PREV_PHASE="$(read_state_field "active_attempt.phase")"
PREV_RESULT="$(read_state_field "active_attempt.result")"
if [[ -n "${PREV_PHASE}" ]] && [[ "${PREV_RESULT}" == "in_progress" || "${PREV_RESULT}" == "interrupted" || "${PREV_RESULT}" == "recovery_required" || "${PREV_PHASE}" == "recovery_required" ]]; then
    log_error "Unresolved previous attempt (phase=${PREV_PHASE}, result=${PREV_RESULT}). Explicit operator recovery is required."
    exit 1
fi

# 4. Validate requested digest & mandatory server-side attestations
validate_digest_format "${DIGEST}"
export INFRAPULSE_DIGEST="${DIGEST}"
IMAGE_REF="${IMAGE_REPO}@${DIGEST}"
verify_server_attestations "${IMAGE_REF}"

if [[ -n "${REQUESTED_COMMIT}" ]] && [[ "${REQUESTED_COMMIT}" != "${VERIFIED_SOURCE_COMMIT}" ]]; then
    log_error "Requested commit '${REQUESTED_COMMIT}' does not match provenance commit '${VERIFIED_SOURCE_COMMIT}'."
    exit 1
fi
SOURCE_COMMIT="${VERIFIED_SOURCE_COMMIT}"

# Check idempotent repeat deployment before mutating state or stopping app
LAST_DIGEST="$(read_state_field "last_successful_release.digest")"
LAST_IMAGE_ID="$(read_state_field "last_successful_release.image_id")"
LAST_REV="$(read_state_field "last_successful_release.alembic_revision")"

if [[ "${LAST_DIGEST}" == "${DIGEST}" ]] && [[ -n "${LAST_IMAGE_ID}" ]] && [[ -n "${LAST_REV}" ]]; then
    APP_CID="$(COMPOSE_CMD_TIMEOUT=10 compose_cmd ps -q app 2>/dev/null || true)"
    if [[ -n "${APP_CID}" ]]; then
        RUNNING_ID="$(timeout 10 docker inspect --format='{{.Image}}' "${APP_CID}" 2>/dev/null || true)"
        if [[ "${RUNNING_ID}" == "${LAST_IMAGE_ID}" ]]; then
            if validate_app_and_monitoring "${LAST_IMAGE_ID}" "${LAST_REV}"; then
                log_info "Digest ${DIGEST} is already deployed, healthy, and at expected revision ${LAST_REV}. No-op."
                exit 0
            fi
        fi
    fi
fi

# Reset active_attempt cleanly for this deployment while preserving last_successful_release
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
write_state_atomic new_attempt \
    "attempt_id=${ATTEMPT_ID}" \
    "type=deploy" \
    "requested_digest=${DIGEST}" \
    "source_commit=${SOURCE_COMMIT}" \
    "phase=preflight" \
    "started_at=${STARTED_AT}" \
    "result=in_progress"

# 5. Pull verified image
log_info "Pulling verified image ${IMAGE_REF}..."
if ! timeout 180 docker pull "${IMAGE_REF}"; then
    log_error "Failed to pull ${IMAGE_REF}."
    write_state_atomic attempt "phase=preflight" "result=failed" "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

# 6. Confirm local image identity and architecture
TARGET_IMAGE_ID="$(docker inspect --format='{{.Id}}' "${IMAGE_REF}")"
TARGET_ARCH="$(docker inspect --format='{{.Os}}/{{.Architecture}}' "${IMAGE_REF}")"
if [[ "${TARGET_ARCH}" != "linux/amd64" ]]; then
    log_error "Unexpected image architecture '${TARGET_ARCH}'; expected linux/amd64."
    write_state_atomic attempt "phase=preflight" "result=failed" "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

CURRENT_PHASE="image_verified"
write_state_atomic attempt "phase=image_verified"

# 7. Validate effective Compose configuration
if ! validate_compose_effective_config "${IMAGE_REF}"; then
    log_error "Effective Compose validation failed."
    write_state_atomic attempt "phase=image_verified" "result=failed" "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

# 8. Check disk space and database readiness
check_disk_space
log_info "Ensuring PostgreSQL and monitoring dependencies are running..."
compose_cmd up -d --no-build postgres prometheus grafana alertmanager
wait_for_postgres_healthy

# 9. Record current image digest and database migration revision
SCHEMA_BEFORE="$(get_db_alembic_revision)"
EXPECTED_HEAD="$(get_image_alembic_head)"
PREV_SUCCESS_DIGEST="$(read_state_field "last_successful_release.digest")"
PREV_SUCCESS_ID="$(read_state_field "last_successful_release.image_id")"
write_state_atomic attempt "schema_before=${SCHEMA_BEFORE}"

# 10. Quiesce existing application when present
if [[ -n "$(compose_cmd ps -q app 2>/dev/null || true)" ]]; then
    log_info "Stopping existing application container..."
    compose_cmd stop app
fi
CURRENT_PHASE="application_stopped"
write_state_atomic attempt "phase=application_stopped"

# 11. Create and validate PostgreSQL backup
log_info "Creating and validating pre-migration PostgreSQL backup..."
if ! create_and_validate_backup "${ATTEMPT_ID}"; then
    log_error "Pre-migration backup failed; aborting deployment before migration."
    write_state_atomic attempt \
        "phase=recovery_required" \
        "result=recovery_required" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi
CURRENT_PHASE="backup_completed"
write_state_atomic attempt \
    "phase=backup_completed" \
    "backup_path=${BACKUP_PATH}" \
    "backup_sha256=${BACKUP_SHA256}"
log_info "Backup validated: ${BACKUP_PATH} (${BACKUP_SHA256})"

# 12. Execute exactly one controlled Alembic migration operation
CURRENT_PHASE="migration_started"
write_state_atomic attempt "phase=migration_started"
log_info "Running Alembic migration (schema_before=${SCHEMA_BEFORE}, target_head=${EXPECTED_HEAD})..."
if ! compose_cmd run --rm --no-deps migrate; then
    SCHEMA_ON_FAIL="$(get_db_alembic_revision || echo "uncertain")"
    log_error "Alembic migration failed (schema_before=${SCHEMA_BEFORE}, schema_after=${SCHEMA_ON_FAIL})."
    write_state_atomic attempt \
        "phase=recovery_required" \
        "schema_after=${SCHEMA_ON_FAIL}" \
        "result=recovery_required" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi

# 13. Record resulting database migration revision
SCHEMA_AFTER="$(get_db_alembic_revision)"
if [[ "${SCHEMA_AFTER}" != "${EXPECTED_HEAD}" ]]; then
    log_error "Post-migration revision '${SCHEMA_AFTER}' != expected head '${EXPECTED_HEAD}'."
    write_state_atomic attempt \
        "phase=recovery_required" \
        "schema_after=${SCHEMA_AFTER}" \
        "result=recovery_required" \
        "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 1
fi
CURRENT_PHASE="migration_completed"
write_state_atomic attempt \
    "phase=migration_completed" \
    "schema_after=${SCHEMA_AFTER}"

# 14. Start the new application container without rerunning migrations
log_info "Starting new application container (${TARGET_IMAGE_ID})..."
APP_START_OK="true"
if ! compose_cmd up -d --no-build --no-deps app; then
    APP_START_OK="false"
    log_error "docker compose up failed for new application container."
fi
CURRENT_PHASE="application_started"
write_state_atomic attempt "phase=application_started"

# 15. Verify application health and monitoring (or perform conservative rollback)
if [[ "${APP_START_OK}" != "true" ]] || ! validate_app_and_monitoring "${TARGET_IMAGE_ID}" "${SCHEMA_AFTER}"; then
    log_error "Post-deployment startup or health validation failed. Stopping unhealthy application container..."
    compose_cmd stop app || true

    if [[ -n "${PREV_SUCCESS_DIGEST}" ]] && [[ "${SCHEMA_BEFORE}" == "${SCHEMA_AFTER}" ]] && [[ "${SCHEMA_BEFORE}" != "uninitialized" ]]; then
        log_warn "Schema unchanged (${SCHEMA_BEFORE}); attempting conservative rollback to ${PREV_SUCCESS_DIGEST}..."
        PREV_REF="${IMAGE_REPO}@${PREV_SUCCESS_DIGEST}"
        export INFRAPULSE_DIGEST="${PREV_SUCCESS_DIGEST}"
        if verify_server_attestations "${PREV_REF}" \
            && docker inspect "${PREV_REF}" >/dev/null 2>&1 \
            && [[ "$(docker inspect --format='{{.Os}}/{{.Architecture}}' "${PREV_REF}")" == "linux/amd64" ]] \
            && [[ "$(docker inspect --format='{{.Id}}' "${PREV_REF}")" == "${PREV_SUCCESS_ID}" ]] \
            && compose_cmd up -d --no-build --no-deps app \
            && validate_app_and_monitoring "${PREV_SUCCESS_ID}" "${SCHEMA_BEFORE}"; then
            write_state_atomic rollback_success \
                "digest=${PREV_SUCCESS_DIGEST}" \
                "image_id=${PREV_SUCCESS_ID}" \
                "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            write_state_atomic attempt "result=failed" "rollback_result=succeeded"
            log_warn "Conservative rollback succeeded, but deployment ${ATTEMPT_ID} is marked FAILED."
            exit 1
        else
            compose_cmd stop app || true
            write_state_atomic attempt \
                "phase=recovery_required" \
                "result=recovery_required" \
                "rollback_result=failed" \
                "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            log_error "Rollback failed. Unhealthy app stopped; manual recovery required (backup preserved at ${BACKUP_PATH})."
            exit 1
        fi
    else
        write_state_atomic attempt \
            "phase=recovery_required" \
            "result=recovery_required" \
            "rollback_result=blocked_schema_changed" \
            "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        log_error "Rollback blocked: schema changed (${SCHEMA_BEFORE} -> ${SCHEMA_AFTER}) or no previous release. Backup preserved at ${BACKUP_PATH}."
        exit 1
    fi
fi

CURRENT_PHASE="validation_completed"
write_state_atomic attempt "phase=validation_completed"

# 16. Atomically commit successful release state
COMPLETED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
write_state_atomic commit_success \
    "digest=${DIGEST}" \
    "image_id=${TARGET_IMAGE_ID}" \
    "source_commit=${SOURCE_COMMIT}" \
    "alembic_revision=${SCHEMA_AFTER}" \
    "completed_at=${COMPLETED_AT}"

prune_old_backups "${BACKUP_PATH}"
DURATION="$(( $(date +%s) - START_EPOCH ))"
log_info "Deployment ${ATTEMPT_ID} succeeded in ${DURATION}s (digest=${DIGEST}, revision=${SCHEMA_AFTER})."
