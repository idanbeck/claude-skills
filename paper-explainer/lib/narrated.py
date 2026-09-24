"""Base scene + visual vocabulary for narrated paper explainers.

Each Manim scene class `S01`, `S02`, ... maps to narration segment `s01`, `s02`, ...
The scene is padded to its narration length, so audio and video stay in sync
when segments are concatenated. Use `self.until(frac)` to land a visual beat at
a fraction of the way through the narration.
"""
import json
import os

from manim import *  # noqa: F401,F403

BG = "#0e1117"
FG = "#e6e6e6"
MUTED = "#7d8590"
BLUE = "#58c4dd"      # 3b1b blue
TEAL = "#5cd0b3"
YELLOW = "#f4d35e"
RED = "#fc6255"
GREEN = "#83c167"
PURPLE = "#9a72ac"
FONT = "Helvetica Neue"

_DURS = None


def durations():
    global _DURS
    if _DURS is None:
        path = os.environ.get("PE_DURATIONS")
        _DURS = json.load(open(path)) if path and os.path.exists(path) else {}
    return _DURS


config.background_color = BG


class NarratedScene(Scene):
    tail = 0.35

    @property
    def seg(self):
        return type(self).__name__.lower()

    @property
    def narration(self):
        return durations().get(self.seg, 6.0)

    def now(self):
        return self.renderer.time

    def until(self, frac):
        """Wait until `frac` of this segment's narration has elapsed (no-op if already past)."""
        target = self.narration * frac
        if target - self.now() > 1 / 60:
            self.wait(target - self.now())

    def tear_down(self):
        remaining = self.narration + self.tail - self.now()
        if remaining > 1 / 60:
            self.wait(remaining)


def T(text, size=36, color=FG, weight=NORMAL, **kw):
    return Text(text, font=FONT, font_size=size, color=color, weight=weight, **kw)


def pill(label, color=TEAL, size=26, pad=0.22, fill=0.12):
    t = T(label, size=size, color=FG)
    box = RoundedRectangle(corner_radius=0.12, width=t.width + 2 * pad, height=t.height + 2 * pad,
                           stroke_color=color, stroke_width=2, fill_color=color, fill_opacity=fill)
    return VGroup(box, t)


def title_card(title, subtitle=None, tag=None):
    parts = [T(title, size=54, weight=BOLD)]
    if subtitle:
        parts.append(T(subtitle, size=28, color=MUTED))
    g = VGroup(*parts).arrange(DOWN, buff=0.35)
    if tag:
        g = VGroup(T(tag, size=20, color=BLUE), g).arrange(DOWN, buff=0.5)
    return g


def bar_chart(values, labels, colors=None, max_value=None, height=3.5, width=0.7, buff=0.45, fmt="{:.1f}"):
    """Simple labeled vertical bars. Returns (group, bars) so bars can be grown in."""
    max_value = max_value or max(values)
    colors = colors or [BLUE] * len(values)
    bars = VGroup(*[Rectangle(width=width, height=max(0.02, height * v / max_value), stroke_width=0,
                              fill_color=c, fill_opacity=0.9) for v, c in zip(values, colors)])
    bars.arrange(RIGHT, buff=buff, aligned_edge=DOWN)
    cols = []
    for b, v, lab, c in zip(bars, values, labels, colors):
        val = T(fmt.format(v), size=22, color=c).next_to(b, UP, buff=0.12)
        lab_t = T(lab, size=18, color=MUTED).next_to(b, DOWN, buff=0.15)
        cols.append(VGroup(b, val, lab_t))
    return VGroup(*cols), list(bars)
