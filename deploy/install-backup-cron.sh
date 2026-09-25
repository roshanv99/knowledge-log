#!/usr/bin/env bash
# Install the daily midnight (IST) backup to Google Drive in the current user's own crontab.
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
# line would silently do nothing. 18:30 UTC = 00:00 IST.
LOG_DIR="${HOME}/logs"
LOG_FILE="${LOG_DIR}/knowledge-log-backup.log"
MARKER="# knowledge-log-backup (managed by deploy/install-backup-cron.sh — do not edit by hand)"
# A notes-sync job this script used to install; removed if it's still there.
NOTES_MARKER="# knowledge-log-notes-sync (managed by deploy/install-backup-cron.sh — do not edit by hand)"

mkdir -p "$LOG_DIR"

NEW_LINE="30 18 * * * cd ${DEPLOY_PATH} && bash deploy/backup.sh >> ${LOG_FILE} 2>&1 ${MARKER}"
{
  # Drops our own lines, and the CRON_TZ and notes-sync lines older versions of this script wrote.
  # grep -v exits 1 when it matches nothing to remove — true on a first install (no crontab
  # yet, or none of these lines in it yet). That's not a failure here, so `|| true` it.
  (crontab -l 2>/dev/null || true) | { grep -vF -e "$MARKER" -e "$NOTES_MARKER" || true; } \
    | { grep -v '^CRON_TZ=' || true; }
  echo "$NEW_LINE"
} | crontab -

echo "install-backup-cron.sh: installed in ${USER}'s crontab"
echo "  schedule: 18:30 UTC (00:00 IST) daily"
echo "  log:      ${LOG_FILE}"
echo "  test now: cd ${DEPLOY_PATH} && bash deploy/backup.sh"
