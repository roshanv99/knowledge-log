#!/usr/bin/env bash
# Install (or reinstall) the knowledge-log runner as a launchd agent for this user.
# Uninstall: launchctl bootout gui/$(id -u)/com.knowledge-log.runner && rm ~/Library/LaunchAgents/com.knowledge-log.runner.plist
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
uv_bin="$(command -v uv)"
claude_bin="$(command -v claude)"
grep -q '^KL_RUNNER_TOKEN=' "$repo/.env" 2>/dev/null || {
  echo "No KL_RUNNER_TOKEN in $repo/.env. Issue one: cd backend && uv run manage.py runner_token kl@\$(hostname -s)" >&2
  exit 1
}
path="$(dirname "$uv_bin"):$(dirname "$claude_bin"):/usr/bin:/bin:/usr/sbin:/sbin"
target="$HOME/Library/LaunchAgents/com.knowledge-log.runner.plist"
mkdir -p "$repo/logs" "$(dirname "$target")"
sed -e "s|@REPO@|$repo|g" -e "s|@UV@|$uv_bin|g" -e "s|@PATH@|$path|g" \
  "$repo/infra/launchd/com.knowledge-log.runner.plist" > "$target"
launchctl bootout "gui/$(id -u)/com.knowledge-log.runner" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$target"
echo "Installed $target (polls every 5 minutes; log: $repo/logs/runner-poll.log)."
