"""Generate reels one headless Claude Code session per sample, and measure how much
of the Claude plan's usage windows each one consumes.

    uv run python -m spike.batch [ids ...] [--run DIR] [--stop-at 0.90]

Each reel is `claude -p "/manim-reel-spike <id> --run <run>"`, run from the repo root.
It's a fresh session, so the cost is representative of a scheduled run. Between
reels, a one-turn probe reads the plan's `rate_limit_event`, which gives the
5-hour and 7-day utilisation (0-1, at 1% resolution). The batch stops before
the 7-day window reaches `--stop-at`, and it waits for the 5-hour window to reset
when that one reaches the guard, so it can't lock the user out of Claude.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
SESSION_TIMEOUT_S = 60 * 60


def _stream(cmd: list[str], log: Path | None, timeout: float) -> list[dict]:
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    if log:
        log.write_text(proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else ""))
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def _windows(events: list[dict]) -> dict | None:
    rl = [e["rate_limit_info"] for e in events if e.get("type") == "rate_limit_event"]
    if not rl:
        return None
    w = rl[-1].get("unifiedWindows", {})
    return {k: {"util": v["utilization"], "resets_at": v["resetsAt"]} for k, v in w.items()}


def probe() -> dict:
    ev = _stream(["claude", "-p", "reply ok", "--output-format", "stream-json", "--verbose", "--max-turns", "1"], None, 600)
    w = _windows(ev)
    if w is None:
        raise RuntimeError("no rate_limit_event in probe output")
    return {"t": time.time(), **w}


def delta(before: dict, after: dict, window: str) -> float | None:
    b, a = before[window], after[window]
    if a["resets_at"] != b["resets_at"]:
        return None  # the window rolled over mid-reel; its delta isn't meaningful
    return round(a["util"] - b["util"], 3)


def fmt_pct(x: float | None) -> str:
    return "reset" if x is None else f"{x * 100:.0f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--run")
    ap.add_argument("--stop-at", type=float, default=0.90)
    ap.add_argument("--model", help="model for the whole session, subagents included (e.g. sonnet, opus)")
    a = ap.parse_args()
    ids = a.ids or [s["id"] for s in json.loads((ROOT / "samples.json").read_text())][:10]
    run = Path(a.run) if a.run else ROOT / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    (run / "logs").mkdir(exist_ok=True)
    run_rel = run.resolve().relative_to(ROOT)
    usage_log = run / "usage.jsonl"

    # a laptop idle-sleeping mid-session kills the in-flight API request ("Request timed out")
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    before = probe()
    print(f"start: 5h {fmt_pct(before['five_hour']['util'])}, 7d {fmt_pct(before['seven_day']['util'])}", flush=True)
    rows = []
    for sid in ids:
        if before["seven_day"]["util"] >= a.stop_at:
            print(f"STOP: 7-day window at {before['seven_day']['util']:.0%} (guard {a.stop_at:.0%}); not starting {sid}", flush=True)
            break
        if before["five_hour"]["util"] >= a.stop_at:
            wake = before["five_hour"]["resets_at"] + 60
            print(f"PAUSE: 5-hour window at {before['five_hour']['util']:.0%}; waiting for its reset at "
                  f"{datetime.fromtimestamp(wake):%H:%M}", flush=True)
            time.sleep(max(0, wake - time.time()))
            before = probe()
            print(f"resume: 5h {fmt_pct(before['five_hour']['util'])}, 7d {fmt_pct(before['seven_day']['util'])}", flush=True)
        print(f"▶ {sid}", flush=True)
        t0 = time.time()
        try:
            ev = _stream(["claude", "-p", f"/manim-reel-spike {sid} --run {run_rel}",
                          "--permission-mode", "bypassPermissions", "--output-format", "stream-json", "--verbose",
                          *(["--model", a.model] if a.model else [])],
                         run / "logs" / f"{sid}.jsonl", SESSION_TIMEOUT_S)
            err = ""
        except subprocess.TimeoutExpired:
            ev, err = [], f"session timed out after {SESSION_TIMEOUT_S}s"
        after = probe()
        result = next((e for e in reversed(ev) if e.get("type") == "result"), {})
        state_f = run / sid / "state.json"
        st = json.loads(state_f.read_text()) if state_f.exists() else {}
        row = {
            "id": sid,
            "model": a.model or "default",
            "status": {"done": "passed"}.get(st.get("stage"), st.get("stage", "no-state")),
            "minutes": round((time.time() - t0) / 60, 1),
            "d_five_hour": delta(before, after, "five_hour"),
            "d_seven_day": delta(before, after, "seven_day"),
            "five_hour_after": after["five_hour"]["util"],
            "seven_day_after": after["seven_day"]["util"],
            "turns": result.get("num_turns"),
            "notional_cost_usd": round(result.get("total_cost_usd") or 0, 2),
            "script_rounds": st.get("script_round"),
            "render_fix": st.get("fix_total"),
            "visual_revisions": st.get("visual_round"),
            "visual_score": st.get("visual_score"),
            "error": err or (result.get("result", "")[:300] if result.get("is_error") else ""),
        }
        rows.append(row)
        with usage_log.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"   {row['status']} in {row['minutes']} min · 5h {fmt_pct(row['d_five_hour'])} · 7d {fmt_pct(row['d_seven_day'])} "
              f"· now 5h {fmt_pct(after['five_hour']['util'])} / 7d {fmt_pct(after['seven_day']['util'])} · ${row['notional_cost_usd']}", flush=True)
        before = after

    subprocess.run(["uv", "run", "python", "-W", "ignore", "-m", "spike.cli", "report", str(run)], cwd=ROOT,
                   capture_output=True)
    print(f"done: {len(rows)} sessions, {sum(r['status'] == 'passed' for r in rows)} passed. run dir: {run}", flush=True)


if __name__ == "__main__":
    main()
