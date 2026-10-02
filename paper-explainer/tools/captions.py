#!/usr/bin/env python3
"""Audio-aligned captions, then remux them into final.mp4.

pe.py render times caption cues by the share of WRITTEN characters, which drifts by 1-2 s when the spoken form is
longer ("Qwen3-4B" is read "Qwen three, four B"). Here cue TEXT is the written form (script.json) and cue TIMING
comes from the audio: sentence boundaries are estimated from the SPOKEN text (tts_script.json, or script.json if
there is none) and snapped to the nearest pause found by ffmpeg silencedetect. Long sentences are split into
<= 84-character chunks. Adapted from the CVW course factory.

  captions.py <workdir> [--no-remux]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SPLIT = re.compile(r"(?<=[.!?])\s+")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).stdout)


def silences(mp3, noise="-38dB", d=0.14):
    err = run(["ffmpeg", "-i", str(mp3), "-af", f"silencedetect=noise={noise}:d={d}", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(starts, ends + [dur(mp3)] * (len(starts) - len(ends))))


def chunk(sentence, max_chars=84):
    out, s = [], sentence.strip()
    while len(s) > max_chars:
        cut = max(s.rfind(", ", 0, max_chars), s.rfind("; ", 0, max_chars), s.rfind(": ", 0, max_chars))
        if cut > max_chars * 0.45:
            cut += 1
        else:
            sp = s.rfind(" ", 0, max_chars)
            cut = sp if sp > 0 else max_chars
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        out.append(s)
    return out


def segment_cues(written, spoken, mp3):
    D = dur(mp3)
    sil = silences(mp3)
    t0 = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    t1 = sil[-1][0] if sil and sil[-1][1] >= D - 0.05 else D
    ws, ss = SPLIT.split(written.strip()), SPLIT.split(spoken.strip())
    if len(ws) != len(ss):
        ss = ws
    lens = [len(x) for x in ss]
    total = sum(lens) or 1
    bounds, acc = [(t0, t0)], 0
    interior = [p for p in sil if p[0] > t0 + 0.1 and p[1] < t1 - 0.05]
    for L in lens[:-1]:
        acc += L
        est = t0 + (t1 - t0) * acc / total
        best = min(interior, key=lambda p: abs((p[0] + p[1]) / 2 - est), default=None)
        if best and abs((best[0] + best[1]) / 2 - est) < 2.2 and best[0] > bounds[-1][1]:
            bounds.append(best)
        else:
            bounds.append((est, est))
    bounds.append((t1, t1))
    cues = []
    for i, w in enumerate(ws):
        a, b = bounds[i][1], bounds[i + 1][0]
        parts = chunk(w)
        tl = sum(len(p) for p in parts)
        t = a
        for p in parts:
            dt = (b - a) * len(p) / tl
            cues.append((t, t + dt, p))
            t += dt
    return cues


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


if __name__ == "__main__":
    W = Path(sys.argv[1]).resolve()
    spoken_file = W / "tts_script.json" if (W / "tts_script.json").exists() else W / "script.json"
    SPOKEN = {x["id"]: x["narration"] for x in json.loads(spoken_file.read_text())["segments"]}
    cues, off = [], 0.0
    for seg in json.loads((W / "script.json").read_text())["segments"]:
        cues += [(a + off, b + off, t) for a, b, t in segment_cues(seg["narration"], SPOKEN[seg["id"]], W / "audio" / f"{seg['id']}.mp3")]
        off += dur(W / "segments" / f"{seg['id']}.mp4")
    fixed = []
    for i, (a, b, t) in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < len(cues) else b + 1
        fixed.append((a, min(max(b, a + 0.6), nxt - 0.02), t))
    (W / "captions.srt").write_text("\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n" for i, (a, b, t) in enumerate(fixed, 1)))
    print(len(fixed), "cues; last ends", srt_time(fixed[-1][1]), "; video", round(off, 2), "s")
    if "--no-remux" not in sys.argv:
        tmp = W / "final_aligned.mp4"
        r = run(["ffmpeg", "-y", "-v", "error", "-i", str(W / "final.mp4"), "-i", str(W / "captions.srt"), "-map", "0:v", "-map", "0:a",
                 "-map", "1:0", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
                 "-movflags", "+faststart", str(tmp)])
        if r.returncode:
            sys.exit(r.stderr)
        tmp.replace(W / "final.mp4")
        print("remuxed captions into final.mp4")
