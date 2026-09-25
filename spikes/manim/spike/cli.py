"""Deterministic tool side of the 2b spike. No LLM calls in here.

The Claude Code session does all the writing and judging (driven by the
`manim-reel-spike` skill). This CLI does everything else and owns the loop
state in `<work>/state.json`, so the round budgets are enforced by code and
not by the model's memory. Every command ends with a `NEXT:` line.

    python -m spike.cli init <sample_id> [--run DIR]
    python -m spike.cli check-script <work>
    python -m spike.cli verdict <work> script --pass|--fail [--severity S] [--issue ...]
    python -m spike.cli tts <work>
    python -m spike.cli render <work>
    python -m spike.cli verdict <work> visual --pass|--fail --score N [--issue ...]
    python -m spike.cli status <work>
    python -m spike.cli report <run>
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from . import media

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"

SCRIPT_ROUNDS = 3  # 1 draft + 2 revisions (settings.max_revisions default)
FIX_ROUNDS = 3     # plan: render_fix up to 3 times (per visual round)
VISUAL_ROUNDS = 2  # revisions after the first failed visual_check
WORDS = (110, 150)  # must match prompts/manim-script.md


class Beat(BaseModel):
    narration: str
    visual: str
    pace: float = Field(1.0, ge=0.85, le=1.1, description="speech speed for this beat; <1 slower")


class Script(BaseModel):
    title: str
    key_point: str
    beats: list[Beat] = Field(min_length=3, max_length=8)


# --- state -----------------------------------------------------------------------

def _load(work: Path) -> dict:
    return json.loads((work / "state.json").read_text())


def _save(work: Path, st: dict):
    (work / "state.json").write_text(json.dumps(st, indent=2))


def _event(st: dict, kind: str, **kw):
    st["events"].append({"t": round(time.time(), 1), "kind": kind, **kw})


def _stage(st: dict, *allowed: str):
    if st["stage"] not in allowed:
        sys.exit(f"ERROR: this command needs stage {allowed}, but stage is {st['stage']!r}.\n{_next(st)}")


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def _next(st: dict) -> str:
    w = st["work"]
    return {
        "script": (f"NEXT: write/revise {w}/script.json following prompts/manim-script.md, then "
                   f"`uv run python -m spike.cli check-script {w}`."),
        "critic": (f"NEXT: spawn a fresh subagent as the script critic (prompts/script-critic.md) on {w}/source + {w}/script.json, "
                   f"then record it: `uv run python -m spike.cli verdict {w} script --pass|--fail --severity S --issue ...`."),
        "tts": f"NEXT: `uv run python -m spike.cli tts {w}`.",
        "scene": (f"NEXT: write/fix {w}/scene.py following prompts/manim-scene.md, then `uv run python -m spike.cli render {w}`."),
        "visual": (f"NEXT: spawn a fresh subagent as the visual checker (prompts/visual-check.md) on the frames listed above, "
                   f"then record it: `uv run python -m spike.cli verdict {w} visual --pass|--fail --score N --issue ...`."),
        "done": f"NEXT: nothing — sample passed. Final video: {st.get('final_video')}",
        "failed": f"NEXT: nothing — sample failed: {st.get('fail_reason')}",
    }[st["stage"]]


def _fail(work: Path, st: dict, reason: str):
    st["stage"], st["fail_reason"], st["finished_at"] = "failed", reason, time.time()
    _event(st, "failed", reason=reason)
    _save(work, st)
    print(f"FAILED: {reason}\n{_next(st)}")


# --- commands --------------------------------------------------------------------

def cmd_init(a):
    samples = {s["id"]: s for s in json.loads((ROOT / "samples.json").read_text())}
    if a.sample not in samples:
        sys.exit(f"unknown sample {a.sample!r}; known: {', '.join(samples)}")
    sample = samples[a.sample]
    run = Path(a.run) if a.run else ROOT / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")
    work = run / sample["id"]
    if (work / "state.json").exists():
        sys.exit(f"{work} already initialised.\n{_next(_load(work))}")
    src = media.extract_source(sample["pdf"], sample["pages"], work / "source")
    (work / "source" / "notes.txt").write_text(src.text)
    st = {"sample": sample, "work": _rel(work), "stage": "script", "script_round": 0, "fix_round": 0,
          "fix_total": 0, "visual_round": 0, "attempt": 0, "renders": [], "events": [], "started_at": time.time()}
    _event(st, "init")
    _save(work, st)
    print(f"Sample: {sample['title']}")
    if sample.get("focus"):
        print(f"Focus: {sample['focus']}")
    print(f"Source text: {_rel(work / 'source/notes.txt')}")
    print("Page images (read them; most of the content is in the images):")
    for p in src.page_images:
        print(f"  {_rel(p)}")
    print(_next(st))


def cmd_check_script(a):
    work = Path(a.work)
    st = _load(work)
    _stage(st, "script", "critic")
    try:
        script = Script.model_validate_json((work / "script.json").read_text())
    except (FileNotFoundError, ValidationError) as e:
        sys.exit(f"script.json invalid:\n{e}\n{_next(st)}")
    issues = []
    words = sum(len(b.narration.split()) for b in script.beats)
    if not WORDS[0] <= words <= WORDS[1]:
        issues.append(f"narration is {words} words; needs {WORDS[0]}-{WORDS[1]}")
    for i, b in enumerate(script.beats):
        bad = re.findall(r"[`*_#<>{}\[\]()|/\\=@$%^&~—–]", b.narration)
        if bad:
            issues.append(f"beat {i}: narration contains symbols the TTS voice will read literally: {sorted(set(bad))}")
    if len(script.title.split()) > 5:
        issues.append("title is longer than 5 words")
    if issues:
        print("Mechanical checks failed (fix before the critic sees it):")
        print("\n".join(f"- {i}" for i in issues))
        st["stage"] = "script"
        _save(work, st)
        print(_next(st))
        return
    st["stage"] = "critic"
    _event(st, "script_draft", round=st["script_round"] + 1, words=words, beats=len(script.beats))
    _save(work, st)
    print(f"OK: {len(script.beats)} beats, {words} words.")
    print(_next(st))


def cmd_verdict(a):
    work = Path(a.work)
    st = _load(work)
    issues = a.issue or []
    if a.kind == "script":
        _stage(st, "critic")
        st["script_round"] += 1
        _event(st, "script_verdict", round=st["script_round"], passed=a.passed, severity=a.severity, issues=issues)
        (work / f"script.round{st['script_round']}.json").write_text((work / "script.json").read_text())
        if a.passed:
            st["stage"] = "tts"
        elif st["script_round"] >= SCRIPT_ROUNDS:
            return _fail(work, st, f"script critic still failing after {SCRIPT_ROUNDS} rounds: " + "; ".join(issues))
        else:
            st["stage"] = "script"
            print(f"Script round {st['script_round']}/{SCRIPT_ROUNDS} failed. Fix every issue:")
            print("\n".join(f"- {i}" for i in issues))
    else:
        _stage(st, "visual")
        if a.score is None:
            sys.exit("visual verdict needs --score 1-5")
        _event(st, "visual_verdict", attempt=st["attempt"], round=st["visual_round"], passed=a.passed,
               score=a.score, issues=issues)
        st["visual_score"] = a.score
        if a.passed:
            final = work.parent / f"{st['sample']['id']}.mp4"
            shutil.copy(st["renders"][-1]["video"], final)
            st.update(stage="done", final_video=_rel(final), finished_at=time.time())
        elif st["visual_round"] >= VISUAL_ROUNDS:
            return _fail(work, st, f"visual_check still failing after {VISUAL_ROUNDS} revisions: " + "; ".join(issues))
        else:
            st["visual_round"] += 1
            st["fix_round"] = 0  # a visual revision gets a fresh render_fix budget
            st["stage"] = "scene"
            print(f"Visual revision {st['visual_round']}/{VISUAL_ROUNDS}. Apply every fix in scene.py:")
            print("\n".join(f"- {i}" for i in issues))
    _save(work, st)
    print(_next(st))


def cmd_tts(a):
    work = Path(a.work)
    st = _load(work)
    _stage(st, "tts")
    script = Script.model_validate_json((work / "script.json").read_text())
    beats = media.synthesize_beats([b.narration for b in script.beats], work / "audio", [b.pace for b in script.beats])
    total = sum(b["duration"] for b in beats)
    _event(st, "tts", seconds=round(total, 1))
    st["stage"] = "scene"
    _save(work, st)
    print(f"Audio: {total:.1f}s total. Beat durations (b.duration inside `with self.beat(i) as b`):")
    for i, (b, sb) in enumerate(zip(beats, script.beats)):
        print(f"  beat {i}: {b['duration']:.2f}s | visual: {sb.visual}")
    print(_next(st))


def cmd_render(a):
    work = Path(a.work)
    st = _load(work)
    _stage(st, "scene")
    code = (work / "scene.py").read_text()
    n_beats = len(json.loads((work / "audio/beats.json").read_text()))
    st["attempt"] += 1
    att = work / f"attempt{st['attempt']}"
    att.mkdir(parents=True, exist_ok=True)
    (att / "scene.py").write_text(code)

    def fixable(kind: str, detail: str):
        st["fix_round"] += 1
        st["fix_total"] += 1
        _event(st, kind, attempt=st["attempt"], detail=detail[-2000:])
        if st["fix_round"] > FIX_ROUNDS:
            return _fail(work, st, f"render_fix exhausted ({FIX_ROUNDS} fixes): {detail[:400]}")
        _save(work, st)
        print(f"{detail}\n\nrender_fix {st['fix_round']}/{FIX_ROUNDS} used for this visual round.")
        print(_next(st))

    issues = media.lint_scene(code, n_beats)
    if issues:
        return fixable("lint_fail", "LINT FAILED:\n" + "\n".join(f"- {i}" for i in issues))
    r = media.render_scene(code, work / "audio/beats.json", att)
    st["renders"].append({"attempt": st["attempt"], "ok": r.ok, "seconds": round(r.seconds, 1),
                          "video": str(r.video) if r.video else None, "layout_issues": r.layout_issues})
    if not r.ok:
        return fixable("render_fail", f"RENDER FAILED ({r.seconds:.0f}s). Traceback tail:\n{r.error}")
    if r.layout_issues:
        return fixable("layout_fail", "RENDERED, BUT LAYOUT AUDIT FAILED:\n" + "\n".join(f"- {i}" for i in r.layout_issues))
    frames = media.extract_frames(r.video, r.timings, att / "frames")
    script = Script.model_validate_json((work / "script.json").read_text())
    st["stage"] = "visual"
    st["overrun_seconds"] = round(sum(t["overrun"] for t in r.timings), 2)
    _event(st, "render_ok", attempt=st["attempt"], seconds=round(r.seconds, 1))
    _save(work, st)
    print(f"RENDER OK in {r.seconds:.0f}s: {_rel(r.video)} ({media.probe_duration(r.video)}s)")
    if st["overrun_seconds"]:
        print(f"note: animations overran narration by {st['overrun_seconds']}s in total")
    print("Frames for visual_check (settled end of each beat):")
    for i, p in frames:
        print(f"  {_rel(p)}  | beat {i} | narration: {script.beats[i].narration!r} | intended: {script.beats[i].visual!r}")
    print(_next(st))


def cmd_status(a):
    st = _load(Path(a.work))
    print(json.dumps({k: v for k, v in st.items() if k not in ("events", "renders")}, indent=2))
    print(_next(st))


def cmd_report(a):
    run = Path(a.run)
    rows = []
    for sf in sorted(run.glob("*/state.json")):
        st = json.loads(sf.read_text())
        renders = st.get("renders", [])
        end = st.get("finished_at") or time.time()
        rows.append({
            "id": st["sample"]["id"], "status": {"done": "passed"}.get(st["stage"], st["stage"]),
            "fail_reason": st.get("fail_reason", ""), "script_rounds": st["script_round"],
            "scene_attempts": st["attempt"], "render_fix_rounds": st["fix_total"],
            "visual_revisions": st["visual_round"], "renders_ok": sum(r["ok"] for r in renders),
            "render_seconds": round(sum(r["seconds"] for r in renders), 1), "visual_score": st.get("visual_score"),
            "overrun_seconds": st.get("overrun_seconds"), "wall_minutes": round((end - st["started_at"]) / 60, 1),
            "video": st.get("final_video"),
            "duration_s": media.probe_duration(ROOT / st["final_video"]) if st.get("final_video") else None,
        })
    (run / "report.json").write_text(json.dumps(rows, indent=2))
    passed = sum(r["status"] == "passed" for r in rows)
    lines = [f"# 2b manim spike: {run.name}", "",
             f"Pass rate: **{passed}/{len(rows)}**. A pass means the script critic, lint, render, layout audit and visual_check all passed.", "",
             "| sample | status | script rounds | scene attempts | render_fix rounds | visual revisions | visual score | duration s | render s | wall min | human quality (1-5) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['status']} | {r['script_rounds']} | {r['scene_attempts']} | {r['render_fix_rounds']} | "
                     f"{r['visual_revisions']} | {r['visual_score']} | {r['duration_s']} | {r['render_seconds']} | {r['wall_minutes']} | _fill in_ |")
    fails = [r for r in rows if r["fail_reason"]]
    if fails:
        lines += ["", "## Failures", ""] + [f"- **{r['id']}**: {r['fail_reason']}" for r in fails]
    lines += ["", "Each `<sample>/state.json` holds the full event log. `attemptN/` holds each scene version, its render and its frames."]
    (run / "report.md").write_text("\n".join(lines) + "\n")
    print((run / "report.md").read_text())


def main():
    ap = argparse.ArgumentParser(prog="spike.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("sample"); p.add_argument("--run"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("check-script"); p.add_argument("work"); p.set_defaults(fn=cmd_check_script)
    p = sub.add_parser("verdict"); p.add_argument("work"); p.add_argument("kind", choices=["script", "visual"])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pass", dest="passed", action="store_true"); g.add_argument("--fail", dest="passed", action="store_false")
    p.add_argument("--severity", default="none", choices=["none", "low", "medium", "high"])
    p.add_argument("--score", type=int, choices=range(1, 6)); p.add_argument("--issue", action="append")
    p.set_defaults(fn=cmd_verdict)
    p = sub.add_parser("tts"); p.add_argument("work"); p.set_defaults(fn=cmd_tts)
    p = sub.add_parser("render"); p.add_argument("work"); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("status"); p.add_argument("work"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("report"); p.add_argument("run"); p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
