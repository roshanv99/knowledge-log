"""`kl` command line. It makes no LLM calls: the `mcq-generation` skill (a Claude Code session)
does the reading, writing and reviewing, and this CLI does everything else.

    kl mcq wanted                           what `start` would claim next, without claiming it
    kl mcq start [--document NAME]          claim work from the API; prints the first NEXT: step
    kl mcq submit notes|draft|critique FILE  hand in an LLM step's JSON; prints the next step
    kl mcq status                           where the run is (also renews the task's lease)
    kl mcq fail "why" [--no-retry]          give up on the current task
    kl mcq stop [--reason usage_limit]      end the run
    kl reel wanted|start|status|render|fail|stop   the manim reel engine (needs the `reels` extra)
    kl reel submit script|script-review|visual FILE
    kl runner poll [--dry-run]              launchd: start a session per kind only if work is wanted
                                             (also reports the notes folder — see kl notes sync)
    kl notes sync                           report every PDF under KL_NOTES_DIR to the app
    kl docs / kl status                     what's selected in Manage notes / pipeline activity
"""

import json
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from kl import notes_sync, runner
from kl.api import ApiError, HttpApi
from kl.config import Settings, load_settings
from kl.engine import Engine, EngineError

app = typer.Typer(no_args_is_help=True, help="knowledge-log content pipeline")
mcq = typer.Typer(no_args_is_help=True, help="The MCQ step engine")
reel = typer.Typer(no_args_is_help=True, help="The manim reel step engine")
runner_app = typer.Typer(no_args_is_help=True, help="The launchd runner")
notes_app = typer.Typer(no_args_is_help=True, help="The notes folder")
app.add_typer(mcq, name="mcq")
app.add_typer(reel, name="reel")
app.add_typer(runner_app, name="runner")
app.add_typer(notes_app, name="notes")


class Step(str, Enum):
    notes = "notes"
    draft = "draft"
    critique = "critique"


class ReelStep(str, Enum):
    notes = "notes"
    script = "script"
    script_review = "script-review"
    visual = "visual"


def _api(s=None) -> HttpApi:
    s = s or load_settings()
    return HttpApi(s.api_base, s.runner_token)


def _engine() -> Engine:
    s = load_settings()
    return Engine(s, _api(s), s.work_dir)


def _reel_engine():
    from kl.reels.engine import ReelEngine
    s = load_settings()
    return ReelEngine(s, _api(s), s.work_dir)


def _sync_notes(s: Settings) -> str:
    """Report every PDF under KL_NOTES_DIR so the app's Manage Notes reflects what's really on
    disk (content/notes.py) — the app itself can no longer see this once deployed away from
    this folder. Never raises: a sync failure shouldn't stop `runner poll` from still checking
    whether work is wanted."""
    try:
        entries = notes_sync.scan(s.notes_dir)
        result = _api(s).sync_notes(entries, str(s.notes_dir))
        return (f"notes: synced {len(entries)} PDF(s) "
                f"({result['available']} available, {result['went_unavailable']} no longer found).")
    except ApiError as e:
        return f"notes: sync failed ({e}) — continuing without it."


def _run(action) -> None:
    try:
        typer.echo(action())
    except (EngineError, ApiError) as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(1) from None


def _wanted(kind: str) -> str:
    """What `start` would claim next, without claiming it — so a driver (notably a cloud
    routine, which has no local copy of the notes folder) can fetch the right PDF first."""
    want = _api().wanted(kind)
    return json.dumps(want, indent=2) if want else f"{kind}: nothing wanted."


def _document_id(name: str) -> int:
    notes = _api().notes()["notes"]
    matches = [n for n in notes if name.lower() in n["filename"].lower()]
    if len(matches) != 1:
        found = ", ".join(n["filename"] for n in matches) or "none"
        raise EngineError(f"'{name}' matched {len(matches)} PDFs in Manage notes ({found}).")
    return matches[0]["id"]


@mcq.command("wanted")
def mcq_wanted() -> None:
    """What `start` would claim next, without claiming it (document, folder, pages)."""
    _run(lambda: _wanted("quiz"))


@mcq.command("start")
def mcq_start(
    document: Annotated[str | None, typer.Option(help="Only this PDF (part of its file name)")] = None,
) -> None:
    """Start (or resume) a run. Manage notes decides which PDFs and pages."""
    _run(lambda: _engine().start(_document_id(document) if document else None))


@mcq.command("submit")
def mcq_submit(step: Step, file: Path) -> None:
    """Hand in the JSON for the current step."""
    engine = _engine()
    handler = {Step.notes: engine.submit_notes, Step.draft: engine.submit_draft,
               Step.critique: engine.submit_critique}[step]
    _run(lambda: handler(file))


@mcq.command("status")
def mcq_status() -> None:
    """Show the current step and renew the task's lease."""
    _run(lambda: _engine().status())


@mcq.command("fail")
def mcq_fail(
    error: str,
    no_retry: Annotated[bool, typer.Option("--no-retry", help="Don't retry automatically")] = False,
) -> None:
    """Give up on the current task and move on."""
    _run(lambda: _engine().fail(error, retryable=not no_retry))


@mcq.command("stop")
def mcq_stop(reason: Annotated[str, typer.Option(help="Stop reason to record")] = "stopped") -> None:
    """End the run. An unfinished task goes straight back to the queue."""
    _run(lambda: _engine().stop(reason))


@mcq.command("drive")
def mcq_drive(
    api: Annotated[bool, typer.Option("--api", help="Answer the LLM steps with the Messages API (ANTHROPIC_API_KEY)")] = False,
    document: Annotated[str | None, typer.Option(help="Only this PDF (part of its file name)")] = None,
    model: Annotated[str | None, typer.Option(help="Model (default claude-opus-5, or KL_API_MODEL)")] = None,
) -> None:
    """Driver B: run the MCQ engine end to end without Claude Code. Needs the `api` extra. Untested live."""
    if not api:
        raise typer.BadParameter("Only --api is supported; in Claude Code, use the /mcq-generation skill instead.")
    import os

    import anthropic

    from kl.drivers.api import DEFAULT_MODEL, ApiDriver

    s = load_settings()
    # Its own work dir, so it never touches a Claude Code session's state.
    engine = Engine(s, _api(s), s.work_dir / "api")
    driver = ApiDriver(engine, anthropic.Anthropic(), model or os.environ.get("KL_API_MODEL", DEFAULT_MODEL))
    _run(lambda: driver.run(_document_id(document) if document else None))


@reel.command("wanted")
def reel_wanted() -> None:
    """What `start` would claim next, without claiming it (document, folder, pages)."""
    _run(lambda: _wanted("reel"))


@reel.command("start")
def reel_start(
    document: Annotated[str | None, typer.Option(help="Only this PDF (part of its file name)")] = None,
) -> None:
    """Start (or resume) a reel run. Manage notes decides which PDFs and pages."""
    _run(lambda: _reel_engine().start(_document_id(document) if document else None))


@reel.command("submit")
def reel_submit(step: ReelStep, file: Path) -> None:
    """Hand in the JSON for the current step."""
    engine = _reel_engine()
    handler = {ReelStep.notes: engine.submit_notes, ReelStep.script: engine.submit_script,
               ReelStep.script_review: engine.submit_script_review, ReelStep.visual: engine.submit_visual}[step]
    _run(lambda: handler(file))


@reel.command("render")
def reel_render() -> None:
    """Lint, render and audit the current scene, then extract frames for the visual review."""
    _run(lambda: _reel_engine().render())


@reel.command("status")
def reel_status() -> None:
    """Show the current step and renew the task's lease."""
    _run(lambda: _reel_engine().status())


@reel.command("fail")
def reel_fail(
    error: str,
    no_retry: Annotated[bool, typer.Option("--no-retry", help="Don't retry automatically")] = False,
) -> None:
    """Give up on the current task and move on."""
    _run(lambda: _reel_engine().fail(error, retryable=not no_retry))


@reel.command("stop")
def reel_stop(reason: Annotated[str, typer.Option(help="Stop reason to record")] = "stopped") -> None:
    """End the run. An unfinished task goes straight back to the queue."""
    _run(lambda: _reel_engine().stop(reason))


@runner_app.command("poll")
def runner_poll(
    kind: Annotated[list[str] | None, typer.Option(help="Content kinds to check (default: quiz and reel)")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Only say what would start")] = False,
) -> None:
    """Start a Claude Code session per kind the app wants a run for. Costs nothing when idle."""
    s = load_settings()
    kinds = kind or list(runner.KINDS)
    _run(lambda: "\n".join([_sync_notes(s)] + [runner.poll(s, _api(s), k, dry_run=dry_run) for k in kinds]))


@notes_app.command("sync")
def notes_sync_cmd() -> None:
    """Report every PDF under KL_NOTES_DIR to the app (also runs automatically on every
    `runner poll`; this is for triggering it manually)."""
    _run(lambda: _sync_notes(load_settings()))


@app.command()
def docs() -> None:
    """PDFs in Manage notes, with their scope and progress."""
    def show() -> str:
        lines = []
        for n in _api().notes()["notes"]:
            scope = n["scope"]
            on = "on " if scope["selected"] and n["available"] else "off"
            lines.append(f"[{on}] {n['folder']}/{n['filename']}: pages {scope['page_from']}-{scope['page_to']}, "
                         f"questions up to page {n['processed_to']} of {n['page_count']}, "
                         f"{n['questions']['total']} questions")
        return "\n".join(lines) or "No PDFs in the notes folder."
    _run(show)


@app.command()
def status() -> None:
    """Active runs, recent runs, failed tasks and runners."""
    def show() -> str:
        st = _api().status()
        active = [
            f"  run {r['id']} ({r['kind']}, {r['runner']}): {r['tasks_done']} tasks, {r['questions_made']} questions"
            + "".join(f"\n    task {t['id']}: {t['document']} p{t['pages'][0]}-{t['pages'][1]} "
                      f"{t['stage'] or ''} {t['detail'] or ''}" for t in r["tasks"])
            for r in st["active_runs"]]
        lines = ["Active runs:", *active] if active else ["Active runs: none"]
        lines += ["Recent runs:"] + [
            f"  run {r['id']} ({r['kind']}, {r['runner']}): {r['stop_reason']}, {r['tasks_done']} tasks, "
            + (f"{r['reels_made']} reels" if r["kind"] == "reel" else f"{r['questions_made']} questions")
            for r in st["recent_runs"][:5]]
        if st["failed_tasks"]:
            lines += ["Failed tasks:"] + [f"  task {t['id']}: {t['document']} p{t['pages'][0]}-{t['pages'][1]}: "
                                          f"{t['error']}" for t in st["failed_tasks"]]
        if st["open_requests"]:
            lines.append(f"Waiting requests: {', '.join(r['kind'] for r in st['open_requests'])}")
        return "\n".join(lines)
    _run(show)
