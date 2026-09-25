#!/usr/bin/env bash
# Install the daily jobs in the current user's own crontab: the midnight backup to Google Drive,
# and the 05:45 IST notes sync (deploy/notes-sync.sh), just before the 06:00 IST cloud routines.
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

# Times are UTC: the server's cron (Debian/Ubuntu vixie cron) ignores CRON_TZ, so a CRON_TZ
# line would silently do nothing. 18:30 UTC = 00:00 IST; 00:15 UTC = 05:45 IST.
LOG_DIR="${HOME}/logs"
LOG_FILE="${LOG_DIR}/knowledge-log-backup.log"
NOTES_LOG_FILE="${LOG_DIR}/knowledge-log-notes-sync.log"
MARKER="# knowledge-log-backup (managed by deploy/install-backup-cron.sh — do not edit by hand)"
NOTES_MARKER="# knowledge-log-notes-sync (managed by deploy/install-backup-cron.sh — do not edit by hand)"

mkdir -p "$LOG_DIR"

NEW_LINE="30 18 * * * cd ${DEPLOY_PATH} && bash deploy/backup.sh >> ${LOG_FILE} 2>&1 ${MARKER}"
NOTES_LINE="15 0 * * * cd ${DEPLOY_PATH} && bash deploy/notes-sync.sh >> ${NOTES_LOG_FILE} 2>&1 ${NOTES_MARKER}"
{
  # Drops our own lines and the CRON_TZ line older versions of this script wrote.
  # grep -v exits 1 when it matches nothing to remove — true on a first install (no crontab
  # yet, or none of these lines in it yet). That's not a failure here, so `|| true` it.
  (crontab -l 2>/dev/null || true) | { grep -vF -e "$MARKER" -e "$NOTES_MARKER" || true; } \
    | { grep -v '^CRON_TZ=' || true; }
  echo "$NEW_LINE"
  echo "$NOTES_LINE"
} | crontab -

echo "install-backup-cron.sh: installed in ${USER}'s crontab"
echo "  backup:     18:30 UTC (00:00 IST) daily, log ${LOG_FILE}"
echo "  notes sync: 00:15 UTC (05:45 IST) daily, log ${NOTES_LOG_FILE}"
echo "  test now:   cd ${DEPLOY_PATH} && bash deploy/backup.sh  (or deploy/notes-sync.sh)"
