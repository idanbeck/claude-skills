#!/usr/bin/env python3
"""Spoken-number check: transcribe what ElevenLabs actually said and diff its numbers against the text sent.

ElevenLabs misreads ~3% of segments silently (comma numbers like 5,120 -> "5,020"; letter+digit names like
"V four" -> "five four"). Whisper (local, free) transcribes every narration segment (audio/sNN.mp3) and, with
--podcast, every podcast line (pod/NNN.mp3). Flags go to qa/audio_numcheck.json. Whisper alone gives ~50% false
flags (it drops phrases, merges "3.5, 9B" into "3.59b", hears "too" as "2"), so re-check each flag with
ElevenLabs Scribe before re-voicing:  python3 ~/.claude/skills/voice-mode/voice_mode.py stt <mp3>

  audiocheck.py <workdir> [--podcast]
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from numcheck import nums  # noqa: E402

MODEL = Path.home() / "paper-videos/gpu-course/tools/models/ggml-medium.en.bin"
W = Path(sys.argv[1]).resolve()
STT = W / "qa" / "stt"
STT.mkdir(parents=True, exist_ok=True)


def transcribe(mp3):
    out = STT / (mp3.parent.name + "_" + mp3.stem)
    txt = out.with_suffix(".txt")
    if not txt.exists() or txt.stat().st_mtime < mp3.stat().st_mtime:
        wav = out.with_suffix(".wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ar", "16000", "-ac", "1", str(wav)], check=True)
        subprocess.run(["whisper-cli", "-m", str(MODEL), "-f", str(wav), "-otxt", "-of", str(out), "-nt", "-np"],
                       check=True, capture_output=True)
        wav.unlink()
    return txt.read_text()


sent_file = W / "tts_script.json" if (W / "tts_script.json").exists() else W / "script.json"
items = [(f"audio/{s['id']}.mp3", s["narration"]) for s in json.loads(sent_file.read_text())["segments"]]
if "--podcast" in sys.argv:
    items += [(f"pod/{i:03d}.mp3", l["text"]) for i, l in enumerate(json.loads((W / "dialogue.json").read_text())["lines"])]
flags = []
for rel, sent in items:
    mp3 = W / rel
    if not mp3.exists():
        print("missing", rel)
        continue
    heard = transcribe(mp3)
    a, b = nums(sent), nums(heard)
    miss, extra = dict(a - b), dict(b - a)
    if miss or extra:
        flags.append({"file": rel, "missing": miss, "extra": extra, "sent": sent, "heard": " ".join(heard.split())})
(W / "qa" / "audio_numcheck.json").write_text(json.dumps(flags, indent=1))
for f in flags:
    print(f"{f['file']}: missing={f['missing']} extra={f['extra']}")
print(f"{len(flags)} flagged of {len(items)} -> qa/audio_numcheck.json (Scribe-check each flag before re-voicing)")
