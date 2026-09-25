#!/usr/bin/env bash
# Install a daily midnight backup to Google Drive in the current user's own crontab.
# Run on the Hostinger host (once, or automatically after each deploy) — no root needed. The
# `deploy` user this runs as in CI has no sudo (by design, see api-gateway-2/CLAUDE.md), so
# this uses `crontab`, not /etc/cron.d (which only root can write).

set -euo pipefail

DEPLOY_PATH="${1:-}"
if [[ -z "$DEPLOY_PATH" ]]; then
  DEPLOY_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
DEPLOY_PATH="$(cd "$DEPLOY_PATH" && pwd)"

if [[ ! -f "${DEPLOY_PATH}/deploy/backup.sh" ]]; then
  echo "install-backup-cron.sh: missing ${DEPLOY_PATH}/deploy/backup.sh" >&2
  exit 1
fi

# Midnight in this timezone (default: India). Override: BACKUP_CRON_TZ=UTC
CRON_TZ="${BACKUP_CRON_TZ:-Asia/Kolkata}"
LOG_DIR="${HOME}/logs"
LOG_FILE="${LOG_DIR}/knowledge-log-backup.log"
MARKER="# knowledge-log-backup (managed by deploy/install-backup-cron.sh — do not edit by hand)"

mkdir -p "$LOG_DIR"

NEW_LINE="0 0 * * * cd ${DEPLOY_PATH} && bash deploy/backup.sh >> ${LOG_FILE} 2>&1 ${MARKER}"
{
  echo "CRON_TZ=${CRON_TZ}"
  # grep -v exits 1 when it matches nothing to remove — true on a first install (no crontab
  # yet, or none of these lines in it yet). That's not a failure here, so `|| true` it.
  (crontab -l 2>/dev/null || true) | { grep -vF "$MARKER" || true; } | { grep -v '^CRON_TZ=' || true; }
  echo "$NEW_LINE"
} | crontab -

echo "install-backup-cron.sh: installed in ${USER}'s crontab"
echo "  schedule: 00:00 daily (${CRON_TZ})"
echo "  log:      ${LOG_FILE}"
echo "  test now: cd ${DEPLOY_PATH} && bash deploy/backup.sh"
