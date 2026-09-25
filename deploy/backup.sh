#!/usr/bin/env bash
# Dump Postgres from the compose stack and upload to Google Drive via rclone.
# Run on the Hostinger host from the repo root (see deploy/HOSTINGER.md).

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

# Google Drive folder (root of My Drive): gdrive:knowledge-log-backups/
DRIVE_BACKUP_FOLDER="${DRIVE_BACKUP_FOLDER:-knowledge-log-backups}"
RCLONE_DEST="gdrive:${DRIVE_BACKUP_FOLDER}"

if ! command -v rclone >/dev/null 2>&1; then
  echo "backup.sh: rclone is not installed (apt install rclone)" >&2
  exit 1
fi

if [[ -n "${RCLONE_CONFIG_B64:-}" ]]; then
  mkdir -p "${HOME}/.config/rclone"
  if ! echo "$RCLONE_CONFIG_B64" | tr -d '\n\r\t ' | base64 -d >"${HOME}/.config/rclone/rclone.conf"; then
    echo "backup.sh: failed to decode RCLONE_CONFIG_B64 (re-create with: base64 -w0 ~/.config/rclone/rclone.conf)" >&2
    exit 1
  fi
  chmod 600 "${HOME}/.config/rclone/rclone.conf"
fi

if [[ ! -f "${HOME}/.config/rclone/rclone.conf" ]]; then
  echo "backup.sh: no rclone config (~/.config/rclone/rclone.conf or RCLONE_CONFIG_B64)" >&2
  exit 1
fi

STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
BACKUP_FILE="/tmp/knowledge-log-${STAMP}.sql.gz"

echo "backup.sh: dumping ${POSTGRES_DB} as ${BACKUP_FILE}"
"${COMPOSE[@]}" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl | gzip >"$BACKUP_FILE"

echo "backup.sh: uploading to ${RCLONE_DEST}/"
rclone mkdir "${RCLONE_DEST}" 2>/dev/null || true
rclone copy "$BACKUP_FILE" "${RCLONE_DEST}/" --log-level INFO

rm -f "$BACKUP_FILE"
echo "backup.sh: done (${STAMP})"
