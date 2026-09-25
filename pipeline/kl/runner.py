"""`kl runner poll`: the launchd job that decides whether to start a Claude Code session.

It is plain Python and costs no Claude usage. Every few minutes it asks the API whether work
is wanted ("Make questions/reels now" was pressed, or auto-run is on and work is waiting). Only
then does it start `claude -p "/mcq-generation"` or `"/reel-generation"` (one session per kind, so
the two can run side by side), restricted to the tools that skill needs, and keeps the Mac awake
while it runs. The cloud never calls into this machine.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from kl.api import Api
from kl.config import PROJECT_ROOT, Settings

# Each kind gets its own session (quiz and reel runs may overlap), its own skill, and only the
# tools that skill needs; anything else is denied without prompting (dontAsk).
KINDS = {
    "quiz": ("/mcq-generation", "Bash(uv run --project pipeline kl mcq *)"),
    "reel": ("/reel-generation", "Bash(uv run --project pipeline --extra reels kl reel *)"),
}
ALLOWED_TOOLS = ["Read", "Edit(./.kl/**)", "Agent"]


def session_command(s: Settings, kind: str = "quiz") -> list[str]:
    skill, engine = KINDS[kind]
    return ["caffeinate", "-i", s.claude_bin, "-p", skill,
            "--permission-mode", "dontAsk", "--allowedTools", *ALLOWED_TOOLS, engine]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path(s: Settings, kind: str = "quiz") -> Path:
    return s.work_dir / f"runner-{kind}.pid"


def running_session(s: Settings, kind: str = "quiz") -> int | None:
    path = lock_path(s, kind)
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
    except ValueError:
        return None
    return pid if _alive(pid) else None


def poll(s: Settings, api: Api, kind: str = "quiz", *, dry_run: bool = False,
         spawn=subprocess.Popen) -> str:
    if pid := running_session(s, kind):
        return f"{kind}: a session is already running (pid {pid})."
    want = api.wanted(kind)
    if not want:
        return f"{kind}: nothing wanted."
    what = f"{want['kind']} ({want['reason']}): {want['document']} pages {want['pages'][0]}-{want['pages'][1]}"
    if dry_run:
        return f"Would start a session for {what}."
    s.logs_dir.mkdir(parents=True, exist_ok=True)
    s.work_dir.mkdir(parents=True, exist_ok=True)
    log = s.logs_dir / f"runner-{kind}-{datetime.now():%Y%m%d-%H%M%S}.log"
    with log.open("w") as out:
        process = spawn(session_command(s, kind), cwd=PROJECT_ROOT, stdout=out, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, start_new_session=True)
    lock_path(s, kind).write_text(str(process.pid))
    return f"Started a session for {what} (pid {process.pid}, log {log})."
