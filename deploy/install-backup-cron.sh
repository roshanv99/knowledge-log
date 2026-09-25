#!/usr/bin/env bash
# Install /etc/cron.d/knowledge-log-backup — daily midnight backup to Google Drive.
# Run on the Hostinger host as root (once, or automatically after each deploy).

set -euo pipefail

DEPLOY_PATH="${1:-}"
if [[ -z "$DEPLOY_PATH" ]]; then
  DEPLOY_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
DEPLOY_PATH="$(cd "$DEPLOY_PATH" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install-backup-cron.sh: run as root (sudo)" >&2
  exit 1
fi

if [[ ! -f "${DEPLOY_PATH}/deploy/backup.sh" ]]; then
  echo "install-backup-cron.sh: missing ${DEPLOY_PATH}/deploy/backup.sh" >&2
  exit 1
fi

# Midnight in this timezone (default: India). Override: BACKUP_CRON_TZ=UTC
CRON_TZ="${BACKUP_CRON_TZ:-Asia/Kolkata}"
CRON_USER="${BACKUP_CRON_USER:-root}"
LOG_FILE="/var/log/knowledge-log-backup.log"

touch "$LOG_FILE"
chmod 644 "$LOG_FILE"

cat > /etc/cron.d/knowledge-log-backup <<EOF
# knowledge-log: daily Postgres dump → Google Drive (gdrive:knowledge-log-backups/)
# Re-run: sudo bash deploy/install-backup-cron.sh ${DEPLOY_PATH}
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
CRON_TZ=${CRON_TZ}

0 0 * * * ${CRON_USER} cd ${DEPLOY_PATH} && bash deploy/backup.sh >> ${LOG_FILE} 2>&1
EOF

chmod 644 /etc/cron.d/knowledge-log-backup

echo "install-backup-cron.sh: installed /etc/cron.d/knowledge-log-backup"
echo "  schedule: 00:00 daily (${CRON_TZ})"
echo "  log:      ${LOG_FILE}"
echo "  test now: cd ${DEPLOY_PATH} && bash deploy/backup.sh"
