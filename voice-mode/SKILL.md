---
name: voice-mode
description: Talk to Claude by voice. Records the mic, transcribes with ElevenLabs Scribe (hosted STT, no local Whisper), sends the text to Claude via the local `claude` CLI, and speaks the reply back with ElevenLabs TTS. Use when the user wants a spoken/voice conversation, voice input, or to dictate to Claude.
---

# Voice Mode

A hands-free voice loop for Claude:

```
mic → ElevenLabs Scribe (STT) → Claude (local `claude` CLI) → ElevenLabs (TTS) → speaker
```

**Why not Whisper / "use Claude to transcribe"?** Claude has no audio input — it can't
transcribe. So a fast *hosted* speech model (ElevenLabs Scribe) does the STT, and Claude
is the brain in the middle. This avoids running Whisper locally (slower, heavier).

## Auth (no new credentials)

Reuses the ElevenLabs API key already set for `eleven-labs-skill`
(`~/.claude/skills/eleven-labs-skill/config.json`, or `ELEVENLABS_API_KEY`).
The brain uses your existing Claude Code login via the `claude` CLI — no API key needed.

## One-time setup

```bash
pip3 install -r ~/.claude/skills/voice-mode/requirements.txt   # sounddevice, numpy, requests
python3 ~/.claude/skills/voice-mode/voice_mode.py setup        # verifies ElevenLabs + claude CLI
```

macOS will prompt for **microphone permission** the first time the terminal records.
The `sounddevice` wheel bundles PortAudio — no `brew install` needed.

## Use

```bash
# Continuous conversation (default). Speak, pause, hear the reply. Say "goodbye" or Ctrl-C to stop.
python3 ~/.claude/skills/voice-mode/voice_mode.py converse

# One turn: record → answer → speak
python3 ~/.claude/skills/voice-mode/voice_mode.py once

# Utilities
python3 ~/.claude/skills/voice-mode/voice_mode.py listen        # record → {"text": ...}
python3 ~/.claude/skills/voice-mode/voice_mode.py say "hello"   # TTS only
python3 ~/.claude/skills/voice-mode/voice_mode.py stt clip.wav  # transcribe a file
python3 ~/.claude/skills/voice-mode/voice_mode.py mics          # list input devices
```

It auto-detects when you stop talking (silence-based cutoff), so there's no push-to-talk.

## Config (`config.json`)

| key | default | notes |
|-----|---------|-------|
| `voice_id` | `21m00Tcm4TlvDq8ikWAM` | ElevenLabs voice (Rachel, a standard voice) |
| `stt_model` | `scribe_v1` | ElevenLabs Scribe |
| `tts_model` | `eleven_turbo_v2_5` | low-latency; use `eleven_flash_v2_5` for min latency |
| `brain` | `claude` | `claude` (Claude Code CLI) or `codex` |
| `silence_secs` | `1.2` | trailing silence that ends an utterance |
| `max_utterance_secs` | `30` | hard cap per turn |

Change the voice: `voice_mode.py setup --voice-id <ID> --voice-name "<name>"`
(browse voices with the eleven-labs-skill). Idan already has a personal voice clone
from the `digital-twin` skill — pass its voice id here to have Claude reply in his voice.

Switch the brain to Codex: `voice_mode.py setup --brain codex`.

## Notes / gotchas

- Replies are constrained by a system prompt to be short and TTS-friendly (no markdown/lists).
- Each turn sends the running transcript to `claude -p` (fresh context per call — avoids the
  `--continue` staleness issue), keeping the last ~6 exchanges.
- STT and TTS are hosted calls (billed to your ElevenLabs account); latency is network-bound,
  typically a second or two per leg — far faster than local Whisper on this machine.
