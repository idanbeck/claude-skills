#!/usr/bin/env python3
"""FAL Video Skill - Video generation using FAL.ai (Kling, Luma, Minimax, etc.)"""

import argparse
import json
import sys
import os
import time
import base64
import requests
from pathlib import Path
from datetime import datetime

CONFIG_DIR = Path(__file__).parent
OUTPUT_DIR = CONFIG_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Available models and their FAL endpoints
MODELS = {
    # Kling models (best quality)
    "kling": "fal-ai/kling-video/v1.6/standard/image-to-video",
    "kling-i2v": "fal-ai/kling-video/v1.6/standard/image-to-video",
    "kling-t2v": "fal-ai/kling-video/v1.6/standard/text-to-video",
    "kling-pro": "fal-ai/kling-video/v1.6/pro/image-to-video",
    "kling-pro-t2v": "fal-ai/kling-video/v1.6/pro/text-to-video",

    # Luma Dream Machine
    "luma": "fal-ai/luma-dream-machine",
    "luma-i2v": "fal-ai/luma-dream-machine/image-to-video",

    # Minimax (good for longer videos)
    "minimax": "fal-ai/minimax-video/image-to-video",
    "minimax-t2v": "fal-ai/minimax-video/text-to-video",

    # Hunyuan (open source, good quality)
    "hunyuan": "fal-ai/hunyuan-video",

    # Runway Gen-3 (if available)
    "runway": "fal-ai/runway-gen3/turbo/image-to-video",

    # Fast/cheap options
    "animatediff": "fal-ai/animatediff-v2v",
    "svd": "fal-ai/stable-video-diffusion",
}

DEFAULT_MODEL = "kling"


def get_api_key():
    """Get FAL API key from environment or config."""
    # Check environment variable first
    api_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if api_key:
        return api_key

    # Check config file
    config_file = CONFIG_DIR / "config.json"
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
            return config.get("api_key")

    return None


def output(data):
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


def image_to_base64(image_path):
    """Convert image file to base64 data URL."""
    path = Path(image_path)
    if not path.exists():
        return None

    # Determine mime type
    suffix = path.suffix.lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime_type = mime_types.get(suffix, "image/png")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{data}"


def upload_image_to_fal(image_path, api_key):
    """Upload image to FAL and return URL."""
    path = Path(image_path)
    if not path.exists():
        return None

    # Read file
    with open(path, "rb") as f:
        file_data = f.read()

    # Get upload URL
    response = requests.post(
        "https://fal.run/fal-ai/file-upload",
        headers={
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        },
        json={"file_name": path.name}
    )

    if response.status_code != 200:
        # Try direct base64 approach instead
        return image_to_base64(image_path)

    upload_data = response.json()
    upload_url = upload_data.get("upload_url")
    file_url = upload_data.get("file_url")

    # Upload file
    requests.put(upload_url, data=file_data)

    return file_url


def submit_fal_request(endpoint, payload, api_key):
    """Submit async request to FAL."""
    response = requests.post(
        f"https://queue.fal.run/{endpoint}",
        headers={
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        },
        json=payload
    )

    if response.status_code != 200:
        return {"error": f"FAL API error: {response.status_code} - {response.text}"}

    return response.json()


def check_fal_status(request_id, endpoint, api_key):
    """Check status of FAL request."""
    response = requests.get(
        f"https://queue.fal.run/{endpoint}/requests/{request_id}/status",
        headers={"Authorization": f"Key {api_key}"}
    )

    if response.status_code != 200:
        return {"status": "error", "error": response.text}

    return response.json()


def get_fal_result(request_id, endpoint, api_key):
    """Get result of completed FAL request."""
    response = requests.get(
        f"https://queue.fal.run/{endpoint}/requests/{request_id}",
        headers={"Authorization": f"Key {api_key}"}
    )

    if response.status_code != 200:
        return {"error": f"Failed to get result: {response.text}"}

    return response.json()


def run_fal_sync(endpoint, payload, api_key, timeout=300):
    """Run FAL request synchronously (submit and wait)."""
    # Submit request
    submit_result = submit_fal_request(endpoint, payload, api_key)

    if "error" in submit_result:
        return submit_result

    request_id = submit_result.get("request_id")
    if not request_id:
        return {"error": "No request_id returned", "response": submit_result}

    # Poll for completion
    start_time = time.time()
    while time.time() - start_time < timeout:
        status = check_fal_status(request_id, endpoint, api_key)

        state = status.get("status")
        if state == "COMPLETED":
            return get_fal_result(request_id, endpoint, api_key)
        elif state in ["FAILED", "CANCELLED"]:
            return {"error": f"Request {state}", "details": status}

        # Log progress
        if status.get("logs"):
            for log in status["logs"]:
                print(f"[FAL] {log.get('message', '')}", file=sys.stderr)

        time.sleep(2)

    return {"error": "Timeout waiting for result", "request_id": request_id}


def download_video(url, output_path):
    """Download video from URL to local file."""
    response = requests.get(url, stream=True)
    if response.status_code != 200:
        return False

    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return True


def cmd_i2v(args):
    """Image to video generation."""
    api_key = get_api_key()
    if not api_key:
        output({"error": "FAL API key not configured. Set FAL_KEY env var or add to config.json"})
        return

    if not args.image:
        output({"error": "Image path required", "usage": "fal_video_skill.py i2v IMAGE [--prompt PROMPT]"})
        return

    # Get model endpoint
    model = args.model or DEFAULT_MODEL
    if model not in MODELS:
        output({"error": f"Unknown model: {model}", "available": list(MODELS.keys())})
        return

    endpoint = MODELS[model]

    # Handle image - upload or use URL
    image_input = args.image
    if not image_input.startswith("http"):
        # Local file - upload to FAL
        image_url = upload_image_to_fal(image_input, api_key)
        if not image_url:
            output({"error": f"Could not process image: {image_input}"})
            return
    else:
        image_url = image_input

    # Build payload based on model
    payload = {
        "image_url": image_url,
    }

    if args.prompt:
        payload["prompt"] = args.prompt

    # Model-specific parameters
    if "kling" in model:
        payload["duration"] = str(args.duration) if args.duration else "5"
        if args.aspect_ratio:
            payload["aspect_ratio"] = args.aspect_ratio
    elif "luma" in model:
        if args.prompt:
            payload["prompt"] = args.prompt
    elif "minimax" in model:
        payload["prompt"] = args.prompt or "animate this image with natural motion"

    if args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt

    # Run request
    print(f"[FAL] Generating video with {model}...", file=sys.stderr)
    result = run_fal_sync(endpoint, payload, api_key, timeout=args.timeout or 300)

    if "error" in result:
        output(result)
        return

    # Extract video URL
    video_url = None
    if "video" in result:
        video_url = result["video"].get("url") if isinstance(result["video"], dict) else result["video"]
    elif "video_url" in result:
        video_url = result["video_url"]
    elif "output" in result:
        video_url = result["output"].get("video", {}).get("url")

    if not video_url:
        output({"error": "No video URL in response", "response": result})
        return

    # Download video
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"video_{model}_{timestamp}.mp4"

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    if download_video(video_url, output_path):
        output({
            "status": "success",
            "model": model,
            "file": str(output_path),
            "url": video_url,
            "duration": args.duration or 5,
        })
    else:
        output({
            "status": "success",
            "model": model,
            "url": video_url,
            "note": "Video URL returned but download failed. Use URL directly.",
        })


def cmd_t2v(args):
    """Text to video generation."""
    api_key = get_api_key()
    if not api_key:
        output({"error": "FAL API key not configured. Set FAL_KEY env var or add to config.json"})
        return

    if not args.prompt:
        output({"error": "Prompt required", "usage": "fal_video_skill.py t2v PROMPT"})
        return

    # Get model endpoint (use t2v variant)
    model = args.model or "kling-t2v"

    # Map to t2v endpoints
    t2v_models = {
        "kling": "fal-ai/kling-video/v1.6/standard/text-to-video",
        "kling-t2v": "fal-ai/kling-video/v1.6/standard/text-to-video",
        "kling-pro": "fal-ai/kling-video/v1.6/pro/text-to-video",
        "kling-pro-t2v": "fal-ai/kling-video/v1.6/pro/text-to-video",
        "minimax": "fal-ai/minimax-video/text-to-video",
        "minimax-t2v": "fal-ai/minimax-video/text-to-video",
        "hunyuan": "fal-ai/hunyuan-video",
        "luma": "fal-ai/luma-dream-machine",
    }

    endpoint = t2v_models.get(model)
    if not endpoint:
        output({"error": f"Model {model} does not support text-to-video", "available": list(t2v_models.keys())})
        return

    # Build payload
    payload = {
        "prompt": args.prompt,
    }

    if args.duration:
        payload["duration"] = str(args.duration)
    if args.aspect_ratio:
        payload["aspect_ratio"] = args.aspect_ratio
    if args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt

    # Run request
    print(f"[FAL] Generating video with {model}...", file=sys.stderr)
    result = run_fal_sync(endpoint, payload, api_key, timeout=args.timeout or 300)

    if "error" in result:
        output(result)
        return

    # Extract video URL
    video_url = None
    if "video" in result:
        video_url = result["video"].get("url") if isinstance(result["video"], dict) else result["video"]
    elif "video_url" in result:
        video_url = result["video_url"]

    if not video_url:
        output({"error": "No video URL in response", "response": result})
        return

    # Download video
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"video_{model}_{timestamp}.mp4"

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    if download_video(video_url, output_path):
        output({
            "status": "success",
            "model": model,
            "file": str(output_path),
            "url": video_url,
            "prompt": args.prompt,
        })
    else:
        output({
            "status": "success",
            "model": model,
            "url": video_url,
            "note": "Video URL returned but download failed. Use URL directly.",
        })


def cmd_models(args):
    """List available models."""
    output({
        "models": {
            "image_to_video": {
                "kling": "Kling 1.6 Standard (best quality, 5s)",
                "kling-pro": "Kling 1.6 Pro (highest quality, 5-10s)",
                "luma": "Luma Dream Machine",
                "luma-i2v": "Luma Dream Machine Image-to-Video",
                "minimax": "Minimax Video (good for longer clips)",
                "runway": "Runway Gen-3 Turbo",
                "svd": "Stable Video Diffusion (fast/cheap)",
            },
            "text_to_video": {
                "kling-t2v": "Kling 1.6 Standard Text-to-Video",
                "kling-pro-t2v": "Kling 1.6 Pro Text-to-Video",
                "minimax-t2v": "Minimax Text-to-Video",
                "hunyuan": "Hunyuan Video (open source)",
                "luma": "Luma Dream Machine",
            },
        },
        "default": DEFAULT_MODEL,
        "recommendation": "Use 'kling' for best i2v quality, 'kling-t2v' for t2v",
    })


def cmd_config(args):
    """Configure FAL API key."""
    if not args.api_key:
        # Show current config status
        api_key = get_api_key()
        if api_key:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "****"
            output({"status": "configured", "api_key": masked})
        else:
            output({"status": "not configured", "help": "Run: fal_video_skill.py config API_KEY"})
        return

    # Save config
    config = {"api_key": args.api_key}
    config_file = CONFIG_DIR / "config.json"

    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    # Set restrictive permissions
    os.chmod(config_file, 0o600)

    output({
        "status": "success",
        "message": "API key saved",
        "config_file": str(config_file),
    })


def cmd_status(args):
    """Check status of async request."""
    api_key = get_api_key()
    if not api_key:
        output({"error": "FAL API key not configured"})
        return

    if not args.request_id:
        output({"error": "Request ID required"})
        return

    endpoint = args.endpoint or MODELS[DEFAULT_MODEL]
    status = check_fal_status(args.request_id, endpoint, api_key)
    output(status)


def main():
    parser = argparse.ArgumentParser(description="FAL Video Generation Skill")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Image to video
    i2v_parser = subparsers.add_parser("i2v", help="Image to video generation")
    i2v_parser.add_argument("image", nargs="?", help="Image path or URL")
    i2v_parser.add_argument("--prompt", "-p", help="Motion/animation prompt")
    i2v_parser.add_argument("--model", "-m", help=f"Model to use (default: {DEFAULT_MODEL})")
    i2v_parser.add_argument("--duration", "-d", type=int, default=5, help="Video duration in seconds")
    i2v_parser.add_argument("--aspect-ratio", "-a", help="Aspect ratio (16:9, 9:16, 1:1)")
    i2v_parser.add_argument("--negative-prompt", "-n", help="Negative prompt")
    i2v_parser.add_argument("--output", "-o", help="Output file path")
    i2v_parser.add_argument("--timeout", "-t", type=int, default=300, help="Timeout in seconds")

    # Text to video
    t2v_parser = subparsers.add_parser("t2v", help="Text to video generation")
    t2v_parser.add_argument("prompt", nargs="?", help="Video description prompt")
    t2v_parser.add_argument("--model", "-m", help="Model to use")
    t2v_parser.add_argument("--duration", "-d", type=int, default=5, help="Video duration")
    t2v_parser.add_argument("--aspect-ratio", "-a", help="Aspect ratio")
    t2v_parser.add_argument("--negative-prompt", "-n", help="Negative prompt")
    t2v_parser.add_argument("--output", "-o", help="Output file path")
    t2v_parser.add_argument("--timeout", "-t", type=int, default=300, help="Timeout in seconds")

    # List models
    subparsers.add_parser("models", help="List available models")

    # Configure
    config_parser = subparsers.add_parser("config", help="Configure API key")
    config_parser.add_argument("api_key", nargs="?", help="FAL API key")

    # Check status
    status_parser = subparsers.add_parser("status", help="Check async request status")
    status_parser.add_argument("request_id", help="Request ID")
    status_parser.add_argument("--endpoint", "-e", help="Model endpoint")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "i2v": cmd_i2v,
        "t2v": cmd_t2v,
        "models": cmd_models,
        "config": cmd_config,
        "status": cmd_status,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
