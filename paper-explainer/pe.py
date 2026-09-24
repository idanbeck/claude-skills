#!/usr/bin/env python3
"""paper-explainer: narrated Manim explainer videos + podcasts for research papers.

Subcommands:
  tts      script.json -> per-segment narration mp3 + durations.json
  render   scene.py + durations -> final.mp4 (segments muxed, concatenated, soft subs)
  podcast  dialogue.json -> episode.mp3 (two voices)
  publish  copy outputs into the vault, write the video note, link the paper note, queue for weekly
  week     list this week's queued papers (JSON) for the weekly compendium
  stitch   concatenate several final.mp4 files into one compendium video
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent
VENV_MANIM = SKILL / ".venv" / "bin" / "manim"
VAULT = Path("/Users/idanbeck/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck")
VIDEOS = VAULT / "Reading" / "Videos"
QUEUE = VIDEOS / "_queue.jsonl"
EL_CONFIG = Path.home() / ".claude" / "skills" / "eleven-labs-skill" / "config.json"

VOICES = {
    "narrator": "JBFqnCBsd6RMkjVDRZzb",  # George - warm storyteller
    "host": "Xb7hH8MSUJpSbSDYk0k2",      # Alice - clear educator
    "guest": "nPczCjzI2devNBz1zQrb",     # Brian - deep, resonant
}
TTS_MODEL = "eleven_multilingual_v2"


def die(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        die(f"command failed: {' '.join(map(str, cmd))}\n{r.stderr[-3000:]}")
    return r.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def api_key():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key and EL_CONFIG.exists():
        key = json.loads(EL_CONFIG.read_text()).get("api_key")
    if not key:
        die("no ElevenLabs API key (eleven-labs-skill config.json or ELEVENLABS_API_KEY)")
    return key


def tts(text, voice, out, prev_text=None, next_text=None):
    body = {"text": text, "model_id": TTS_MODEL,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.15}}
    if prev_text:
        body["previous_text"] = prev_text
    if next_text:
        body["next_text"] = next_text
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps(body).encode(),
        headers={"xi-api-key": api_key(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        die(f"ElevenLabs {e.code}: {e.read().decode()[:500]}")


def cached_tts(text, voice, out, prev_text=None, next_text=None):
    """Re-synthesize only when the text or voice changed (hash sidecar)."""
    h = hashlib.sha256(f"{voice}|{TTS_MODEL}|{text}".encode()).hexdigest()[:16]
    tag = out.with_suffix(".hash")
    if out.exists() and tag.exists() and tag.read_text() == h:
        return False
    tts(text, voice, out, prev_text, next_text)
    tag.write_text(h)
    return True


def resolve_voice(v):
    return VOICES.get(v, v)


# ---------------------------------------------------------------- tts
def cmd_tts(a):
    script = json.loads(Path(a.script).read_text())
    work = Path(a.workdir)
    (work / "audio").mkdir(parents=True, exist_ok=True)
    voice = resolve_voice(script.get("voice", "narrator"))
    segs = script["segments"]
    durations, synthesized, chars = {}, 0, 0
    for i, s in enumerate(segs):
        out = work / "audio" / f"{s['id']}.mp3"
        prev = segs[i - 1]["narration"] if i else None
        nxt = segs[i + 1]["narration"] if i + 1 < len(segs) else None
        if cached_tts(s["narration"], voice, out, prev, nxt):
            synthesized += 1
            chars += len(s["narration"])
        durations[s["id"]] = duration(out)
    (work / "durations.json").write_text(json.dumps(durations, indent=2))
    print(json.dumps({"ok": True, "segments": len(segs), "synthesized": synthesized,
                      "characters_billed": chars, "total_seconds": round(sum(durations.values()), 1),
                      "durations": str(work / "durations.json")}))


# ---------------------------------------------------------------- render
def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def captions(segs, offsets, audio_durs, max_chars=90):
    """One cue per sentence chunk, timed proportionally to characters within each segment."""
    cues = []
    for s in segs:
        chunks = []
        for sent in re.split(r"(?<=[.!?])\s+", s["narration"].strip()):
            while len(sent) > max_chars:
                cut = sent.rfind(" ", 0, max_chars) or max_chars
                chunks.append(sent[:cut])
                sent = sent[cut:].strip()
            if sent:
                chunks.append(sent)
        total = sum(len(c) for c in chunks) or 1
        t = offsets[s["id"]]
        for c in chunks:
            d = audio_durs[s["id"]] * len(c) / total
            cues.append((t, t + d, c))
            t += d
    return "\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(cues, 1))


def cmd_render(a):
    script = json.loads(Path(a.script).read_text())
    work = Path(a.workdir).resolve()
    scene = Path(a.scene).resolve()
    segs = script["segments"]
    durs = json.loads((work / "durations.json").read_text())
    classes = [s["id"].upper() for s in segs]
    if a.only:
        classes = [c for c in classes if c.lower() in a.only.split(",")]
    env = dict(os.environ, PE_DURATIONS=str(work / "durations.json"),
               PYTHONPATH=str(SKILL / "lib") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    res = {"l": ["-ql"], "m": ["-qm"], "h": ["-r", "1920,1080", "--frame_rate", "30"]}[a.quality]
    media = work / "media"
    run([str(VENV_MANIM), "render", *res, "--media_dir", str(media), "--disable_caching",
         str(scene), *classes], env=env, cwd=str(work))
    seg_dir = work / "segments"
    seg_dir.mkdir(exist_ok=True)
    offsets, t = {}, 0.0
    parts = []
    for s in segs:
        cls = s["id"].upper()
        vids = sorted(media.glob(f"videos/{scene.stem}/*/{cls}.mp4"), key=lambda p: p.stat().st_mtime)
        if not vids:
            die(f"no rendered video for {cls}")
        muxed = seg_dir / f"{s['id']}.mp4"
        run(["ffmpeg", "-y", "-i", str(vids[-1]), "-i", str(work / "audio" / f"{s['id']}.mp3"),
             "-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(muxed)])
        offsets[s["id"]] = t
        t += duration(muxed)
        parts.append(muxed)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = work / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    srt = work / "captions.srt"
    srt.write_text(captions(segs, offsets, durs))
    final = work / "final.mp4"
    run(["ffmpeg", "-y", "-i", str(joined), "-i", str(srt), "-map", "0", "-map", "1",
         "-c", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
         "-movflags", "+faststart", str(final)])
    print(json.dumps({"ok": True, "final": str(final), "seconds": round(duration(final), 1),
                      "mb": round(final.stat().st_size / 1e6, 1), "captions": str(srt)}))


# ---------------------------------------------------------------- podcast
def cmd_podcast(a):
    dia = json.loads(Path(a.dialogue).read_text())
    work = Path(a.workdir)
    (work / "pod").mkdir(parents=True, exist_ok=True)
    voices = {k: resolve_voice(v) for k, v in dia.get("voices", {"A": "host", "B": "guest"}).items()}
    lines = dia["lines"]
    files, chars = [], 0
    for i, ln in enumerate(lines):
        out = work / "pod" / f"{i:03}.mp3"
        prev = next((l["text"] for l in reversed(lines[:i]) if l["speaker"] == ln["speaker"]), None)
        if cached_tts(ln["text"], voices[ln["speaker"]], out, prev_text=prev):
            chars += len(ln["text"])
        files.append(out)
    gap = work / "pod" / "gap.mp3"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.28",
         "-c:a", "libmp3lame", "-b:a", "128k", str(gap)])
    lst = work / "pod" / "list.txt"
    lst.write_text("".join(f"file '{f.resolve()}'\nfile '{gap.resolve()}'\n" for f in files))
    out = Path(a.out)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "160k",
         "-metadata", f"title={dia.get('title', out.stem)}", "-metadata", "artist=Zerg Paper Explainer",
         str(out)])
    print(json.dumps({"ok": True, "episode": str(out), "seconds": round(duration(out), 1),
                      "characters_billed": chars}))


# ---------------------------------------------------------------- publish
def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip()


def cmd_publish(a):
    work = Path(a.workdir)
    script = json.loads(Path(a.script).read_text())
    title = safe(a.title or script["title"])
    dest = VIDEOS / title
    dest.mkdir(parents=True, exist_ok=True)
    files = {}
    for src, name in [(work / "final.mp4", f"{title}.mp4"), (work / "captions.srt", f"{title}.srt"),
                      (Path(a.podcast) if a.podcast else None, f"{title} - Podcast.mp3"),
                      (Path(a.scene) if a.scene else None, "scene.py"),
                      (Path(a.script), "script.json"),
                      (Path(a.dialogue) if a.dialogue else None, "dialogue.json")]:
        if src and src.exists():
            shutil.copy2(src, dest / name)
            files[name] = str(dest / name)
    paper_link = ""
    if a.paper_note:
        pn = Path(a.paper_note)
        rel = pn.relative_to(VAULT).with_suffix("") if pn.is_absolute() else Path(a.paper_note).with_suffix("")
        paper_link = f"[[{rel}|{script['title']}]]"
    vid_seconds = duration(work / "final.mp4") if (work / "final.mp4").exists() else 0
    pod_line = f"\n## Podcast\n\n![[Reading/Videos/{title}/{title} - Podcast.mp3]]\n" if a.podcast else ""
    transcript = "\n\n".join(s["narration"] for s in script["segments"])
    note = VIDEOS / f"{title}.md"
    note.write_text(f"""---
type: paper-video
created: {dt.date.today().isoformat()}
paper: "{paper_link}"
seconds: {round(vid_seconds)}
tags: paper-video
---

# {script['title']} — Explainer

**Paper:** {paper_link}
**Length:** {int(vid_seconds // 60)}:{int(vid_seconds % 60):02d} · narrated Manim explainer · captions in the `.srt` / CC track

![[Reading/Videos/{title}/{title}.mp4]]
{pod_line}
## Transcript

{transcript}
""")
    if a.paper_note:
        pn = Path(a.paper_note) if Path(a.paper_note).is_absolute() else VAULT / a.paper_note
        text = pn.read_text()
        link = f"**Explainer video:** [[Reading/Videos/{title}|Video explainer]]"
        if "**Explainer video:**" in text:
            text = re.sub(r"\*\*Explainer video:\*\*.*", link, text, count=1)
        else:
            text = re.sub(r"(\n## My Thoughts)", f"\n{link}\n\\1", text, count=1)
        pn.write_text(text)
    with QUEUE.open("a") as q:
        q.write(json.dumps({"date": dt.date.today().isoformat(), "title": script["title"],
                            "video_note": str(note.relative_to(VAULT)), "paper_note": a.paper_note,
                            "video": files.get(f"{title}.mp4"), "podcast": files.get(f"{title} - Podcast.mp3")}) + "\n")
    print(json.dumps({"ok": True, "note": str(note), "files": files}))


# ---------------------------------------------------------------- weekly helpers
def cmd_week(a):
    since = dt.date.today() - dt.timedelta(days=a.days)
    items = []
    if QUEUE.exists():
        for ln in QUEUE.read_text().splitlines():
            e = json.loads(ln)
            if dt.date.fromisoformat(e["date"]) >= since:
                items.append(e)
    iso = dt.date.today().isocalendar()
    print(json.dumps({"ok": True, "week": f"{iso[0]}-W{iso[1]:02d}", "since": since.isoformat(),
                      "items": items}, indent=2))


def cmd_stitch(a):
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    norm = []
    for i, v in enumerate(a.videos):
        n = work / f"part{i:02}.mp4"
        run(["ffmpeg", "-y", "-i", v, "-map", "0:v", "-map", "0:a", "-vf", "scale=1920:1080,fps=30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-ar", "48000", str(n)])
        norm.append(n)
    lst = work / "stitch.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in norm))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", a.out])
    print(json.dumps({"ok": True, "out": a.out, "seconds": round(duration(a.out), 1)}))


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("tts"); t.add_argument("script"); t.add_argument("--workdir", required=True)
    r = sp.add_parser("render"); r.add_argument("script"); r.add_argument("scene")
    r.add_argument("--workdir", required=True); r.add_argument("--quality", default="h", choices="lmh")
    r.add_argument("--only", help="comma-separated segment ids to (re)render")
    po = sp.add_parser("podcast"); po.add_argument("dialogue"); po.add_argument("--workdir", required=True)
    po.add_argument("--out", required=True)
    pu = sp.add_parser("publish"); pu.add_argument("script"); pu.add_argument("--workdir", required=True)
    pu.add_argument("--title"); pu.add_argument("--paper-note"); pu.add_argument("--podcast")
    pu.add_argument("--scene"); pu.add_argument("--dialogue")
    w = sp.add_parser("week"); w.add_argument("--days", type=int, default=7)
    s = sp.add_parser("stitch"); s.add_argument("videos", nargs="+"); s.add_argument("--out", required=True)
    s.add_argument("--workdir", required=True)
    a = p.parse_args()
    {"tts": cmd_tts, "render": cmd_render, "podcast": cmd_podcast, "publish": cmd_publish,
     "week": cmd_week, "stitch": cmd_stitch}[a.cmd](a)


if __name__ == "__main__":
    main()
