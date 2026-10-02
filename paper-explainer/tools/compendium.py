#!/usr/bin/env python3
"""Weekly compendium: intro card + every explainer published in the window -> one shareable 1080p30 mp4.

Reads Reading/Videos/_queue.jsonl (one entry per title, latest wins), renders a title card listing the papers,
re-encodes and concatenates the videos, merges their SRTs with time offsets, embeds chapter markers, copies the
individual videos, and writes Links.md (chapter timestamps + the links from each paper note's **Source:** line).

  compendium.py [--days 7] [--out ~/Downloads/Paper-Explainers-<YYYY-Www>]

Also copies the compendium mp4 + srt to Reading/Videos/Weekly/<YYYY-Www> - Paper Compendium.{mp4,srt} for the
weekly vault note. Prints a JSON summary (paths, length, chapters).
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VAULT = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck"
QUEUE = VAULT / "Reading/Videos/_queue.jsonl"
VENV_MANIM = SKILL / ".venv/bin/manim"
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-vf", "scale=1920:1080",
       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]

INTRO = '''from narrated import *
import json, os
D = json.load(open(os.environ["PE_INTRO"]))
class Intro(Scene):
    def construct(self):
        head = VGroup(T("PAPER EXPLAINERS", size=22, color=BLUE, weight=BOLD), T("This week in papers", size=56, weight=BOLD),
                      T(D["subtitle"], size=26, color=MUTED)).arrange(DOWN, buff=0.28).to_edge(UP, buff=0.7)
        rows = VGroup()
        for i, p in enumerate(D["titles"]):
            n = T(str(i + 1), size=26, color=YELLOW, weight=BOLD).move_to(ORIGIN, aligned_edge=RIGHT)
            t = T(p, size=26).next_to(ORIGIN, RIGHT, buff=0.35)
            t.match_y(n)
            rows.add(VGroup(n, t))
        rows.arrange(DOWN, buff=0.3)
        for r in rows[1:]:
            r.shift(RIGHT * (rows[0][1].get_left()[0] - r[1].get_left()[0]))
        fit(rows, max_w=12.4, max_h=7.6 - head.height - 1.6)
        rows.next_to(head, DOWN, buff=0.6)
        self.play(FadeIn(head, shift=0.2 * UP), run_time=1.0)
        self.play(LaggedStart(*[FadeIn(r, shift=0.15 * RIGHT) for r in rows], lag_ratio=0.25), run_time=2.2)
        self.wait(3.3)
        self.play(FadeOut(VGroup(head, rows)), run_time=0.5)
'''


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f"{' '.join(map(str, cmd[:3]))}...\n{r.stderr[-2000:]}")
    return r


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).stdout)


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        a, b = lines[1].split(" --> ")
        f = lambda x: sum(float(p) * m for p, m in zip(x.replace(",", ".").split(":"), (3600, 60, 1)))
        cues.append((f(a), f(b), "\n".join(lines[2:])))
    return cues


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def hms(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def source_links(paper_note):
    p = VAULT / paper_note
    if not p.exists():
        return []
    for ln in p.read_text().splitlines():
        if ln.startswith("**Source:**"):
            return re.findall(r"\]\((https?://[^)\s]+)\)", ln)
    return []


ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=7)
ap.add_argument("--out")
a = ap.parse_args()
today = dt.date.today()
since = today - dt.timedelta(days=a.days)
latest = {}
for ln in QUEUE.read_text().splitlines():
    e = json.loads(ln)
    if dt.date.fromisoformat(e["date"]) >= since:
        latest[e["title"]] = e
items = sorted(latest.values(), key=lambda e: e["date"])
if not items:
    print(json.dumps({"ok": True, "items": 0}))
    raise SystemExit
iso = today.isocalendar()
week = f"{iso[0]}-W{iso[1]:02d}"
OUT = Path(os.path.expanduser(a.out)) if a.out else Path.home() / "Downloads" / f"Paper-Explainers-{week}"
WORK = Path.home() / "paper-videos" / f"weekly-{week}"
(WORK / "parts").mkdir(parents=True, exist_ok=True)
(OUT / "Individual videos").mkdir(parents=True, exist_ok=True)
first = dt.date.fromisoformat(items[0]["date"])
subtitle = f"{first:%b} {first.day} – {today:%b} {today.day}, {today.year}  ·  {len(items)} narrated explainers"

# intro card
(WORK / "intro.json").write_text(json.dumps({"titles": [e["title"] for e in items], "subtitle": subtitle}))
(WORK / "intro.py").write_text(INTRO)
env = dict(os.environ, PE_INTRO=str(WORK / "intro.json"), PYTHONPATH=str(SKILL / "lib"))
run([str(VENV_MANIM), "render", "-r", "1920,1080", "--frame_rate", "30", "--media_dir", str(WORK / "media"), "--disable_caching",
     str(WORK / "intro.py"), "Intro"], env=env, cwd=str(WORK))
intro = WORK / "parts" / "00_intro.mp4"
run(["ffmpeg", "-y", "-v", "error", "-i", str(WORK / "media/videos/intro/1080p30/Intro.mp4"), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
     "-shortest", "-map", "0:v", "-map", "1:a", *ENC, str(intro)])

parts, cues, chapters, t = [intro], [], [], dur(intro)
for i, e in enumerate(items, 1):
    src = Path(e["video"])
    srt = src.with_suffix(".srt")
    p = WORK / "parts" / f"{i:02}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v", "-map", "0:a", *ENC, str(p)])
    d = dur(p)
    chapters.append((t, t + d, e["title"], source_links(e.get("paper_note", ""))))
    if srt.exists():
        cues += [(x + t, y + t, txt) for x, y, txt in parse_srt(srt.read_text())]
        shutil.copy(srt, OUT / "Individual videos" / f"{i}. {src.stem}.srt")
    shutil.copy(src, OUT / "Individual videos" / f"{i}. {src.name}")
    parts.append(p)
    t += d
(WORK / "parts" / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
joined = WORK / "parts" / "joined.mp4"
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(WORK / "parts" / "list.txt"), "-c", "copy", str(joined)])
name = f"Paper Explainers - Week of {first.isoformat()}"
srt_out = OUT / f"{name}.srt"
srt_out.write_text("\n".join(f"{k}\n{srt_time(x)} --> {srt_time(y)}\n{txt}\n" for k, (x, y, txt) in enumerate(cues, 1)))
meta = WORK / "parts" / "chapters.txt"
meta.write_text(f";FFMETADATA1\ntitle=Paper Explainers: {subtitle.split('  ·')[0]}\n" +
                "".join(f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(x * 1000)}\nEND={int(y * 1000)}\ntitle={ti}\n" for x, y, ti, _ in chapters))
mp4_out = OUT / f"{name}.mp4"
run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-i", str(srt_out), "-i", str(meta), "-map", "0:v", "-map", "0:a", "-map", "1:0",
     "-map_metadata", "2", "-map_chapters", "2", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
     "-movflags", "+faststart", str(mp4_out)])
total = dur(mp4_out)
lines = [f"# Paper Explainers: {subtitle.split('  ·')[0]}", "",
         f"Compendium: `{mp4_out.name}` ({hms(total)}, 1080p, soft English captions, chapter markers). "
         "Each video is also in `Individual videos/` with its own captions.", "", "## Papers and chapter times", ""]
for k, (x, y, ti, links) in enumerate(chapters, 1):
    lines.append(f"{k}. **{ti}**")
    lines.append(f"   - Chapter: {hms(x)}–{hms(y)} · video length {hms(y - x)}")
    lines += [f"   - {u}" for u in links]
lines += ["", "## Plain list (copy-paste)", ""]
lines += [f"{hms(x)} {ti}: {links[0] if links else ''}".rstrip(": ") for x, y, ti, links in chapters]
(OUT / "Links.md").write_text("\n".join(lines) + "\n")
weekly = VAULT / "Reading/Videos/Weekly"
weekly.mkdir(parents=True, exist_ok=True)
vault_mp4 = weekly / f"{week} - Paper Compendium.mp4"
shutil.copy(mp4_out, vault_mp4)
shutil.copy(srt_out, vault_mp4.with_suffix(".srt"))
print(json.dumps({"ok": True, "week": week, "out_dir": str(OUT), "compendium": str(mp4_out), "vault_copy": str(vault_mp4),
                  "seconds": round(total, 1), "chapters": [(hms(x), ti) for x, _, ti, _ in chapters]}, indent=1))
