#!/usr/bin/env python3
"""Written-form script -> spoken-form TTS script.

script.json holds the WRITTEN form (digits, model names, symbols as they should appear in captions:
"Qwen3-4B", "50.9 percent", "GRPO"). This applies pronunciation rules and writes tts_script.json, which is
what pe.py tts voices. Rules: <workdir>/lexicon.json {"rules": [[written, spoken], ...]} first (paper-specific),
then the shared DEFAULT rules below. Matching is case-sensitive with word boundaries.

  tts_prep.py <workdir> [--say]      # --say prints the spoken text for review
"""
import json
import re
import sys
from pathlib import Path

DEFAULT = [
    ("GRPO", "G R P O"), ("RLVR", "R L V R"), ("RLHF", "R L H F"), ("PPO", "P P O"), ("DPO", "D P O"), ("SFT", "S F T"),
    ("LLMs", "L L Ms"), ("LLM", "L L M"), ("VLMs", "V L Ms"), ("VLM", "V L M"), ("VAE", "V A E"), ("ViT", "V I T"),
    ("GPUs", "G P Us"), ("GPU", "G P U"), ("API", "A P I"), ("JSON", "jay-son"), ("CoT", "chain of thought"),
    ("FP32", "F P thirty-two"), ("FP16", "F P sixteen"), ("BF16", "B F sixteen"), ("FP8", "F P eight"),
    ("1080p", "ten eighty p"), ("3D", "three D"), ("2D", "two D"),
]


def rules(workdir):
    p = Path(workdir) / "lexicon.json"
    own = [tuple(r) for r in json.loads(p.read_text())["rules"]] if p.exists() else []
    return own + DEFAULT


def spoken(text, rs):
    out = text
    for pat, rep in rs:
        out = re.sub(r"(?<![A-Za-z0-9_.])" + re.escape(pat) + r"(?![A-Za-z0-9_])", rep, out)
    return out


if __name__ == "__main__":
    W = Path(sys.argv[1]).resolve()
    rs = rules(W)
    s = json.loads((W / "script.json").read_text())
    t = dict(s, segments=[dict(seg, narration=spoken(seg["narration"], rs)) for seg in s["segments"]])
    (W / "tts_script.json").write_text(json.dumps(t, indent=1, ensure_ascii=False))
    if "--say" in sys.argv:
        for seg in t["segments"]:
            print(f"[{seg['id']}] {seg['narration']}\n")
    print(f"wrote {W / 'tts_script.json'}")
