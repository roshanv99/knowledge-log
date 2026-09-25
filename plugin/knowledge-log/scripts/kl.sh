#!/usr/bin/env bash
# Run the `kl` pipeline CLI from the knowledge-log repo.
# KL_HOME points at the repo; by default it is two levels above this plugin
# (plugin/knowledge-log/scripts -> repo root), which holds when loaded with --plugin-dir.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KL_HOME="${KL_HOME:-$(cd "$here/../../.." && pwd)}"
if [[ ! -f "$KL_HOME/pipeline/pyproject.toml" ]]; then
  echo "knowledge-log repo not found at $KL_HOME; set KL_HOME" >&2
  exit 1
fi
exec uv run --quiet --project "$KL_HOME/pipeline" kl "$@"
