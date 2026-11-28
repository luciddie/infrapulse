#!/usr/bin/env bash
# Mocked unit tests for InfraPulse Stage 13 deploy.sh and rollback.sh.
# Uses image-specific mock state, strict command validation, and explicit release.json assertions.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PASS_COUNT=0
FAIL_COUNT=0

DIGEST_A="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST_B="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
COMMIT_A="1111111111111111111111111111111111111111"
COMMIT_B="2222222222222222222222222222222222222222"

setup_fixture() {
    TMP_DIR="$(mktemp -d)"
    export DEPLOY_ROOT="${TMP_DIR}/opt"
    export STATE_DIR="${DEPLOY_ROOT}/state"
    export BACKUP_DIR="${DEPLOY_ROOT}/backups"
    export LOCK_DIR="${DEPLOY_ROOT}/locks"
    export LOG_DIR="${DEPLOY_ROOT}/logs"
    export STATE_FILE="${STATE_DIR}/release.json"
    export LOCK_FILE="${LOCK_DIR}/deploy.lock"
    export ENV_FILE="${DEPLOY_ROOT}/.env"
    export COMPOSE_BASE="${DEPLOY_ROOT}/compose.yml"
    export COMPOSE_DEPLOY="${DEPLOY_ROOT}/compose.deploy.yml"
    export COMPOSE_TELEGRAM="${DEPLOY_ROOT}/compose.telegram.yml"
    export HEALTH_DEADLINE_SECS=2
    export PROM_DEADLINE_SECS=2
    export SCHED_DEADLINE_SECS=2
    export MIN_FREE_KB=1000
    export MOCK_STATE="${TMP_DIR}/mock.env"

    mkdir -p "${DEPLOY_ROOT}/scripts/deploy" "${TMP_DIR}/bin"
    cp "${REPO_ROOT}/scripts/deploy/lib.sh" "${DEPLOY_ROOT}/scripts/deploy/"
    cp "${REPO_ROOT}/scripts/deploy/deploy.sh" "${DEPLOY_ROOT}/scripts/deploy/"
    cp "${REPO_ROOT}/scripts/deploy/rollback.sh" "${DEPLOY_ROOT}/scripts/deploy/"
    chmod +x "${DEPLOY_ROOT}/scripts/deploy/"*.sh

    printf 'POSTGRES_PASSWORD=test_only\n' > "${ENV_FILE}"
    touch "${COMPOSE_BASE}" "${COMPOSE_DEPLOY}"

    cat > "${MOCK_STATE}" <<'EOF'
MOCK_PULL_FAIL=0
MOCK_ARCH=linux/amd64
MOCK_CONFIG_BAD=0
MOCK_PG_HEALTH=healthy
MOCK_PROM_MISSING=0
MOCK_MULTI_REV=0
MOCK_DB_REV=rev1
MOCK_IMG_HEAD=rev2
MOCK_PARTIAL_DUMP=0
MOCK_RESTORE_LIST_FAIL=0
MOCK_MIGRATE_FAIL=0
MOCK_UNHEALTHY_DIGEST=""
MOCK_APP_RUNNING=0
MOCK_RUNNING_IMAGE_ID=""
MOCK_ROLLBACK_FAIL=0
MOCK_DF_KB=5000000
MOCK_GH_FAIL_PROV=0
MOCK_GH_FAIL_SBOM=0
MOCK_MIGRATE_COUNT=0
MOCK_BACKUP_COUNT=0
EOF

    cat > "${TMP_DIR}/bin/gh" <<'EOF'
#!/usr/bin/env bash
source "${MOCK_STATE}"
[[ "${MOCK_GH_FAIL_PROV}" == "1" ]] && [[ "$*" == *"slsa.dev/provenance/v1"* ]] && exit 1
if [[ "$*" == *"slsa.dev/provenance/v1"* ]]; then
    if [[ "$*" == *"bbbbbbbb"* ]]; then
        c="2222222222222222222222222222222222222222"
    else
        c="1111111111111111111111111111111111111111"
    fi
    printf '[{"verificationResult":{"statement":{"predicate":{"buildDefinition":{"resolvedDependencies":[{"digest":{"gitCommit":"%s"}}]}}}}}]\n' "$c"
    exit 0
elif [[ "$*" == *"spdx.dev/Document"* ]]; then
    [[ "${MOCK_GH_FAIL_SBOM}" == "1" ]] && exit 1
    echo '[]'
    exit 0
fi
exit 99
EOF
    chmod +x "${TMP_DIR}/bin/gh"

    cat > "${TMP_DIR}/bin/df" <<'EOF'
#!/usr/bin/env bash
source "${MOCK_STATE}"
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/sda1 10000000 5000000 ${MOCK_DF_KB} 50% /"
EOF
    chmod +x "${TMP_DIR}/bin/df"

    cat > "${TMP_DIR}/bin/docker" <<'EOF'
#!/usr/bin/env bash
source "${MOCK_STATE}"
cmd="${1:-}"
shift || true

is_target_healthy() {
    if [[ -n "${MOCK_UNHEALTHY_DIGEST}" ]] && [[ "${MOCK_RUNNING_IMAGE_ID}" == *"${MOCK_UNHEALTHY_DIGEST}"* ]]; then
        echo "unhealthy"
    else
        echo "healthy"
    fi
}

case "${cmd}" in
    pull)
        [[ "${MOCK_PULL_FAIL}" == "1" ]] && exit 1
        exit 0
        ;;
    inspect)
        fmt=""
        target=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --format=*) fmt="${1#--format=}"; shift ;;
                --format) fmt="$2"; shift 2 ;;
                *) target="$1"; shift ;;
            esac
        done
        if [[ "${fmt}" == *"Os"* ]]; then
            echo "${MOCK_ARCH}"
        elif [[ "${fmt}" == *"Health"* ]]; then
            if [[ "${target}" == "pg-cid" ]]; then echo "${MOCK_PG_HEALTH}"; else is_target_healthy; fi
        elif [[ "${fmt}" == *"Status"* ]]; then
            [[ "${MOCK_APP_RUNNING}" == "1" ]] && echo "running" || echo "exited"
        elif [[ "${fmt}" == *"Image"* ]]; then
            echo "${MOCK_RUNNING_IMAGE_ID}"
        elif [[ "${fmt}" == *"Id"* ]]; then
            echo "sha256:img-${target#*@}"
        else
            exit 0
        fi
        exit 0
        ;;
    compose)
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --project-name|--env-file|-f) shift 2 ;;
                *) break ;;
            esac
        done
        sub="${1:-}"; shift || true
        case "${sub}" in
            config)
                if [[ "$*" == *"--format json"* ]]; then
                    if [[ "${MOCK_CONFIG_BAD}" == "1" ]]; then
                        echo '{"services":{"app":{"build":".","image":"bad"},"migrate":{"image":"bad"}}}'
                    else
                        ref="ghcr.io/luciddie/infrapulse@${INFRAPULSE_DIGEST}"
                        echo "{\"services\":{\"app\":{\"image\":\"${ref}\"},\"migrate\":{\"image\":\"${ref}\"}}}"
                    fi
                fi
                exit 0
                ;;
            ps)
                svc="${3:-${2:-}}"
                if [[ "${svc}" == "postgres" ]]; then echo "pg-cid";
                elif [[ "${svc}" == "prometheus" ]]; then [[ "${MOCK_PROM_MISSING}" == "1" ]] && true || echo "prom-cid";
                elif [[ "${svc}" == "app" ]] && [[ "${MOCK_APP_RUNNING}" == "1" ]]; then echo "app-cid";
                fi
                exit 0
                ;;
            up)
                if [[ "$*" == *"app"* ]]; then
                    if [[ "${MOCK_ROLLBACK_FAIL}" == "1" ]] && [[ "${INFRAPULSE_DIGEST}" == *"aaaa"* ]]; then
                        exit 1
                    fi
                    sed -i 's/MOCK_APP_RUNNING=.*/MOCK_APP_RUNNING=1/' "${MOCK_STATE}"
                    sed -i "s|MOCK_RUNNING_IMAGE_ID=.*|MOCK_RUNNING_IMAGE_ID=sha256:img-${INFRAPULSE_DIGEST}|" "${MOCK_STATE}"
                fi
                exit 0
                ;;
            stop)
                sed -i 's/MOCK_APP_RUNNING=.*/MOCK_APP_RUNNING=0/' "${MOCK_STATE}"
                exit 0
                ;;
            exec)
                if [[ "$*" == *"pg_dump"* ]]; then
                    MOCK_BACKUP_COUNT=$(( MOCK_BACKUP_COUNT + 1 ))
                    sed -i "s/MOCK_BACKUP_COUNT=.*/MOCK_BACKUP_COUNT=${MOCK_BACKUP_COUNT}/" "${MOCK_STATE}"
                    if [[ "${MOCK_PARTIAL_DUMP}" == "1" ]]; then
                        echo "PGDMP-PARTIAL-CORRUPT"
                        exit 1
                    fi
                    echo "PGDMP-MOCK-BINARY"
                    exit 0
                elif [[ "$*" == *"pg_restore"* ]]; then
                    [[ "${MOCK_RESTORE_LIST_FAIL}" == "1" ]] && exit 1
                    echo "TABLE devices"
                    exit 0
                elif [[ "$*" == *"urlopen"* ]]; then
                    [[ "$(is_target_healthy)" == "healthy" ]] && exit 0 || exit 1
                fi
                exit 99
                ;;
            run)
                if [[ "$*" == *"heads"* ]]; then
                    echo "${MOCK_IMG_HEAD} (head)"
                    exit 0
                elif [[ "$*" == *"alembic_version"* ]]; then
                    [[ "${MOCK_MULTI_REV}" == "1" ]] && exit 1
                    echo "${MOCK_DB_REV}"
                    exit 0
                elif [[ "$*" == *"migrate"* ]]; then
                    MOCK_MIGRATE_COUNT=$(( MOCK_MIGRATE_COUNT + 1 ))
                    sed -i "s/MOCK_MIGRATE_COUNT=.*/MOCK_MIGRATE_COUNT=${MOCK_MIGRATE_COUNT}/" "${MOCK_STATE}"
                    [[ "${MOCK_MIGRATE_FAIL}" == "1" ]] && exit 1
                    sed -i "s/MOCK_DB_REV=.*/MOCK_DB_REV=${MOCK_IMG_HEAD}/" "${MOCK_STATE}"
                    exit 0
                fi
                exit 99
                ;;
            *)
                exit 99
                ;;
        esac
        ;;
    *)
        exit 99
        ;;
esac
EOF
    chmod +x "${TMP_DIR}/bin/docker"
    OLD_PATH="${PATH}"
    export PATH="${TMP_DIR}/bin:${PATH}"
}

teardown_fixture() {
    export PATH="${OLD_PATH}"
    rm -rf "${TMP_DIR}"
}

assert_pass() {
    local name="$1"; shift
    if "$@"; then
        echo "PASS: ${name}"
        PASS_COUNT=$(( PASS_COUNT + 1 ))
    else
        echo "FAIL: ${name}" >&2
        FAIL_COUNT=$(( FAIL_COUNT + 1 ))
    fi
}

assert_fail() {
    local name="$1"; shift
    if "$@"; then
        echo "FAIL (expected non-zero): ${name}" >&2
        FAIL_COUNT=$(( FAIL_COUNT + 1 ))
    else
        echo "PASS (rejected as expected): ${name}"
        PASS_COUNT=$(( PASS_COUNT + 1 ))
    fi
}

assert_eq() {
    local name="$1" actual="$2" expected="$3"
    if [[ "${actual}" == "${expected}" ]]; then
        echo "PASS: ${name} (${actual})"
        PASS_COUNT=$(( PASS_COUNT + 1 ))
    else
        echo "FAIL: ${name}: got '${actual}', expected '${expected}'" >&2
        FAIL_COUNT=$(( FAIL_COUNT + 1 ))
    fi
}

state_get() {
    python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d$1)"
}

load_mock_state() {
    # shellcheck disable=SC1090
    source "${MOCK_STATE}"
}

# 1. Invalid digest & missing config & disk & pull & arch & compose config
setup_fixture
assert_fail "invalid digest rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "latest"
teardown_fixture

setup_fixture
rm -f "${ENV_FILE}"
assert_fail "missing .env rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

setup_fixture
sed -i 's/MOCK_DF_KB=.*/MOCK_DF_KB=100/' "${MOCK_STATE}"
assert_fail "insufficient disk space rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

setup_fixture
sed -i 's/MOCK_PULL_FAIL=.*/MOCK_PULL_FAIL=1/' "${MOCK_STATE}"
assert_fail "pull failure rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

setup_fixture
sed -i 's|MOCK_ARCH=.*|MOCK_ARCH=linux/arm64|' "${MOCK_STATE}"
assert_fail "arm64 architecture rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

setup_fixture
sed -i 's/MOCK_CONFIG_BAD=.*/MOCK_CONFIG_BAD=1/' "${MOCK_STATE}"
assert_fail "compose config with build: rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

# 2. Provenance failure with valid SBOM & SBOM failure with valid provenance
setup_fixture
sed -i 's/MOCK_GH_FAIL_PROV=.*/MOCK_GH_FAIL_PROV=1/' "${MOCK_STATE}"
assert_fail "provenance failure blocks deploy" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

setup_fixture
sed -i 's/MOCK_GH_FAIL_SBOM=.*/MOCK_GH_FAIL_SBOM=1/' "${MOCK_STATE}"
assert_fail "sbom failure blocks deploy" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

# 3. Partial pg_dump failure prevents migration
setup_fixture
sed -i 's/MOCK_PARTIAL_DUMP=.*/MOCK_PARTIAL_DUMP=1/' "${MOCK_STATE}"
assert_fail "partial pg_dump failure rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
load_mock_state
assert_eq "migration did not run after partial pg_dump" "${MOCK_MIGRATE_COUNT}" "0"
assert_eq "state phase is recovery_required" "$(state_get "['active_attempt']['phase']")" "recovery_required"
teardown_fixture

# 4. Multiple Alembic revision rows rejected
setup_fixture
sed -i 's/MOCK_MULTI_REV=.*/MOCK_MULTI_REV=1/' "${MOCK_STATE}"
assert_fail "multiple alembic rows rejected" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

# 5. Missing Prometheus rejected
setup_fixture
sed -i 's/MOCK_PROM_MISSING=.*/MOCK_PROM_MISSING=1/' "${MOCK_STATE}"
assert_fail "missing prometheus fails validation" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
teardown_fixture

# 6. First deployment + idempotent repeat (no extra migration/backup) + upgrade
setup_fixture
sed -i 's/MOCK_DB_REV=.*/MOCK_DB_REV=uninitialized/' "${MOCK_STATE}"
sed -i 's/MOCK_IMG_HEAD=.*/MOCK_IMG_HEAD=rev1/' "${MOCK_STATE}"
assert_pass "first deployment succeeds" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}" --commit "${COMMIT_A}"
load_mock_state
assert_eq "first deploy ran 1 migration" "${MOCK_MIGRATE_COUNT}" "1"
assert_eq "first deploy ran 1 backup" "${MOCK_BACKUP_COUNT}" "1"
assert_pass "repeated deployment is idempotent" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}" --commit "${COMMIT_A}"
load_mock_state
assert_eq "idempotent repeat ran 0 extra migrations" "${MOCK_MIGRATE_COUNT}" "1"
assert_eq "idempotent repeat ran 0 extra backups" "${MOCK_BACKUP_COUNT}" "1"
sed -i 's/MOCK_IMG_HEAD=.*/MOCK_IMG_HEAD=rev2/' "${MOCK_STATE}"
assert_pass "upgrade deployment succeeds" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_B}" --commit "${COMMIT_B}"
assert_eq "last_successful_release is B" "$(state_get "['last_successful_release']['digest']")" "${DIGEST_B}"
assert_eq "previous_successful_image is A" "$(state_get "['previous_successful_image']['digest']")" "${DIGEST_A}"
teardown_fixture

# 7. Successful automatic rollback to healthy A when B is unhealthy (exits non-zero)
setup_fixture
sed -i 's/MOCK_DB_REV=.*/MOCK_DB_REV=rev1/' "${MOCK_STATE}"
sed -i 's/MOCK_IMG_HEAD=.*/MOCK_IMG_HEAD=rev1/' "${MOCK_STATE}"
assert_pass "baseline A succeeds" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
sed -i "s/MOCK_UNHEALTHY_DIGEST=.*/MOCK_UNHEALTHY_DIGEST=bbbbbbbb/" "${MOCK_STATE}"
assert_fail "unhealthy B fails deploy despite rollback" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_B}"
assert_eq "rollback_result is succeeded" "$(state_get "['active_attempt']['rollback_result']")" "succeeded"
assert_eq "currently_running_image restored to A" "$(state_get "['currently_running_image']['digest']")" "${DIGEST_A}"
assert_eq "last_successful_release preserved as A" "$(state_get "['last_successful_release']['digest']")" "${DIGEST_A}"
teardown_fixture

# 8. Blocked rollback on changed schema leaves app stopped and recovery_required
setup_fixture
sed -i 's/MOCK_DB_REV=.*/MOCK_DB_REV=rev1/' "${MOCK_STATE}"
sed -i 's/MOCK_IMG_HEAD=.*/MOCK_IMG_HEAD=rev1/' "${MOCK_STATE}"
assert_pass "baseline A for schema-change block" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
sed -i 's/MOCK_IMG_HEAD=.*/MOCK_IMG_HEAD=rev2/' "${MOCK_STATE}"
sed -i "s/MOCK_UNHEALTHY_DIGEST=.*/MOCK_UNHEALTHY_DIGEST=bbbbbbbb/" "${MOCK_STATE}"
assert_fail "schema-changed healthcheck failure blocks rollback" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_B}"
load_mock_state
assert_eq "no app running after blocked rollback" "${MOCK_APP_RUNNING}" "0"
assert_eq "state is recovery_required" "$(state_get "['active_attempt']['phase']")" "recovery_required"
assert_fail "manual rollback blocked during recovery_required" "${DEPLOY_ROOT}/scripts/deploy/rollback.sh" --digest "${DIGEST_A}"
teardown_fixture

# 9. Failed rollback leaves app stopped and recovery_required
setup_fixture
sed -i 's/MOCK_DB_REV=.*/MOCK_DB_REV=rev1/' "${MOCK_STATE}"
sed -i 's/MOCK_IMG_HEAD=.*/MOCK_IMG_HEAD=rev1/' "${MOCK_STATE}"
assert_pass "baseline A for failed rollback" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
sed -i "s/MOCK_UNHEALTHY_DIGEST=.*/MOCK_UNHEALTHY_DIGEST=bbbbbbbb/" "${MOCK_STATE}"
sed -i 's/MOCK_ROLLBACK_FAIL=.*/MOCK_ROLLBACK_FAIL=1/' "${MOCK_STATE}"
assert_fail "failed rollback exits non-zero" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_B}"
load_mock_state
assert_eq "no app running after failed rollback" "${MOCK_APP_RUNNING}" "0"
assert_eq "rollback_result is failed" "$(state_get "['active_attempt']['rollback_result']")" "failed"
assert_eq "phase is recovery_required" "$(state_get "['active_attempt']['phase']")" "recovery_required"
teardown_fixture

# 10. Interrupted migration blocks both deploy.sh and rollback.sh
setup_fixture
mkdir -p "${STATE_DIR}"
printf '{"active_attempt":{"phase":"migration_started","result":"interrupted"}}\n' > "${STATE_FILE}"
assert_fail "interrupted migration blocks deploy.sh" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
assert_fail "interrupted migration blocks rollback.sh" "${DEPLOY_ROOT}/scripts/deploy/rollback.sh" --digest "${DIGEST_A}"
teardown_fixture

# 11. Lock contention does not modify existing attempt journal
setup_fixture
mkdir -p "${STATE_DIR}" "${LOCK_DIR}"
printf '{"active_attempt":{"attempt_id":"keep-me","phase":"migration_started","result":"in_progress"}}\n' > "${STATE_FILE}"
(
    exec 9>"${LOCK_FILE}"
    flock -x 9
    sleep 2
) &
LOCK_PID=$!
sleep 0.3
assert_fail "concurrent deploy blocked by flock" "${DEPLOY_ROOT}/scripts/deploy/deploy.sh" --digest "${DIGEST_A}"
assert_eq "flock contention did not alter release.json" "$(state_get "['active_attempt']['attempt_id']")" "keep-me"
wait "${LOCK_PID}"
teardown_fixture

echo "UNIT_TESTS_SUMMARY: PASS=${PASS_COUNT} FAIL=${FAIL_COUNT}"
[[ "${FAIL_COUNT}" -eq 0 ]]
