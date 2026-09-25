---
description: Show knowledge-log pipeline activity and what Manage notes has selected
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/kl.sh:*)
---

Run `${CLAUDE_PLUGIN_ROOT}/scripts/kl.sh status` and `${CLAUDE_PLUGIN_ROOT}/scripts/kl.sh docs`, then
summarise:
- how far each selected PDF has been processed
- any active run and what it is doing
- any failed tasks, with their errors
- how the last run ended
