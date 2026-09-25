"""Runtime base class every generated reel scene subclasses (promoted from spikes/manim).

Generated code only has to draw and animate; this module owns everything the
pipeline needs to stay deterministic:

- portrait 1080x1920 @ 30fps with a 9x16 frame, so 1 unit = 120px;
- ``with self.beat(i) as b:`` plays beat i's pre-synthesised narration WAV and pads
  the beat with a wait so it lasts at least as long as its audio (the same idea
  as manim-voiceover's ``with self.voiceover(...)`` without the dependency);
- a layout audit at the end of every beat: anything outside the safe area or
  text overlapping other text is recorded, and the pipeline treats it as a
  render failure to fix;
- timings + audit written to ``$REEL_TIMING_OUT`` so frames can be sampled at
  beat ends and overruns reported.

Beats come from ``$REEL_BEATS`` (JSON list of {text, wav, duration}).
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass

from manim import (
    MarkupText,
    Mobject,
    Paragraph,
    RoundedRectangle,
    Scene,
    Text,
    ValueTracker,
    VGroup,
    VMobject,
    config,
)

config.pixel_width = 1080
config.pixel_height = 1920
config.frame_width = 9.0
config.frame_height = 16.0
config.frame_rate = 30
config.background_color = "#0f1117"

# Pango otherwise falls back to a serif face on macOS.
FONT = os.environ.get("REEL_FONT", "Helvetica Neue")
for _cls in (Text, MarkupText, Paragraph):
    _cls.set_default(font=FONT)

# Reels UI covers the top (account/header) and bottom (caption, buttons) of the
# screen, so content must stay inside this box. The right edge also holds the
# like/comment/share rail on Instagram; 3.6 proved too generous (visual_check
# flagged right-edge crowding in 5/7 reels on 2026-09-24), so it ends at ~85% width.
SAFE_LEFT, SAFE_RIGHT = -4.0, 3.2
SAFE_BOTTOM, SAFE_TOP = -5.6, 6.4
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT
SAFE_HEIGHT = SAFE_TOP - SAFE_BOTTOM
SAFE_CENTER_X = (SAFE_LEFT + SAFE_RIGHT) / 2
# Vertical bands: title on top, one caption line at the bottom, and the main
# diagram centred in the stage between them (top-heavy frames were the most
# common visual_check complaint).
TITLE_Y = 5.6
CAPTION_Y = -4.9
STAGE_TOP, STAGE_BOTTOM = 4.8, -4.2

BEAT_GAP = 0.25  # breathing room after each beat's audio
_TOL = 0.05


@dataclass
class BeatInfo:
    index: int
    text: str
    duration: float  # seconds of narration audio for this beat


def _text_leaves(root: Mobject):
    for m in root.get_family():
        if isinstance(m, (Text, MarkupText, Paragraph)) and m.width > 0:
            yield m


def _overlap(a: Mobject, b: Mobject) -> float:
    w = min(a.get_right()[0], b.get_right()[0]) - max(a.get_left()[0], b.get_left()[0])
    h = min(a.get_top()[1], b.get_top()[1]) - max(a.get_bottom()[1], b.get_bottom()[1])
    return w * h if w > _TOL and h > _TOL else 0.0


def _invisible(m: Mobject) -> bool:
    if isinstance(m, ValueTracker):
        return True  # holds a number in its points; never drawn
    if not isinstance(m, VMobject):
        return False
    return m.get_fill_opacity() == 0 and m.get_stroke_opacity() == 0


def labeled_box(label: str, color, font_size: int = 34, buff: float = 0.3,
                min_width: float = 0.0, fill_opacity: float = 0.2) -> VGroup:
    """A rounded box sized from its (centred, possibly multi-line) label, so text
    never touches the border. Returns VGroup(box, text)."""
    text = Paragraph(*label.split("\n"), font_size=font_size, alignment="center", line_spacing=0.8)
    box = RoundedRectangle(width=max(text.width + 2 * buff, min_width), height=text.height + 2 * buff,
                           corner_radius=0.2, color=color, fill_color=color, fill_opacity=fill_opacity)
    return VGroup(box, text.move_to(box))


class ReelScene(Scene):
    def setup(self):
        with open(os.environ["REEL_BEATS"]) as f:
            raw = json.load(f)
        self._beats = [BeatInfo(i, b["text"], b["duration"]) for i, b in enumerate(raw)]
        self._wavs = [b["wav"] for b in raw]
        self._next_beat = 0
        self._timings: list[dict] = []
        self._layout_issues: list[str] = []

    # --- helpers generated code may use -------------------------------------
    @property
    def beats(self) -> list[BeatInfo]:
        return self._beats

    def fit_safe(self, mob: Mobject, max_width: float = SAFE_WIDTH, max_height: float = SAFE_HEIGHT) -> Mobject:
        """Scale ``mob`` down (never up) so it fits the given box."""
        if mob.width > max_width:
            mob.scale_to_fit_width(max_width)
        if mob.height > max_height:
            mob.scale_to_fit_height(max_height)
        return mob

    def place_stage(self, mob: Mobject, max_width: float = SAFE_WIDTH - 0.4) -> Mobject:
        """Fit ``mob`` into the stage band and centre it there (horizontally on the
        safe area, vertically between title and caption)."""
        self.fit_safe(mob, max_width=max_width, max_height=STAGE_TOP - STAGE_BOTTOM)
        return mob.move_to([SAFE_CENTER_X, (STAGE_TOP + STAGE_BOTTOM) / 2, 0])

    @contextmanager
    def beat(self, i: int):
        if i != self._next_beat:
            raise RuntimeError(f"beats must be played in order: expected beat({self._next_beat}), got beat({i})")
        b = self._beats[i]
        start = self.renderer.time
        self.add_sound(self._wavs[i])
        yield b
        elapsed = self.renderer.time - start
        pad = b.duration + BEAT_GAP - elapsed
        if pad > 0:
            self.wait(pad)
        self._audit(i)
        self._timings.append({
            "beat": i,
            "start": round(start, 3),
            "end": round(self.renderer.time, 3),
            "audio": round(b.duration, 3),
            "overrun": round(max(0.0, elapsed - b.duration - BEAT_GAP), 3),
        })
        self._next_beat += 1

    # --- audit ---------------------------------------------------------------
    def _audit(self, i: int):
        for m in self.mobjects:
            for leaf in m.get_family():
                if not leaf.has_points() or _invisible(leaf):
                    continue
                if (leaf.get_left()[0] < SAFE_LEFT - _TOL or leaf.get_right()[0] > SAFE_RIGHT + _TOL
                        or leaf.get_bottom()[1] < SAFE_BOTTOM - _TOL or leaf.get_top()[1] > SAFE_TOP + _TOL):
                    name = type(m).__name__
                    self._layout_issues.append(
                        f"end of beat {i}: a {name} extends outside the safe area "
                        f"(x {leaf.get_left()[0]:.2f}..{leaf.get_right()[0]:.2f}, "
                        f"y {leaf.get_bottom()[1]:.2f}..{leaf.get_top()[1]:.2f}; "
                        f"allowed x {SAFE_LEFT}..{SAFE_RIGHT}, y {SAFE_BOTTOM}..{SAFE_TOP})")
                    break
        texts = [t for m in self.mobjects for t in _text_leaves(m) if not _invisible(t)]
        seen = set()
        for a_i, a in enumerate(texts):
            for b in texts[a_i + 1:]:
                if a in b.get_family() or b in a.get_family():
                    continue
                if _overlap(a, b) > 0.02:
                    key = (getattr(a, "text", "?"), getattr(b, "text", "?"))
                    if key in seen:
                        continue
                    seen.add(key)
                    self._layout_issues.append(f"end of beat {i}: text {key[0]!r} overlaps text {key[1]!r}")

    def tear_down(self):
        if self._next_beat != len(self._beats):
            raise RuntimeError(f"only {self._next_beat} of {len(self._beats)} beats were played; every beat must be played once, in order")
        out = os.environ.get("REEL_TIMING_OUT")
        if out:
            with open(out, "w") as f:
                json.dump({"timings": self._timings, "layout_issues": self._layout_issues}, f, indent=2)
