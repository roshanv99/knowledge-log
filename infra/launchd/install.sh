#!/usr/bin/env bash
# Install (or reinstall) the knowledge-log runner and Following-feed discovery sweep as launchd
# agents for this user.
# Uninstall: launchctl bootout gui/$(id -u)/com.knowledge-log.runner && rm ~/Library/LaunchAgents/com.knowledge-log.runner.plist
#            launchctl bootout gui/$(id -u)/com.knowledge-log.social-discover && rm ~/Library/LaunchAgents/com.knowledge-log.social-discover.plist
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
uv_bin="$(command -v uv)"
claude_bin="$(command -v claude)"
grep -q '^KL_RUNNER_TOKEN=' "$repo/.env" 2>/dev/null || {
  echo "No KL_RUNNER_TOKEN in $repo/.env. Issue one: cd backend && uv run manage.py runner_token kl@\$(hostname -s)" >&2
  exit 1
}
path="$(dirname "$uv_bin"):$(dirname "$claude_bin"):/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$repo/logs" "$HOME/Library/LaunchAgents"

target="$HOME/Library/LaunchAgents/com.knowledge-log.runner.plist"
sed -e "s|@REPO@|$repo|g" -e "s|@UV@|$uv_bin|g" -e "s|@PATH@|$path|g" \
  "$repo/infra/launchd/com.knowledge-log.runner.plist" > "$target"
launchctl bootout "gui/$(id -u)/com.knowledge-log.runner" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$target"
echo "Installed $target (polls every 5 minutes; log: $repo/logs/runner-poll.log)."

social_target="$HOME/Library/LaunchAgents/com.knowledge-log.social-discover.plist"
sed -e "s|@REPO@|$repo|g" -e "s|@UV@|$uv_bin|g" -e "s|@PATH@|$path|g" \
  "$repo/infra/launchd/com.knowledge-log.social-discover.plist" > "$social_target"
launchctl bootout "gui/$(id -u)/com.knowledge-log.social-discover" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$social_target"
echo "Installed $social_target (sweeps every 6 hours; log: $repo/logs/social-discover.log)."
echo "Needs the pipeline's 'social' extra: cd pipeline && uv sync --extra social"
