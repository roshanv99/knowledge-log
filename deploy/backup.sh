#!/usr/bin/env bash
# Dump Postgres from the compose stack and upload it to a private Cloudflare R2 bucket via
# rclone. Run on the server from the repo root: nightly from cron (install-backup-cron.sh)
# and before every deploy (ci-deploy.sh).
#
# Why R2 and not Google Drive (what this used to upload to): Drive needs an OAuth login, and
# a Google app left in "Testing" expires its refresh token after 7 days. That silently broke
# every backup — and so every deploy — from 2026-10-02 to 2026-11-01. R2 uses a plain S3 key
# that doesn't expire. The rclone remote is defined entirely from .env below, so there is no
# rclone.conf on the server to keep in sync.
#
# Needs in .env: R2_ENDPOINT_URL (shared with the media bucket — same account) and a token
# scoped to the backups bucket only:
#   BACKUP_R2_BUCKET, BACKUP_R2_ACCESS_KEY_ID, BACKUP_R2_SECRET_ACCESS_KEY

set -euo pipefail

ROOT_DIR="${DEPLOY_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.gateway.yml)

if [[ ! -f .env ]]; then
  echo "backup.sh: missing .env in $ROOT_DIR" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${POSTGRES_USER:?POSTGRES_USER not set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB not set in .env}"
: "${R2_ENDPOINT_URL:?R2_ENDPOINT_URL not set in .env}"
: "${BACKUP_R2_BUCKET:?BACKUP_R2_BUCKET not set in .env}"
: "${BACKUP_R2_ACCESS_KEY_ID:?BACKUP_R2_ACCESS_KEY_ID not set in .env}"
: "${BACKUP_R2_SECRET_ACCESS_KEY:?BACKUP_R2_SECRET_ACCESS_KEY not set in .env}"

# Dumps older than this are deleted after each successful upload.
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-90}"

if ! command -v rclone >/dev/null 2>&1; then
  echo "backup.sh: rclone is not installed (brew install rclone / apt install rclone)" >&2
  exit 1
fi

# An rclone remote named "backups", defined by environment variables instead of rclone.conf.
export RCLONE_CONFIG_BACKUPS_TYPE=s3
export RCLONE_CONFIG_BACKUPS_PROVIDER=Cloudflare
export RCLONE_CONFIG_BACKUPS_ENDPOINT="$R2_ENDPOINT_URL"
export RCLONE_CONFIG_BACKUPS_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_BACKUPS_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"
# A bucket-scoped token can't list or create buckets, which rclone otherwise tries first.
export RCLONE_CONFIG_BACKUPS_NO_CHECK_BUCKET=true
RCLONE_DEST="backups:${BACKUP_R2_BUCKET}/postgres"

STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
BACKUP_FILE="$(mktemp -d)/knowledge-log-${STAMP}.sql.gz"
trap 'rm -rf "$(dirname "$BACKUP_FILE")"' EXIT

echo "backup.sh: dumping ${POSTGRES_DB} as ${BACKUP_FILE}"
"${COMPOSE[@]}" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl | gzip >"$BACKUP_FILE"

echo "backup.sh: uploading to ${RCLONE_DEST}/"
rclone copy "$BACKUP_FILE" "${RCLONE_DEST}/" --log-level NOTICE

echo "backup.sh: removing dumps older than ${RETENTION_DAYS} days"
rclone delete "${RCLONE_DEST}/" --min-age "${RETENTION_DAYS}d" --log-level NOTICE

echo "backup.sh: done (${STAMP})"
