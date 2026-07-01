#!/usr/bin/env python3
"""Digital Twin Skill.

Create audio or video of a specific person (you) saying arbitrary text:

  voice  -> ElevenLabs Professional Voice Clone (PVC) of your voice
  face   -> a canonical keyframe still (your photo, optionally cleaned via nano-banana)
  say    -> cloned-voice audio (the audio-only twin)
  video  -> script -> cloned-voice audio -> audio-driven talking-head video (fal)

Vendor split: ElevenLabs for the voice, fal.ai for the talking-head video.
Keys are reused from the eleven-labs-skill and fal-video-skill configs if present,
so you usually do not need to re-enter them.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print(json.dumps({"error": "requests not installed. Run: pip3 install requests"}))
    sys.exit(1)

CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / "config.json"
SKILLS_ROOT = CONFIG_DIR.parent

# Audio-driven talking-head models on fal (image + audio -> talking video).
AVATAR_MODELS = {
    # ByteDance OmniHuman 1.5: best single-photo quality, ~30s audio cap per call.
    "omnihuman": "fal-ai/bytedance/omnihuman/v1.5",
    # InfiniteTalk: long-form, strong identity preservation, effectively unlimited length.
    "infinitetalk": "fal-ai/infinitalk",
    # Kling AI Avatar v2 Pro: max polish, 1080p, up to ~5 min.
    "kling": "fal-ai/kling-video/ai-avatar/v2/pro",
}
DEFAULT_AVATAR = "kling"   # most expressive; omnihuman is turnkey but caps ~30s/clip
# OmniHuman caps a single generation around 30s of audio; warn past this.
OMNIHUMAN_AUDIO_WARN_SEC = 30

# Motion/camera guidance for the avatar prompt. Default = webcam-style talking head:
# locked-off camera, NO zoom / push-in / Ken Burns.
DEFAULT_VIDEO_PROMPT = (
    "Static locked-off webcam shot. No camera zoom, no push-in, no pan, no Ken Burns "
    "effect. The person looks straight at the camera and speaks naturally with subtle, "
    "lifelike head movement, blinking, and facial expression; framing and background stay fixed."
)

# Default art-direction set for `shots` (reference-frame generation via nano-banana).
DEFAULT_SHOTS = [
    "clean front-facing professional headshot, neutral relaxed expression, plain background",
    "front-facing with a warm, natural slight smile, plain background",
    "relaxed three-quarter angle portrait, still looking at the camera",
    "wearing a dark blazer over a tee, clean modern office background",
    "casual look in a home office, friendly and approachable",
]

# eleven_multilingual_v2 is broadly available; eleven_v3 is more expressive but may be
# gated on some accounts; eleven_flash_v2_5 is low-latency.
DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

EL_API = "https://api.elevenlabs.io"


# --------------------------------------------------------------------------- #
# Output / config helpers
# --------------------------------------------------------------------------- #
def output(data):
    print(json.dumps(data, indent=2, default=str))


def log(msg):
    print("[twin] {}".format(msg), file=sys.stderr)


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def data_root():
    """Root for generated/stored media. Configurable (config 'data_dir') so personal
    media can live outside the skill repo, which is gitignored / pushed to GitHub."""
    d = load_config().get("data_dir")
    return Path(d).expanduser() if d else CONFIG_DIR


def output_dir():
    return data_root() / "output"


def assets_dir():
    return data_root() / "assets"


def keyframes_dir():
    return data_root() / "keyframes"


def shots_dir():
    return keyframes_dir() / "shots"


def _read_sibling_key(skill_name, field="api_key"):
    """Read an api key from another installed skill's config.json."""
    p = SKILLS_ROOT / skill_name / "config.json"
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f).get(field)
        except (ValueError, OSError):
            return None
    return None


def get_elevenlabs_key():
    return (
        os.environ.get("ELEVENLABS_API_KEY")
        or load_config().get("elevenlabs_api_key")
        or _read_sibling_key("eleven-labs-skill", "api_key")
    )


def get_fal_key():
    return (
        os.environ.get("FAL_KEY")
        or os.environ.get("FAL_API_KEY")
        or load_config().get("fal_api_key")
        or _read_sibling_key("fal-video-skill", "api_key")
    )


def mask(key):
    if not key:
        return None
    return key[:6] + "..." + key[-4:] if len(key) > 12 else "****"


def get_el_client():
    """Return an authenticated ElevenLabs SDK client or (None, error)."""
    key = get_elevenlabs_key()
    if not key:
        return None, ("ElevenLabs API key not found. Set ELEVENLABS_API_KEY, run "
                      "'setup --elevenlabs-key KEY', or configure the eleven-labs-skill.")
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        return None, "elevenlabs SDK not installed. Run: pip3 install elevenlabs"
    try:
        return ElevenLabs(api_key=key), None
    except Exception as e:  # noqa: BLE001
        return None, "Failed to init ElevenLabs client: {}".format(e)


def salted(stem, ext):
    """Obsidian caches by filename; salt generated media so it refreshes."""
    return "{}_{}{}".format(stem, int(time.time()), ext)


def resolve_voice_id(args):
    vid = getattr(args, "voice_id", None) or load_config().get("voice_id")
    return vid


def resolve_keyframe(args):
    kf = getattr(args, "keyframe", None) or load_config().get("keyframe")
    return kf


def audio_duration_sec(path):
    """Best-effort duration via ffprobe; None if unavailable."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- #
# fal helpers (queue REST, mirrors fal-video-skill)
# --------------------------------------------------------------------------- #
def fal_upload(path, api_key):
    """Upload a local file to fal storage; return a URL. Falls back to data URL."""
    p = Path(path)
    if not p.exists():
        return None
    # Preferred: fal_client.upload_file -> real fal CDN URL.
    # (data: URLs are rejected by avatar models for the audio input.)
    try:
        import fal_client
        os.environ["FAL_KEY"] = api_key
        url = fal_client.upload_file(str(p))
        if url and url.startswith("http"):
            return url
    except Exception:  # noqa: BLE001
        pass
    suffix = p.suffix.lower()
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".ogg": "audio/ogg", ".flac": "audio/flac",
    }.get(suffix, "application/octet-stream")
    data = p.read_bytes()
    try:
        r = requests.post(
            "https://fal.run/fal-ai/file-upload",
            headers={"Authorization": "Key {}".format(api_key),
                     "Content-Type": "application/json"},
            json={"file_name": p.name}, timeout=60,
        )
        if r.status_code == 200:
            info = r.json()
            upload_url = info.get("upload_url")
            file_url = info.get("file_url")
            if upload_url and file_url:
                put = requests.put(
                    upload_url, data=data,
                    headers={"Content-Type": mime}, timeout=300,
                )
                if put.status_code in (200, 201, 204):
                    return file_url
    except requests.RequestException:
        pass
    # Fallback: inline data URL (works for smaller files)
    import base64
    b64 = base64.b64encode(data).decode("utf-8")
    return "data:{};base64,{}".format(mime, b64)


def fal_run(endpoint, payload, api_key, timeout=900):
    """Submit a fal queue job and poll until done. Returns result dict or {error}."""
    try:
        sub = requests.post(
            "https://queue.fal.run/{}".format(endpoint),
            headers={"Authorization": "Key {}".format(api_key),
                     "Content-Type": "application/json"},
            json=payload, timeout=120,
        )
    except requests.RequestException as e:
        return {"error": "fal submit failed: {}".format(e)}
    if sub.status_code != 200:
        return {"error": "fal API error {}: {}".format(sub.status_code, sub.text[:500])}
    sub = sub.json()
    request_id = sub.get("request_id")
    status_url = sub.get("status_url") or \
        "https://queue.fal.run/{}/requests/{}/status".format(endpoint, request_id)
    response_url = sub.get("response_url") or \
        "https://queue.fal.run/{}/requests/{}".format(endpoint, request_id)
    if not request_id:
        return {"error": "no request_id from fal", "response": sub}

    start = time.time()
    while time.time() - start < timeout:
        try:
            st = requests.get(status_url,
                              headers={"Authorization": "Key {}".format(api_key)},
                              params={"logs": 1}, timeout=60)
        except requests.RequestException:
            time.sleep(3)
            continue
        if st.status_code != 200:
            time.sleep(3)
            continue
        st = st.json()
        state = st.get("status")
        for entry in (st.get("logs") or []):
            if entry.get("message"):
                log("fal: {}".format(entry["message"]))
        if state == "COMPLETED":
            res = requests.get(response_url,
                               headers={"Authorization": "Key {}".format(api_key)},
                               timeout=120)
            if res.status_code == 200:
                return res.json()
            return {"error": "fal result fetch failed: {}".format(res.text[:500])}
        if state in ("FAILED", "CANCELLED", "ERROR"):
            return {"error": "fal request {}".format(state), "details": st}
        time.sleep(4)
    return {"error": "fal timeout", "request_id": request_id, "status_url": status_url}


def extract_video_url(result):
    """Find the output video URL across the common fal response shapes."""
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("video"), dict):
        return result["video"].get("url")
    if isinstance(result.get("video"), str):
        return result["video"]
    if result.get("video_url"):
        return result["video_url"]
    out = result.get("output")
    if isinstance(out, dict):
        v = out.get("video")
        if isinstance(v, dict):
            return v.get("url")
        if isinstance(v, str):
            return v
    # Some avatar models return {"videos":[{"url":...}]}
    vids = result.get("videos")
    if isinstance(vids, list) and vids:
        first = vids[0]
        return first.get("url") if isinstance(first, dict) else first
    return None


def download(url, dest):
    try:
        r = requests.get(url, stream=True, timeout=600)
    except requests.RequestException:
        return False
    if r.status_code != 200:
        return False
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return True


# --------------------------------------------------------------------------- #
# TTS (the audio engine)
# --------------------------------------------------------------------------- #
def synth_speech(text, voice_id, model_id, out_path, output_format=DEFAULT_OUTPUT_FORMAT):
    """Render text to speech in the cloned voice. Returns (path, error)."""
    client, err = get_el_client()
    if err:
        return None, err
    tmp = None
    try:
        audio_iter = client.text_to_speech.convert(
            voice_id,
            text=text,
            model_id=model_id,
            output_format=output_format,
        )
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and atomic-rename, so a failed/empty render
        # never leaves a 0-byte file at the destination.
        tmp = str(out_path) + ".part"
        with open(tmp, "wb") as f:
            for chunk in audio_iter:
                f.write(chunk)
        os.replace(tmp, out_path)
        return str(out_path), None
    except Exception as e:  # noqa: BLE001
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return None, "TTS failed: {}".format(_el_err(e))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_setup(args):
    config = load_config()
    if args.elevenlabs_key:
        config["elevenlabs_api_key"] = args.elevenlabs_key
    if args.fal_key:
        config["fal_api_key"] = args.fal_key
    if getattr(args, "data_dir", None):
        config["data_dir"] = args.data_dir
    if args.elevenlabs_key or args.fal_key or getattr(args, "data_dir", None):
        save_config(config)
    cmd_status(args)


def cmd_status(args):
    cfg = load_config()
    output({
        "elevenlabs_key": mask(get_elevenlabs_key()),
        "fal_key": mask(get_fal_key()),
        "voice_id": cfg.get("voice_id"),
        "voice_status": cfg.get("voice_status"),
        "keyframe": cfg.get("keyframe"),
        "data_dir": str(data_root()),
        "default_avatar_model": cfg.get("default_avatar_model", DEFAULT_AVATAR),
        "default_tts_model": cfg.get("default_tts_model", DEFAULT_TTS_MODEL),
        "default_video_prompt": cfg.get("default_video_prompt", DEFAULT_VIDEO_PROMPT),
        "avatar_models": AVATAR_MODELS,
    })


def cmd_voices(args):
    """List cloned/professional voices to pick a voice_id."""
    client, err = get_el_client()
    if err:
        output({"error": err})
        return
    try:
        resp = client.voices.get_all()
        voices = []
        for v in resp.voices:
            cat = getattr(v, "category", None)
            if args.all or cat in ("cloned", "professional", "generated"):
                voices.append({"voice_id": v.voice_id, "name": v.name, "category": cat})
        output({"voices": voices, "count": len(voices)})
    except Exception as e:  # noqa: BLE001
        output({"error": "Failed to list voices: {}".format(_el_err(e))})


def cmd_use_voice(args):
    """Point the twin at an existing voice_id."""
    if not args.voice_id:
        output({"error": "voice_id required: use-voice VOICE_ID"})
        return
    cfg = load_config()
    cfg["voice_id"] = args.voice_id
    cfg["voice_status"] = "selected"
    save_config(cfg)
    output({"status": "success", "voice_id": args.voice_id})


def _open_files(paths):
    handles = []
    for p in paths:
        if not Path(p).exists():
            for h in handles:
                h.close()
            return None, "File not found: {}".format(p)
        handles.append(open(p, "rb"))
    return handles, None


def cmd_voice_create(args):
    """PVC step 1+2: create a Professional Voice Clone and upload samples."""
    client, err = get_el_client()
    if err:
        output({"error": err})
        return
    if not args.name or not args.files:
        output({"error": "Usage: voice-create NAME sample1.mp3 [sample2 ...]",
                "tip": "PVC wants 30+ min of clean solo audio (3 hrs ideal) for best fidelity."})
        return
    try:
        created = client.voices.pvc.create(
            name=args.name,
            language=args.language,
            description=args.description or "Digital twin voice: {}".format(args.name),
        )
        voice_id = created.voice_id
    except Exception as e:  # noqa: BLE001
        output({"error": "PVC create failed: {}".format(_el_err(e)),
                "hint": "PVC needs Creator+ tier and an available professional-voice slot. "
                        "If this is a 401, the API key may lack voice-write scope."})
        return

    handles, ferr = _open_files(args.files)
    if ferr:
        output({"error": ferr, "voice_id": voice_id})
        return
    try:
        client.voices.pvc.samples.create(
            voice_id,
            files=handles,
            remove_background_noise=not args.no_noise_removal,
        )
    except Exception as e:  # noqa: BLE001
        output({"error": "Sample upload failed: {}".format(_el_err(e)), "voice_id": voice_id})
        return
    finally:
        for h in handles:
            h.close()

    cfg = load_config()
    cfg["voice_id"] = voice_id
    cfg["voice_status"] = "pending_verification"
    save_config(cfg)
    output({
        "status": "success",
        "voice_id": voice_id,
        "samples_uploaded": len(args.files),
        "next_steps": [
            "1. voice-verify           (get the captcha text to read aloud)",
            "2. voice-verify --recording you_reading_captcha.mp3",
            "3. voice-train            (start training; takes hours)",
            "4. voice-status           (poll until fine-tuning is done)",
        ],
    })


def cmd_voice_verify(args):
    """PVC verification: captcha (record yourself reading text) or manual ID upload."""
    client, err = get_el_client()
    if err:
        output({"error": err})
        return
    voice_id = args.voice_id or load_config().get("voice_id")
    if not voice_id:
        output({"error": "No voice_id. Run voice-create first or pass --voice-id."})
        return
    cap = client.voices.pvc.verification.captcha

    if args.id_file:  # manual verification path (gov ID / consent doc)
        handles, ferr = _open_files([args.id_file])
        if ferr:
            output({"error": ferr})
            return
        try:
            client.voices.pvc.verification.request(
                voice_id, files=handles, extra_text=args.note or None)
            output({"status": "submitted", "path": "manual",
                    "message": "Manual verification submitted for review."})
        except Exception as e:  # noqa: BLE001
            output({"error": "Manual verification failed: {}".format(_el_err(e))})
        finally:
            for h in handles:
                h.close()
        return

    if args.recording:  # submit a recording of you reading the captcha
        handles, ferr = _open_files([args.recording])
        if ferr:
            output({"error": ferr})
            return
        try:
            res = cap.verify(voice_id, recording=handles[0])
            cfg = load_config()
            cfg["voice_status"] = "verified"
            save_config(cfg)
            output({"status": "verified", "voice_id": voice_id, "result": _to_dict(res),
                    "next": "voice-train"})
        except Exception as e:  # noqa: BLE001
            output({"error": "Captcha verify failed: {}".format(_el_err(e))})
        finally:
            for h in handles:
                h.close()
        return

    # No recording: fetch the captcha (a PNG of the phrase to read), save + OCR it.
    try:
        data = _captcha_bytes(cap, voice_id)
        if not data:
            raise RuntimeError("empty captcha response")
        ad = assets_dir()
        ad.mkdir(parents=True, exist_ok=True)
        png = ad / "captcha_{}.png".format(voice_id)
        png.write_bytes(data)
        text = None
        if data[:8] == b"\x89PNG\r\n\x1a\n" and shutil.which("tesseract"):
            try:
                r = subprocess.run(["tesseract", str(png), "stdout", "--psm", "6"],
                                   capture_output=True, text=True, timeout=30)
                text = " ".join(r.stdout.split()) or None
            except (OSError, subprocess.SubprocessError):
                pass
        output({
            "status": "captcha_fetched",
            "voice_id": voice_id,
            "captcha_image": str(png),
            "captcha_text": text,
            "instructions": [
                "The voice owner reads the captcha phrase aloud and records it (clean, clear).",
                "Save it (e.g. captcha.mp3), then: voice-verify --recording captcha.mp3",
                "If OCR text is null, open the captcha_image to read the phrase.",
            ],
        })
    except Exception as e:  # noqa: BLE001
        output({"error": "Captcha fetch failed: {}".format(_el_err(e)),
                "fallback": "Complete PVC verification in the ElevenLabs web dashboard, "
                            "then run voice-train."})


def cmd_voice_train(args):
    client, err = get_el_client()
    if err:
        output({"error": err})
        return
    voice_id = args.voice_id or load_config().get("voice_id")
    if not voice_id:
        output({"error": "No voice_id. Pass --voice-id or run voice-create."})
        return
    try:
        res = client.voices.pvc.train(voice_id, model_id=args.model or None)
        cfg = load_config()
        cfg["voice_status"] = "training"
        save_config(cfg)
        output({"status": "training_started", "voice_id": voice_id,
                "result": _to_dict(res), "next": "voice-status (poll until done)"})
    except Exception as e:  # noqa: BLE001
        output({"error": "Training start failed: {}".format(_el_err(e)),
                "hint": "Verification must complete before training can run."})


def cmd_voice_status(args):
    client, err = get_el_client()
    if err:
        output({"error": err})
        return
    voice_id = args.voice_id or load_config().get("voice_id")
    if not voice_id:
        output({"error": "No voice_id. Pass --voice-id or run voice-create."})
        return
    try:
        v = client.voices.get(voice_id)
        ft = getattr(v, "fine_tuning", None)
        info = {"voice_id": voice_id, "name": getattr(v, "name", None),
                "category": getattr(v, "category", None)}
        if ft is not None:
            info["fine_tuning"] = _to_dict(ft)
        output(info)
    except Exception as e:  # noqa: BLE001
        output({"error": "Status lookup failed: {}".format(_el_err(e))})


def cmd_voice_instant(args):
    """Bonus: Instant Voice Clone for prototyping today (1-5 min audio, immediate)."""
    client, err = get_el_client()
    if err:
        output({"error": err})
        return
    if not args.name or not args.files:
        output({"error": "Usage: voice-instant NAME sample1.mp3 [sample2 ...]"})
        return
    handles, ferr = _open_files(args.files)
    if ferr:
        output({"error": ferr})
        return
    try:
        res = client.voices.ivc.create(
            name=args.name, files=handles,
            remove_background_noise=not args.no_noise_removal,
            description=args.description or "Digital twin (instant): {}".format(args.name),
        )
        voice_id = res.voice_id
        cfg = load_config()
        cfg["voice_id"] = voice_id
        cfg["voice_status"] = "ready_instant"
        save_config(cfg)
        output({"status": "success", "voice_id": voice_id,
                "note": "Instant clone ready immediately. Use 'say' or 'video' now."})
    except Exception as e:  # noqa: BLE001
        output({"error": "Instant clone failed: {}".format(_el_err(e))})
    finally:
        for h in handles:
            h.close()


def cmd_enroll_face(args):
    """Set the canonical keyframe still. Default: use the photo as-is.
    --generate: synthesize a clean front-facing headshot via nano-banana-pro."""
    if not args.photos:
        output({"error": "Usage: enroll-face photo1.png [photo2 ...] [--generate]"})
        return
    for p in args.photos:
        if not Path(p).exists():
            output({"error": "Photo not found: {}".format(p)})
            return
    kf_dir = keyframes_dir()
    kf_dir.mkdir(parents=True, exist_ok=True)

    if args.generate:
        nano = SKILLS_ROOT / "nano-banana-pro" / "generate_image.py"
        if not nano.exists():
            output({"error": "nano-banana-pro not found at {}".format(nano)})
            return
        prompt = args.prompt or (
            "A clean, well-lit, front-facing professional headshot of this exact person, "
            "neutral expression, looking straight at the camera, plain neutral background, "
            "sharp focus, preserve the person's identity and facial features exactly")
        cmd = ["python3", str(nano), prompt, "--photorealistic",
               "--aspect", "1:1", "--resolution", "2K",
               "--output", str(kf_dir), "--reference"] + list(args.photos)
        log("generating keyframe with nano-banana-pro...")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.SubprocessError as e:
            output({"error": "nano-banana invocation failed: {}".format(e)})
            return
        path = None
        for line in proc.stdout.splitlines():
            if "Image saved:" in line:
                path = line.split("Image saved:", 1)[1].strip()
        if not path or not Path(path).exists():
            output({"error": "Could not parse generated image path",
                    "stdout": proc.stdout[-800:], "stderr": proc.stderr[-800:]})
            return
        keyframe = path
    else:
        src = Path(args.photos[0])
        dest = kf_dir / salted("keyframe", src.suffix.lower() or ".png")
        shutil.copy2(src, dest)
        keyframe = str(dest)

    cfg = load_config()
    cfg["keyframe"] = keyframe
    save_config(cfg)
    output({"status": "success", "keyframe": keyframe,
            "generated": bool(args.generate)})


def cmd_say(args):
    """Audio-only twin: render text in the cloned voice."""
    text = _resolve_text(args)
    if not text:
        output({"error": "Provide text or --file. Usage: say \"...\" [--out a.mp3]"})
        return
    voice_id = resolve_voice_id(args)
    if not voice_id:
        output({"error": "No voice_id. Run voice-create/voice-instant or use-voice, "
                         "or pass --voice-id."})
        return
    cfg = load_config()
    model = args.model or cfg.get("default_tts_model", DEFAULT_TTS_MODEL)
    od = output_dir()
    od.mkdir(parents=True, exist_ok=True)
    out = args.out or str(od / salted("say", ".mp3"))
    log("synthesizing speech ({} chars, model={})...".format(len(text), model))
    path, err = synth_speech(text, voice_id, model, out)
    if err:
        output({"error": err})
        return
    output({"status": "success", "file": path, "voice_id": voice_id, "model": model,
            "chars": len(text)})


def cmd_video(args):
    """Full video twin: script -> cloned-voice audio -> talking-head video."""
    text = _resolve_text(args)
    if not text:
        output({"error": "Provide text or --file. Usage: video \"...\" [--out v.mp4]"})
        return
    voice_id = resolve_voice_id(args)
    if not voice_id:
        output({"error": "No voice_id. Run voice-create/voice-instant or use-voice."})
        return
    keyframe = resolve_keyframe(args)
    if not keyframe:
        output({"error": "No keyframe. Run enroll-face first or pass --keyframe."})
        return
    if not Path(keyframe).exists():
        output({"error": "Keyframe not found: {}".format(keyframe)})
        return
    fal_key = get_fal_key()
    if not fal_key:
        output({"error": "fal API key not found. Set FAL_KEY or configure fal-video-skill."})
        return

    model_key = args.model or load_config().get("default_avatar_model", DEFAULT_AVATAR)
    if model_key not in AVATAR_MODELS:
        output({"error": "Unknown avatar model: {}".format(model_key),
                "available": list(AVATAR_MODELS.keys())})
        return
    endpoint = AVATAR_MODELS[model_key]

    cfg = load_config()
    tts_model = args.tts_model or cfg.get("default_tts_model", DEFAULT_TTS_MODEL)
    od = output_dir()
    od.mkdir(parents=True, exist_ok=True)

    # 1. Voice
    audio_path = str(od / salted("twin_audio", ".mp3"))
    log("step 1/4: synthesizing cloned-voice audio...")
    audio_path, err = synth_speech(text, voice_id, tts_model, audio_path)
    if err:
        output({"error": err, "stage": "tts"})
        return

    dur = audio_duration_sec(audio_path)
    if dur and model_key == "omnihuman" and dur > OMNIHUMAN_AUDIO_WARN_SEC:
        log("WARNING: audio is {:.1f}s; OmniHuman caps near {}s. "
            "Consider --model infinitetalk for long scripts."
            .format(dur, OMNIHUMAN_AUDIO_WARN_SEC))

    # 2. Upload image + audio to fal
    log("step 2/4: uploading keyframe and audio to fal...")
    image_url = fal_upload(keyframe, fal_key)
    audio_url = fal_upload(audio_path, fal_key)
    if not image_url or not audio_url:
        output({"error": "fal upload failed", "image_url": bool(image_url),
                "audio_url": bool(audio_url)})
        return

    # 3. Submit to the avatar model.
    # prompt is REQUIRED by infinitalk and optional for omnihuman/kling; always send one.
    # Default is webcam-style (no zoom / Ken Burns); override per call or via config.
    prompt = args.prompt or cfg.get("default_video_prompt") or DEFAULT_VIDEO_PROMPT
    payload = {"image_url": image_url, "audio_url": audio_url, "prompt": prompt}
    log("step 3/4: generating talking-head video with {} ({})...".format(model_key, endpoint))
    result = fal_run(endpoint, payload, fal_key, timeout=args.timeout)
    if "error" in result:
        result["stage"] = "avatar"
        result["audio_file"] = audio_path
        output(result)
        return

    video_url = extract_video_url(result)
    if not video_url:
        output({"error": "No video URL in fal response", "response": result,
                "audio_file": audio_path})
        return

    # 4. Download
    log("step 4/4: downloading video...")
    out = args.out or str(od / salted("twin_video", ".mp4"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if download(video_url, out):
        output({"status": "success", "file": out, "audio_file": audio_path,
                "model": model_key, "endpoint": endpoint, "video_url": video_url,
                "audio_seconds": dur})
    else:
        output({"status": "partial", "video_url": video_url, "audio_file": audio_path,
                "note": "Video generated but download failed; use the URL directly."})


def cmd_shots(args):
    """Generate styled reference frames from real reference image(s) via nano-banana.
    Each becomes a keyframe you can drive with `video --keyframe ...` (e.g. wardrobe,
    angle, or setting variants). Identity is anchored by the reference image(s)."""
    refs = list(args.refs) if args.refs else []
    if not refs:
        kf = load_config().get("keyframe")
        if kf:
            refs = [kf]
    refs = [r for r in refs if r and Path(r).exists()]
    if not refs:
        output({"error": "No reference images. Pass image paths, or enroll-face first."})
        return
    nano = SKILLS_ROOT / "nano-banana-pro" / "generate_image.py"
    if not nano.exists():
        output({"error": "nano-banana-pro not found at {}".format(nano)})
        return
    shots = args.shots if args.shots else DEFAULT_SHOTS
    out = shots_dir()
    out.mkdir(parents=True, exist_ok=True)
    base = ("Photorealistic photo of this exact same person - preserve their identity, "
            "face shape, and features precisely. {desc}. Sharp focus, natural lighting, "
            "looking at the camera unless the description says otherwise.")
    results = []
    for i, desc in enumerate(shots, 1):
        prompt = base.format(desc=desc)
        cmd = ["python3", str(nano), prompt, "--photorealistic",
               "--aspect", args.aspect, "--resolution", "2K",
               "--output", str(out), "--reference"] + refs
        log("shot {}/{}: {}".format(i, len(shots), desc))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.SubprocessError as e:
            results.append({"shot": desc, "error": str(e)})
            continue
        path = None
        for line in proc.stdout.splitlines():
            if "Image saved:" in line:
                path = line.split("Image saved:", 1)[1].strip()
        if path and Path(path).exists():
            results.append({"shot": desc, "file": path})
        else:
            results.append({"shot": desc, "error": "no image produced",
                            "stderr": proc.stderr[-300:]})
    ok = [r for r in results if r.get("file")]
    output({
        "status": "done" if ok else "failed",
        "shots_dir": str(out),
        "references": refs,
        "generated": results,
        "tip": "Pick one and run:  video \"...\" --keyframe <file>   (or enroll-face <file>)",
    })


def cmd_models(args):
    output({
        "avatar_models": {
            "omnihuman": "ByteDance OmniHuman 1.5 - best single-photo quality, ~30s audio cap",
            "infinitetalk": "InfiniteTalk - long-form, strong identity, effectively unlimited",
            "kling": "Kling AI Avatar v2 Pro - max polish, 1080p, up to ~5 min",
        },
        "default_avatar": DEFAULT_AVATAR,
        "default_video_prompt": DEFAULT_VIDEO_PROMPT,
        "tts_models": {
            "eleven_multilingual_v2": "broadly available, 29 langs (default)",
            "eleven_v3": "most expressive (may be gated on some accounts)",
            "eleven_flash_v2_5": "low latency",
        },
        "default_tts": DEFAULT_TTS_MODEL,
    })


# --------------------------------------------------------------------------- #
# small utilities
# --------------------------------------------------------------------------- #
def _resolve_text(args):
    if getattr(args, "file", None):
        p = Path(args.file)
        if p.exists():
            return p.read_text().strip()
    return (getattr(args, "text", None) or "").strip()


def _el_err(e):
    """Pull a human-readable message out of an ElevenLabs SDK ApiError."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict) and detail.get("message"):
            return detail["message"]
        if isinstance(detail, str):
            return detail
        if body.get("message"):
            return body["message"]
    status = getattr(e, "status_code", None)
    return "{}{}".format("HTTP {}: ".format(status) if status else "", str(e)[:300])


def _to_dict(obj):
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                pass
    if isinstance(obj, (dict, list, str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _captcha_bytes(cap, voice_id):
    """Get the raw PVC verification captcha image bytes from the SDK."""
    try:
        raw = cap.with_raw_response.get(voice_id)
        for attr in ("_response", "response"):
            resp = getattr(raw, attr, None)
            if resp is not None and hasattr(resp, "content"):
                return resp.content
        d = getattr(raw, "data", None)
        if isinstance(d, (bytes, bytearray)):
            return bytes(d)
    except Exception:  # noqa: BLE001
        pass
    res = cap.get(voice_id)
    if isinstance(res, (bytes, bytearray)):
        return bytes(res)
    if hasattr(res, "__iter__"):
        return b"".join(res)
    return None


def _raw_body(raw):
    """Extract a readable body from an SDK with_raw_response result."""
    for attr in ("data",):
        if hasattr(raw, attr):
            d = getattr(raw, attr)
            if d is not None:
                return _to_dict(d)
    resp = getattr(raw, "_response", None) or getattr(raw, "response", None)
    if resp is not None:
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            try:
                return resp.text
            except Exception:  # noqa: BLE001
                pass
    return str(raw)


def main():
    parser = argparse.ArgumentParser(description="Digital Twin: cloned-voice audio & talking-head video")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("setup", help="Store keys / data dir / show status")
    p.add_argument("--elevenlabs-key")
    p.add_argument("--fal-key")
    p.add_argument("--data-dir", help="Where to store media (default: the skill dir)")

    sub.add_parser("status", help="Show configured keys, voice, keyframe, defaults")

    p = sub.add_parser("voices", help="List cloned/professional voices")
    p.add_argument("--all", action="store_true", help="Include premade voices too")

    p = sub.add_parser("use-voice", help="Point the twin at an existing voice_id")
    p.add_argument("voice_id", nargs="?")

    p = sub.add_parser("voice-create", help="PVC: create voice + upload samples")
    p.add_argument("name", nargs="?")
    p.add_argument("files", nargs="*", help="Audio samples (30+ min total recommended)")
    p.add_argument("--language", default="en")
    p.add_argument("--description")
    p.add_argument("--no-noise-removal", action="store_true")

    p = sub.add_parser("voice-verify", help="PVC verification (captcha or manual ID)")
    p.add_argument("--voice-id")
    p.add_argument("--recording", help="Audio of you reading the captcha text")
    p.add_argument("--id-file", help="Gov ID / consent doc for manual verification")
    p.add_argument("--note", help="Extra text for manual verification")

    p = sub.add_parser("voice-train", help="PVC: start training")
    p.add_argument("--voice-id")
    p.add_argument("--model", help="Optional model_id for training")

    p = sub.add_parser("voice-status", help="PVC: poll fine-tuning state")
    p.add_argument("--voice-id")

    p = sub.add_parser("voice-instant", help="Instant Voice Clone (prototype today)")
    p.add_argument("name", nargs="?")
    p.add_argument("files", nargs="*")
    p.add_argument("--description")
    p.add_argument("--no-noise-removal", action="store_true")

    p = sub.add_parser("enroll-face", help="Set the keyframe still (optionally --generate)")
    p.add_argument("photos", nargs="*")
    p.add_argument("--generate", action="store_true",
                   help="Synthesize a clean headshot via nano-banana-pro")
    p.add_argument("--prompt", help="Override the headshot prompt (with --generate)")

    p = sub.add_parser("shots", help="Generate reference frames from photo(s) via nano-banana")
    p.add_argument("refs", nargs="*", help="Reference images (default: enrolled keyframe)")
    p.add_argument("--shots", nargs="+", help="Shot descriptions (default: a standard set)")
    p.add_argument("--aspect", default="16:9", help="Aspect ratio for frames (default 16:9)")

    p = sub.add_parser("say", help="Audio twin: cloned-voice audio from text")
    p.add_argument("text", nargs="?")
    p.add_argument("--file", "-f", help="Read script from a file")
    p.add_argument("--voice-id")
    p.add_argument("--model", "-m", help="TTS model_id")
    p.add_argument("--out", "-o", help="Output audio path")

    p = sub.add_parser("video", help="Video twin: script -> cloned audio -> talking head")
    p.add_argument("text", nargs="?")
    p.add_argument("--file", "-f", help="Read script from a file")
    p.add_argument("--voice-id")
    p.add_argument("--keyframe", help="Override the enrolled keyframe image")
    p.add_argument("--model", "-m", help="Avatar model: {}".format("|".join(AVATAR_MODELS)))
    p.add_argument("--tts-model", help="TTS model_id")
    p.add_argument("--prompt", help="Optional motion/expression prompt")
    p.add_argument("--out", "-o", help="Output video path")
    p.add_argument("--timeout", type=int, default=900, help="fal poll timeout (s)")

    sub.add_parser("models", help="List avatar + TTS models")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    handlers = {
        "setup": cmd_setup, "status": cmd_status, "voices": cmd_voices,
        "use-voice": cmd_use_voice, "voice-create": cmd_voice_create,
        "voice-verify": cmd_voice_verify, "voice-train": cmd_voice_train,
        "voice-status": cmd_voice_status, "voice-instant": cmd_voice_instant,
        "enroll-face": cmd_enroll_face, "shots": cmd_shots, "say": cmd_say,
        "video": cmd_video, "models": cmd_models,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
