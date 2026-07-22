#!/usr/bin/env python3
"""
voice-mode — talk to Claude by voice.

Pipeline:  mic → ElevenLabs Scribe (STT) → Claude (local `claude` CLI) → ElevenLabs (TTS) → speaker

Claude has no audio input, so a hosted speech model (ElevenLabs Scribe) does the
transcription; Claude is the brain in the middle. Reuses the ElevenLabs API key
already configured for the eleven-labs-skill — no new credentials.

Commands:
    setup [--voice-id ID] [--brain CMD]   configure voice / brain
    converse                              continuous voice conversation (default)
    once                                  a single turn (record → answer → speak)
    listen                                record one utterance, print the transcript
    say "text"                            speak text via ElevenLabs TTS
    stt PATH                              transcribe an audio file
    mics                                  list input devices
"""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import requests

SKILL_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SKILL_DIR / "config.json"
ELEVEN_CONFIG = Path.home() / ".claude" / "skills" / "eleven-labs-skill" / "config.json"

ELEVEN_BASE = "https://api.elevenlabs.io/v1"

VOICE_SYSTEM_PROMPT = (
    "You are Idan's spoken voice assistant. Your replies are read aloud by "
    "text-to-speech, so: keep answers short and conversational (1-3 sentences "
    "unless more is truly needed), use plain spoken language, and never use "
    "markdown, bullet lists, code blocks, or emoji. Answer directly and get to "
    "the point. If you don't know, say so briefly."
)

END_PHRASES = {
    "goodbye", "good bye", "exit", "quit", "stop listening",
    "that's all", "thats all", "end conversation", "bye",
}


# ---------------------------------------------------------------- config / auth

def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def eleven_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key and ELEVEN_CONFIG.exists():
        try:
            key = json.loads(ELEVEN_CONFIG.read_text()).get("api_key")
        except Exception:
            key = None
    if not key:
        sys.exit(
            "No ElevenLabs API key found. Set ELEVENLABS_API_KEY, or configure the "
            "eleven-labs-skill:\n"
            "  python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py setup YOUR_KEY"
        )
    return key


# ---------------------------------------------------------------- audio capture

def record_until_silence(cfg: dict, quiet: bool = False) -> str:
    """Record from the default mic until the speaker goes quiet. Returns a wav path."""
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as e:  # pragma: no cover
        sys.exit(
            f"Audio capture needs sounddevice + numpy ({e}).\n"
            f"  pip3 install -r {SKILL_DIR / 'requirements.txt'}\n"
            "(the sounddevice wheel bundles PortAudio on macOS — no brew needed)."
        )

    sr = int(cfg.get("samplerate", 16000))
    silence_secs = float(cfg.get("silence_secs", 1.2))
    max_secs = float(cfg.get("max_utterance_secs", 30))
    start_timeout = float(cfg.get("start_timeout_secs", 15))
    block = int(sr * 0.03)  # 30 ms frames

    def rms(frame) -> float:
        if frame.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))

    stream = sd.InputStream(samplerate=sr, channels=1, dtype="int16", blocksize=block)
    stream.start()
    try:
        # Calibrate ambient noise for ~0.4s.
        noise = []
        for _ in range(int(0.4 / 0.03)):
            data, _ = stream.read(block)
            noise.append(rms(data[:, 0]))
        floor = sorted(noise)[len(noise) // 2] if noise else 0.0
        threshold = max(floor * 3.0, 350.0)  # int16 RMS; 350 ≈ quiet room speech

        if not quiet:
            print("🎙  listening… (speak, then pause)", flush=True)

        frames = []
        started = False
        t0 = time.time()
        last_voice = t0
        while True:
            data, _ = stream.read(block)
            mono = data[:, 0]
            level = rms(mono)
            now = time.time()

            if level >= threshold:
                started = True
                last_voice = now
                frames.append(mono.copy())
            elif started:
                frames.append(mono.copy())  # keep trailing audio for natural cutoff

            if not started and (now - t0) > start_timeout:
                stream.stop(); stream.close()
                return ""  # nothing was said
            if started and (now - last_voice) > silence_secs:
                break
            if (now - t0) > max_secs:
                break
    finally:
        try:
            stream.stop(); stream.close()
        except Exception:
            pass

    if not frames:
        return ""

    audio = np.concatenate(frames)
    path = tempfile.mktemp(suffix=".wav", prefix="vm_")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return path


# ------------------------------------------------------------------- STT / TTS

def transcribe(wav_path: str, cfg: dict) -> str:
    with open(wav_path, "rb") as f:
        resp = requests.post(
            f"{ELEVEN_BASE}/speech-to-text",
            headers={"xi-api-key": eleven_key()},
            data={"model_id": cfg.get("stt_model", "scribe_v1")},
            files={"file": (os.path.basename(wav_path), f, "audio/wav")},
            timeout=120,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"STT failed ({resp.status_code}): {resp.text[:300]}")
    return (resp.json().get("text") or "").strip()


def speak(text: str, cfg: dict) -> None:
    if not text.strip():
        return
    voice_id = cfg.get("voice_id", "21m00Tcm4TlvDq8ikWAM")
    resp = requests.post(
        f"{ELEVEN_BASE}/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": eleven_key(),
            "accept": "audio/mpeg",
            "content-type": "application/json",
        },
        params={"output_format": "mp3_44100_128"},
        json={
            "text": text,
            "model_id": cfg.get("tts_model", "eleven_turbo_v2_5"),
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"TTS failed ({resp.status_code}): {resp.text[:300]}")
    mp3 = tempfile.mktemp(suffix=".mp3", prefix="vm_")
    with open(mp3, "wb") as f:
        f.write(resp.content)
    # afplay ships with macOS and plays mp3 natively.
    subprocess.run(["afplay", mp3], check=False)
    try:
        os.remove(mp3)
    except OSError:
        pass


# --------------------------------------------------------------------- brain

def ask_brain(transcript: list, cfg: dict) -> str:
    """Send the running transcript to Claude via the local `claude` CLI (uses your
    existing Claude Code auth — no API key needed)."""
    brain = cfg.get("brain", "claude")
    convo = "\n".join(f"{'User' if r == 'user' else 'Assistant'}: {t}" for r, t in transcript)
    prompt = convo + "\nAssistant:"

    if brain == "claude":
        cmd = ["claude", "-p", prompt, "--append-system-prompt", VOICE_SYSTEM_PROMPT]
    elif brain == "codex":
        # codex exec runs a one-shot prompt non-interactively.
        cmd = ["codex", "exec", f"{VOICE_SYSTEM_PROMPT}\n\n{prompt}"]
    else:
        cmd = brain.split() + [prompt]

    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return f"I can't find the '{brain.split()[0]}' command on your path."
    except subprocess.TimeoutExpired:
        return "That took too long, let's try again."
    reply = (out.stdout or "").strip()
    if not reply:
        reply = (out.stderr or "").strip() or "Sorry, I didn't get a response."
    return reply


# -------------------------------------------------------------------- commands

def cmd_converse(cfg: dict) -> None:
    print("Voice mode. Say 'goodbye' or press Ctrl-C to stop.\n", flush=True)
    transcript: list = []
    try:
        while True:
            wav = record_until_silence(cfg)
            if not wav:
                print("…(silence — still here, say something)", flush=True)
                continue
            try:
                user_text = transcribe(wav, cfg)
            finally:
                try: os.remove(wav)
                except OSError: pass
            if not user_text:
                continue
            print(f"🗣  You: {user_text}", flush=True)
            if user_text.strip().lower().strip(".!?") in END_PHRASES:
                speak("Goodbye.", cfg)
                break
            transcript.append(("user", user_text))
            reply = ask_brain(transcript, cfg)
            transcript.append(("assistant", reply))
            print(f"🤖 Claude: {reply}\n", flush=True)
            speak(reply, cfg)
            transcript[:] = transcript[-12:]  # keep last ~6 exchanges
    except KeyboardInterrupt:
        print("\n👋 ended.", flush=True)


def cmd_once(cfg: dict) -> None:
    wav = record_until_silence(cfg)
    if not wav:
        print("(nothing heard)"); return
    try:
        user_text = transcribe(wav, cfg)
    finally:
        try: os.remove(wav)
        except OSError: pass
    if not user_text:
        print("(couldn't transcribe)"); return
    print(f"🗣  You: {user_text}", flush=True)
    reply = ask_brain([("user", user_text)], cfg)
    print(f"🤖 Claude: {reply}", flush=True)
    speak(reply, cfg)


def cmd_listen(cfg: dict) -> None:
    wav = record_until_silence(cfg)
    if not wav:
        print(json.dumps({"text": "", "note": "no speech detected"})); return
    try:
        text = transcribe(wav, cfg)
    finally:
        try: os.remove(wav)
        except OSError: pass
    print(json.dumps({"text": text}))


def cmd_say(cfg: dict, text: str) -> None:
    speak(text, cfg)
    print(json.dumps({"spoke": text[:80]}))


def cmd_stt(cfg: dict, path: str) -> None:
    if not os.path.exists(path):
        sys.exit(f"file not found: {path}")
    print(json.dumps({"text": transcribe(path, cfg)}))


def cmd_mics(_cfg: dict) -> None:
    try:
        import sounddevice as sd
    except Exception as e:
        sys.exit(f"sounddevice not installed ({e}). pip3 install -r {SKILL_DIR/'requirements.txt'}")
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            print(f"  [{i}] {d['name']}  (in:{d['max_input_channels']})")


def cmd_setup(cfg: dict, args) -> None:
    if args.voice_id:
        cfg["voice_id"] = args.voice_id
        cfg["voice_name"] = args.voice_name or "custom"
    if args.brain:
        cfg["brain"] = args.brain
    save_config(cfg)
    # sanity check ElevenLabs auth via a capability endpoint (/voices), since some
    # keys aren't scoped for /user but work fine for STT/TTS.
    key = eleven_key()
    ok = requests.get(f"{ELEVEN_BASE}/voices", headers={"xi-api-key": key}, timeout=30).status_code == 200
    print(json.dumps({
        "config": cfg,
        "elevenlabs_auth": "ok" if ok else "key present (verify STT/TTS if this says check)",
        "claude_cli": bool(subprocess.run(["which", cfg.get("brain", "claude")],
                                          capture_output=True).returncode == 0),
    }, indent=2))


# ------------------------------------------------------------------------- main

def main() -> None:
    cfg = load_config()
    p = argparse.ArgumentParser(description="Voice mode for Claude (ElevenLabs STT/TTS).")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("converse", help="continuous voice conversation")
    sub.add_parser("once", help="single turn")
    sub.add_parser("listen", help="record one utterance → transcript JSON")
    sub.add_parser("mics", help="list input devices")

    sp = sub.add_parser("say", help="speak text")
    sp.add_argument("text")
    st = sub.add_parser("stt", help="transcribe an audio file")
    st.add_argument("path")
    se = sub.add_parser("setup", help="configure")
    se.add_argument("--voice-id")
    se.add_argument("--voice-name")
    se.add_argument("--brain", help="brain command: 'claude' (default) or 'codex'")

    args = p.parse_args()
    cmd = args.cmd or "converse"

    if cmd == "converse": cmd_converse(cfg)
    elif cmd == "once": cmd_once(cfg)
    elif cmd == "listen": cmd_listen(cfg)
    elif cmd == "mics": cmd_mics(cfg)
    elif cmd == "say": cmd_say(cfg, args.text)
    elif cmd == "stt": cmd_stt(cfg, args.path)
    elif cmd == "setup": cmd_setup(cfg, args)
    else: p.print_help()


if __name__ == "__main__":
    main()
