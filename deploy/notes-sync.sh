#!/usr/bin/env bash
# Mirror the Google Drive notes folder into ./notes, then record in the app which PDFs exist
# (backend/pipeline/management/commands/sync_notes.py). Runs daily from cron before the cloud
# routines (deploy/install-backup-cron.sh); safe to run by hand any time.
#
# Reads Drive as a Google service account that only the Notes folder is shared with (Viewer),
# so it can't see anything else in the Drive. Its own rclone config,
# ~/.config/rclone/notes.conf (remote "notes:", root_folder_id = the Notes folder), is kept
# apart from rclone.conf, which backup.sh rewrites from RCLONE_CONFIG_B64 on every deploy.
# Setup: deploy/HOSTINGER.md, "Notes from Google Drive".

set -euo pipefail

ROOT_DIR="${DEPLOY_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT_DIR"

CONFIG="${HOME}/.config/rclone/notes.conf"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.gateway.yml)

if [[ ! -f "$CONFIG" ]]; then
  echo "notes-sync.sh: no ${CONFIG} (see deploy/HOSTINGER.md, 'Notes from Google Drive')" >&2
  exit 1
fi

mkdir -p notes
echo "notes-sync.sh: $(date -u +%FT%TZ) mirroring the Drive notes folder -> ${ROOT_DIR}/notes"
# A failed or partial copy stops here (set -e), before the app is told anything.
rclone --config "$CONFIG" sync notes: notes --include "*.pdf" --log-level NOTICE

"${COMPOSE[@]}" exec -T knowledge-log-backend python manage.py sync_notes
