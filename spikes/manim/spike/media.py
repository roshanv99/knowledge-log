"""Everything that isn't an LLM call: source extraction, TTS, lint, render, frames."""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import pymupdf

SPIKE_ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = Path(os.environ.get("NOTES_DIR", Path.home() / "Documents/Notes/Technical Notes"))
SRG_ROOT = Path(os.environ.get("SRG_ROOT", Path.home() / "Projects/Study Reels Generator"))
# Narration engine. Kokoro-82M is the default: a calm, natural narrator that
# runs locally on CPU at ~8x realtime. Piper (SRG's engine) stays available.
TTS_ENGINE = os.environ.get("TTS_ENGINE", "kokoro")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
KOKORO_SPEED = float(os.environ.get("KOKORO_SPEED", "1.0"))
# SRG's Piper voices are reused read-only; SRG's own piper venv isn't (its
# shebang points at an old path), so piper-tts is installed in this venv.
VOICE = Path(os.environ.get("PIPER_VOICE", SRG_ROOT / "content_service/voices/en_US-ryan-high.onnx"))
PIPER_BIN = Path(sys.executable).parent / "piper"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
# SRG tts.py settings, for the same voice character across reel kinds.
NOISE_SCALE, NOISE_W, LENGTH_SCALE = 0.9, 1.1, 0.95
RENDER_TIMEOUT_S = 600


# --- source ------------------------------------------------------------------

@dataclass
class Source:
    text: str
    page_images: list[Path]


def extract_source(pdf: str, pages: list[int], out_dir: Path) -> Source:
    """Text + a PNG per page (the notes are screenshot-heavy, so text alone misses most content)."""
    doc = pymupdf.open(NOTES_DIR / pdf)
    out_dir.mkdir(parents=True, exist_ok=True)
    texts, images = [], []
    for p in pages:
        page = doc[p - 1]
        texts.append(f"--- page {p} ---\n{page.get_text().strip()}")
        img = out_dir / f"page{p}.png"
        page.get_pixmap(dpi=90).save(img)
        images.append(img)
    return Source("\n\n".join(texts), images)


# --- tts -----------------------------------------------------------------------

def _kokoro(text: str, wav: Path, pace: float = 1.0):
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    global _KOKORO
    if "_KOKORO" not in globals():
        # the voice name's first letter is Kokoro's language code (a=US, b=UK)
        _KOKORO = KPipeline(lang_code=KOKORO_VOICE[0], repo_id="hexgrad/Kokoro-82M")
    chunks = [np.asarray(a) for _, _, a in _KOKORO(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED * pace)]
    sf.write(str(wav), np.concatenate(chunks), 24000, subtype="PCM_16")


def _piper(text: str, wav: Path, pace: float = 1.0):
    subprocess.run(
        [str(PIPER_BIN), "-m", str(VOICE), "-c", f"{VOICE}.json", "-f", str(wav),
         "--noise-scale", str(NOISE_SCALE), "--noise-w-scale", str(NOISE_W), "--length-scale", str(LENGTH_SCALE / pace)],
        input=text, text=True, check=True, capture_output=True,
    )


def synthesize_beats(narrations: list[str], out_dir: Path, paces: list[float] | None = None) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    synth = {"kokoro": _kokoro, "piper": _piper}[TTS_ENGINE]
    beats = []
    for i, text in enumerate(narrations):
        wav = out_dir / f"beat{i}.wav"
        synth(text, wav, paces[i] if paces else 1.0)
        with wave.open(str(wav), "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        beats.append({"text": text, "wav": str(wav.resolve()), "duration": round(duration, 3)})
    (out_dir / "beats.json").write_text(json.dumps(beats, indent=2))
    return beats


# --- lint ----------------------------------------------------------------------

FORBIDDEN_NAMES = {
    # need LaTeX, which isn't installed (a plain Text/Code/shape vocabulary is enough for reels)
    "Tex", "MathTex", "SingleStringMathTex", "TexTemplate", "BulletedList", "Title",
    "Integer", "DecimalNumber", "Variable", "LabeledDot", "BraceLabel", "Matrix", "MathTable", "IntegerTable",
    "SVGMobject", "ImageMobject",  # no external assets
    "ThreeDScene", "MovingCameraScene", "ZoomedScene",
}
FORBIDDEN_MODULES = {"os", "subprocess", "sys", "shutil", "pathlib", "requests", "socket"}


def lint_scene(code: str, n_beats: int) -> list[str]:
    """Cheap static checks that catch the usual failure classes before a slow render."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]
    issues = []
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    reel = [c for c in classes if c.name == "Reel"]
    if not reel:
        issues.append("define exactly one scene class named `Reel` that subclasses ReelScene")
    elif not any(getattr(b, "id", None) == "ReelScene" for b in reel[0].bases):
        issues.append("class Reel must subclass ReelScene")
    beat_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            issues.append(f"`{node.id}` is not allowed (no LaTeX / external assets / camera scenes available); use Text/MarkupText and shapes")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
            bad = [m for m in mods if m in FORBIDDEN_MODULES]
            if bad:
                issues.append(f"import of {bad} is not allowed")
        if isinstance(node, ast.keyword) and node.arg == "include_numbers" and getattr(node.value, "value", False):
            issues.append("`include_numbers=True` needs LaTeX; add Text labels next to the ticks instead")
        if isinstance(node, ast.Attribute) and node.attr in {"add_coordinates", "get_axis_labels"}:
            issues.append(f"`{node.attr}` needs LaTeX; use Text labels instead")
        if isinstance(node, ast.Attribute) and node.attr in {"add_sound", "wait_until"}:
            issues.append(f"`self.{node.attr}` is not allowed; audio and timing are handled by `self.beat(i)`")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "beat":
            arg = node.args[0] if node.args else None
            beat_calls.append(arg.value if isinstance(arg, ast.Constant) else None)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "config":
                    issues.append("do not modify `config`; ReelScene sets resolution, frame size and background")
    if beat_calls != list(range(n_beats)):
        issues.append(f"`with self.beat(i)` must be used exactly once per beat with literal indices 0..{n_beats - 1} in order; found {beat_calls}")
    return list(dict.fromkeys(issues))


# --- render --------------------------------------------------------------------

@dataclass
class RenderResult:
    ok: bool
    video: Path | None
    error: str
    seconds: float
    timings: list[dict]
    layout_issues: list[str]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _trim_traceback(stderr: str, limit: int = 60) -> str:
    lines = [_ANSI.sub("", ln).rstrip() for ln in stderr.splitlines()]
    lines = [ln for ln in lines if ln.strip() and not re.match(r"^\s*[│╭╰─]+\s*$", ln)]
    return "\n".join(lines[-limit:])


def render_scene(code: str, beats_json: Path, work: Path) -> RenderResult:
    work, beats_json = work.resolve(), beats_json.resolve()
    work.mkdir(parents=True, exist_ok=True)
    scene = work / "scene.py"
    scene.write_text(code)
    timing = work / "timing.json"
    timing.unlink(missing_ok=True)
    env = {**os.environ, "REEL_BEATS": str(beats_json), "REEL_TIMING_OUT": str(timing), "PYTHONPATH": str(SPIKE_ROOT)}
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "manim", "render", "-qh", "--progress_bar", "none", "--disable_caching",
             "--media_dir", str(work / "media"), "-o", "reel", str(scene), "Reel"],
            env=env, capture_output=True, text=True, timeout=RENDER_TIMEOUT_S, cwd=work,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(False, None, f"render timed out after {RENDER_TIMEOUT_S}s (too many objects or animations?)", time.monotonic() - t0, [], [])
    secs = time.monotonic() - t0
    videos = list((work / "media").glob("videos/**/reel.mp4"))
    if proc.returncode != 0 or not videos or not timing.exists():
        return RenderResult(False, None, _trim_traceback(proc.stderr + proc.stdout), secs, [], [])
    data = json.loads(timing.read_text())
    return RenderResult(True, videos[0], "", secs, data["timings"], data["layout_issues"])


# --- frames --------------------------------------------------------------------

def extract_frames(video: Path, timings: list[dict], out_dir: Path, n: int = 3) -> list[tuple[int, Path]]:
    """One frame at the settled end of n beats (first, middle, last): the moment
    each beat's diagram is fully built, which is where overlaps and clutter show."""
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = sorted({0, len(timings) // 2, len(timings) - 1}) if len(timings) >= n else list(range(len(timings)))
    frames = []
    for i in idx:
        t = max(0.0, timings[i]["end"] - 0.15)
        out = out_dir / f"beat{i}.png"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=540:960", str(out)], check=True)
        frames.append((i, out))
    return frames


def probe_duration(video: Path) -> float:
    out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(video)], capture_output=True, text=True)
    return round(float(out.stdout.strip() or 0), 2)
