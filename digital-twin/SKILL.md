---
name: digital-twin
description: Generate audio or video of a specific person (the user) saying arbitrary text. Clones the user's voice with ElevenLabs (Professional Voice Clone) and drives a talking-head video with fal.ai audio-driven avatar models. Use when the user wants to make their voice say something, produce a talking-head video of themselves, or build/manage their voice/face twin.
allowed-tools: Bash, Read, Write
---

# Digital Twin

Create a voice + video twin of yourself, then make it say arbitrary text.

**Vendor split:** ElevenLabs for the cloned voice (best fidelity), fal.ai for the
audio-driven talking-head video. Keys are reused from `eleven-labs-skill` and
`fal-video-skill` configs automatically, so you usually don't re-enter them.

## Pipeline

```
voice (PVC) ──────────────────────────────►  say  = cloned-voice audio   (audio twin)

reference photo ─► shots (nano-banana) ─► pick a keyframe ─┐
voice (PVC) ───────────────────────────────────────────────┴─► video = kling talking-head mp4
```

## Setup

```bash
pip3 install elevenlabs requests fal-client   # ffmpeg recommended; nano-banana-pro skill for `shots`
python3 ~/.claude/skills/digital-twin/digital_twin.py status
# Optionally store keys directly (else inherited from the other skills):
python3 ~/.claude/skills/digital-twin/digital_twin.py setup --elevenlabs-key KEY --fal-key KEY
# Keep media out of the skill repo (recommended) — store it anywhere:
python3 ~/.claude/skills/digital-twin/digital_twin.py setup --data-dir ~/Documents/DigitalTwin
```

## 1. Clone the voice (Professional Voice Clone)

PVC gives near-indistinguishable fidelity. It wants **30+ min of clean solo audio**
(≈3 hrs ideal), needs a **Creator+** ElevenLabs tier with a free professional-voice
slot, and includes a **human verification step** (you record yourself reading a captcha).

```bash
# 1. create the voice + upload samples (mp3/wav/m4a)
python3 .../digital_twin.py voice-create "Idan" sample1.mp3 sample2.mp3 ...

# 2. get the captcha text to read aloud
python3 .../digital_twin.py voice-verify
# ...record yourself reading it, then submit the recording:
python3 .../digital_twin.py voice-verify --recording captcha.mp3
#   (or manual ID path:  voice-verify --id-file consent.pdf)

# 3. train, then poll until done (training takes hours)
python3 .../digital_twin.py voice-train
python3 .../digital_twin.py voice-status
```

The resulting `voice_id` is stored in `config.json` and used by `say`/`video`.

**Prototype today without waiting for PVC** — Instant Voice Clone (1–5 min audio, immediate):

```bash
python3 .../digital_twin.py voice-instant "Idan" short_sample.mp3
```

Point at an existing voice / list voices:

```bash
python3 .../digital_twin.py voices
python3 .../digital_twin.py use-voice VOICE_ID
```

## 2. Enroll a face (keyframe still)

```bash
# Use a photo as-is (recommended starting point):
python3 .../digital_twin.py enroll-face "/path/to/photo.png"

# Or synthesize a clean front-facing headshot from reference photos (nano-banana-pro):
python3 .../digital_twin.py enroll-face photo1.png photo2.png --generate
```

A short (15–30s) video clip of the subject yields materially better likeness than a
still, but every avatar model here works from a single photo.

## 2b. Generate reference shots (optional — art direction)

Turn your real reference frame(s) into a library of styled keyframes — different
expressions, angles, wardrobe, or settings — via nano-banana-pro, with identity anchored
by the reference image(s). Use real, current-look frames as references for consistency.

```bash
# default set: headshot, slight smile, 3/4 angle, blazer-in-office, casual home-office
python3 .../digital_twin.py shots ref1.jpg ref2.jpg

# custom directions
python3 .../digital_twin.py shots ref1.jpg --shots "in a suit on a conference stage" "outdoors, golden hour"
```

Frames land in `data_dir/keyframes/shots/`. Drive any one with the video stage:

```bash
python3 .../digital_twin.py video "..." --keyframe <shots/...png>
```

## 3. Generate

```bash
# Audio-only twin
python3 .../digital_twin.py say "Hey, this is Idan." --out hello.mp3
python3 .../digital_twin.py say --file script.txt

# Full talking-head video
python3 .../digital_twin.py video "Hey, this is Idan." --out hello.mp4
python3 .../digital_twin.py video --file script.txt --model infinitetalk
```

## Avatar models (`--model`)

| key | fal endpoint | notes |
|-----|--------------|-------|
| `kling` (default) | `fal-ai/kling-video/ai-avatar/v2/pro` | most expressive; 1080p; up to ~5 min |
| `omnihuman` | `fal-ai/bytedance/omnihuman/v1.5` | turnkey single-photo; ~30s audio cap/call |
| `infinitetalk` | `fal-ai/infinitalk` | long-form, strong identity, effectively unlimited |

`python3 .../digital_twin.py models` lists avatar + TTS models.

## Notes & caveats

- **Long scripts:** OmniHuman caps near 30s of audio per call; the skill warns and you
  should switch to `--model infinitetalk` (or `kling`) for monologues.
- **fal input fields:** avatar models are sent `image_url` + `audio_url` + `prompt`
  (verified against the live fal OpenAPI schemas; `infinitalk` *requires* `prompt`, the
  others default it). fal slugs and input names evolve; if a model errors on validation,
  check its page on fal.ai and adjust `AVATAR_MODELS` / the payload in `digital_twin.py`.
- **TTS model:** defaults to `eleven_multilingual_v2`. `eleven_v3` is more expressive but
  may be gated on your account; `eleven_flash_v2_5` is low-latency.
- **Motion prompt:** `video` sends a default webcam-style prompt (static, locked-off, no
  zoom / Ken Burns). Override per call with `--prompt "..."` or set `default_video_prompt`
  in config. This matters: without it, avatar models tend to add a slow push-in.
- **Storage:** set `data_dir` (`setup --data-dir DIR`) to keep media out of the skill repo
  (which is `.gitignore`'d and pushed to GitHub). Outputs → `data_dir/output`, keyframes →
  `data_dir/keyframes`, shots → `data_dir/keyframes/shots`. Defaults to the skill dir if unset.
- **Consent & safety:** only clone your own likeness. A voice+face twin is high
  impersonation risk — keep the cloned `voice_id`, keyframe, and outputs access-controlled
  and never expose them to third parties via bridges/CRM without explicit gating.

#voice #video #avatar #elevenlabs #fal #digitaltwin
