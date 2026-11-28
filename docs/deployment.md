# InfraPulse Continuous Deployment & Release Management (Stage 13)

> **Scope:** Stage 13 implements the registry-only Compose override, GitHub Actions staging deployment workflow, server-side deployment/rollback scripts, and automated validation. Actual Linux host provisioning is deferred to **Stage 14**; no remote server has been provisioned yet.

## 1. Architecture

InfraPulse deploys pre-built, CI-validated container images from `ghcr.io/luciddie/infrapulse` by **immutable SHA-256 manifest digest**—never `:latest` and never by building source code on the target host.

1. **Runner-side verification ([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)):** Manual `workflow_dispatch` on `refs/heads/main` targeting the `staging` GitHub Environment. Validates digest format (`^sha256:[0-9a-f]{64}$`), `linux/amd64` platform config, SLSA Build Provenance (`https://slsa.dev/provenance/v1`), and SPDX SBOM (`https://spdx.dev/Document`) attestations via `gh attestation verify` before opening an SSH connection.
2. **Server-side execution ([`scripts/deploy/deploy.sh`](../scripts/deploy/deploy.sh)):** Acquires an exclusive `flock` lock, reconciles any interrupted deployment, pulls the verified digest, validates the merged [`compose.yml`](../compose.yml) + [`compose.deploy.yml`](../compose.deploy.yml) configuration, quiesces `app`, creates and validates a `pg_dump -Fc` backup, runs `alembic upgrade head` once, starts `app` (`--no-deps --no-build`), validates health/readiness/metrics/Prometheus, and atomically updates `release.json`.

> **Runner-side vs. Server-side Verification:** Attestation verification runs on the GitHub Actions runner before SSH because the deployment host does not require `gh` CLI or GitHub API tokens. The host independently verifies the pulled `Image ID` and `linux/amd64` architecture.

## 2. Stage 14 Server Bootstrap Prerequisites

Before running `deploy.yml` against a real host, Stage 14 must provision:
- **OS & Runtime:** Ubuntu 24.04 LTS with **Docker Engine 24.0+**, **Docker Compose v2.20.0+** (required for `build: !reset null`), `bash`, `flock` (`util-linux`), `python3`, `df`, `sha256sum`, and OpenSSH server.
- **Deployment Account:** Dedicated non-root user `infrapulse-deploy` (`PasswordAuthentication no`, `PermitRootLogin no`).
  - *Security note:* Standard `docker` group membership grants root-equivalent host access. A `sudo` wrapper or `ForceCommand` only provides isolation if `infrapulse-deploy` cannot modify the scripts, Compose files, or `.env`.
- **Directory Layout (`/opt/infrapulse`):**
  - `/opt/infrapulse/.env` (`0600`, server-managed secrets; `TELEGRAM_ENABLED=false` in staging)
  - `/opt/infrapulse/compose.yml`, `compose.deploy.yml`, `compose.telegram.yml`, `monitoring/`, `scripts/deploy/` (synced from trusted `main` commits—never assumed to auto-sync)
  - `/opt/infrapulse/{state,backups,locks,logs}` (`0700`, owned by `infrapulse-deploy`; lock file at `/opt/infrapulse/locks/deploy.lock`, not `/var/lock`)
- **Fixed Compose Project Name:** `infrapulse` (matching `COMPOSE_PROJECT_NAME=infrapulse`).

## 3. GitHub Environment & SSH Setup

Configure a GitHub Environment named **`staging`** (optionally with required reviewers) and set **Deployment branches and tags** to **Selected branches: `main` only**. (A workflow-level `if: github.ref == 'refs/heads/main'` check alone is not a sufficient security boundary against a modified workflow on a feature branch.) Set these environment secrets:
- `DEPLOY_HOST`: Staging server IP or hostname
- `DEPLOY_PORT`: SSH port (default `22`)
- `DEPLOY_USER`: `infrapulse-deploy`
- `DEPLOY_SSH_KEY`: Dedicated Ed25519 private key (never committed to Git)
- `DEPLOY_HOST_KNOWN_HOSTS`: Independently verified `ssh-keyscan` / host public key line(s) for `StrictHostKeyChecking=yes`

## 4. Manual Staging Deployment & Digest Selection

1. Locate a verified `sha256:...` digest from the `main` branch `publish` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
2. In GitHub Actions, run **InfraPulse Staging Deployment** (`deploy.yml`) from `main` with `image_digest = sha256:<64-hex-chars>`.
3. Verification commands (also run automatically by `deploy.yml`):
   ```bash
   gh attestation verify "oci://ghcr.io/luciddie/infrapulse@sha256:<DIGEST>" \
     --repo luciddie/infrapulse \
     --signer-workflow luciddie/infrapulse/.github/workflows/ci.yml \
     --source-ref refs/heads/main \
     --predicate-type https://slsa.dev/provenance/v1
   ```
   *(Note: Workflow provenance proves the image was attested by the trusted `main`-branch workflow; it does not claim a specific SLSA build level.)*

## 5. Release State Machine & Interrupted Deployments

[`scripts/deploy/lib.sh`](../scripts/deploy/lib.sh) atomically updates `/opt/infrapulse/state/release.json` via `os.replace` while keeping `last_successful_release` intact during in-progress attempts.

- **States:** `preflight` → `image_verified` → `application_stopped` → `backup_completed` → `migration_started` → `migration_completed` → `application_started` → `validation_completed` → `succeeded` (or `rolled_back` / `recovery_required`).
- **Signals & Reconciliation:** `INT`/`TERM`/`HUP` traps mark `result=interrupted`. `SIGKILL` or power loss leaves `result=in_progress`. On the next run, `deploy.sh` inspects `active_attempt.phase`: if interrupted during `migration_started` or `recovery_required`, it fails closed until an operator inspects the DB schema.

## 6. PostgreSQL Backup & Tested Restore Procedure

Before every migration, `deploy.sh` stops `app` (preventing concurrent scheduler writes), verifies free disk space (`>= 2 GiB`), streams `pg_dump -Fc` with `umask 077` to a `.tmp` file, validates it with `pg_restore --list`, writes a `.sha256` sidecar, and atomically renames it. Backups from failed/unresolved deployments are never pruned.

> **Important:** `pg_dump` + `pg_restore --list` proves archive readability, **not** full disaster recovery. Same-host backups do not protect against host/disk loss.

**Tested restore into a disposable database:**
```bash
docker compose exec -T postgres createdb -U infrapulse infrapulse_restore_test
docker compose exec -T postgres pg_restore -U infrapulse -d infrapulse_restore_test < /opt/infrapulse/backups/infrapulse_<ts>_<id>.dump
```

## 7. Conservative Rollback & Migration Compatibility

- **Automatic rollback (`deploy.sh`):** Permitted **only** when `previous_successful_image` exists, its image is available, and `schema_before == schema_after`. Even when automatic rollback succeeds, `deploy.sh` exits non-zero so the failed deployment is never reported as green.
- **Manual rollback (`scripts/deploy/rollback.sh`):** Acquires `deploy.lock`, verifies `CURRENT_DB_REV == TARGET_IMAGE_HEAD`, replaces `app` with `--no-build --no-deps`, and re-validates health/readiness.
- **Incompatible schemas:** If `alembic upgrade head` changed the schema before failure, rollback is **blocked** (`recovery_required`). Never run `alembic downgrade` or restore backups over live data automatically.

## 8. Security Boundaries & Known Limitations

- **Single-instance downtime:** With `--workers 1`, replacing `app` causes brief (~5–15s) API downtime; zero-downtime deployment is not claimed.
- **Staging notifications:** `TELEGRAM_FORCE_DISABLE=true` forces `TELEGRAM_ENABLED=false` and omits `compose.telegram.yml` during staging.
- **Concurrency:** `deploy-staging` uses `cancel-in-progress: false` (GitHub Actions queues at most one pending run per concurrency group) alongside server-side `flock`.
