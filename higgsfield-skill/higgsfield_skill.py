#!/usr/bin/env python3
"""Higgsfield Skill - AI Video Generation from Images and Text."""

import argparse
import json
import sys
import os
import time
import requests
from pathlib import Path
from datetime import datetime

CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / "config.json"
OUTPUT_DIR = CONFIG_DIR / "output"

# Higgsfield API endpoints
API_BASE = "https://api.higgsfield.ai/v1"


def output(data):
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


def load_config():
    """Load API key from config."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save config to file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_headers():
    """Get authenticated headers."""
    config = load_config()
    api_key = config.get('api_key') or os.environ.get('HIGGSFIELD_API_KEY')

    if not api_key:
        return None, "API key not configured. Run: python3 higgsfield_skill.py setup YOUR_API_KEY"

    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, None


def cmd_setup(args):
    """Set up API key."""
    if not args.api_key:
        output({
            "error": "API key required",
            "usage": "python3 higgsfield_skill.py setup YOUR_API_KEY",
            "get_key": "Get your API key at https://higgsfield.ai (sign up for API access)"
        })
        return

    config = load_config()
    config['api_key'] = args.api_key
    save_config(config)

    # Verify the key works
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    try:
        response = requests.get(f"{API_BASE}/user", headers=headers, timeout=10)
        if response.status_code == 200:
            output({
                "status": "success",
                "message": "Higgsfield API configured successfully"
            })
        elif response.status_code == 401:
            output({"error": "Invalid API key"})
        else:
            # Even if validation fails, save the key for later
            output({
                "status": "saved",
                "message": "API key saved. Validation endpoint may not be available.",
                "note": "Try running a generation to verify the key works."
            })
    except requests.exceptions.RequestException as e:
        # Save anyway, endpoint might not be available
        output({
            "status": "saved",
            "message": "API key saved (could not verify - network error)",
            "note": str(e)
        })


def cmd_image_to_video(args):
    """Generate video from an image."""
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    if not args.image:
        output({
            "error": "Image path required",
            "usage": "python3 higgsfield_skill.py i2v path/to/image.png --prompt \"camera slowly zooms in\""
        })
        return

    image_path = Path(args.image)
    if not image_path.exists():
        output({"error": f"Image not found: {args.image}"})
        return

    try:
        # Read and encode image
        import base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Determine image type
        suffix = image_path.suffix.lower()
        mime_type = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp'
        }.get(suffix, 'image/png')

        # Build request payload
        payload = {
            "image": f"data:{mime_type};base64,{image_data}",
            "prompt": args.prompt or "smooth camera motion",
            "duration": args.duration or 4,
            "fps": args.fps or 24,
            "motion_strength": args.motion or 0.5,
        }

        if args.negative_prompt:
            payload["negative_prompt"] = args.negative_prompt

        # Submit generation request
        response = requests.post(
            f"{API_BASE}/generations/image-to-video",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 200 and response.status_code != 201:
            output({"error": f"API error: {response.status_code}", "detail": response.text})
            return

        result = response.json()
        generation_id = result.get('id') or result.get('generation_id')

        if not generation_id:
            output({"error": "No generation ID returned", "response": result})
            return

        output({
            "status": "submitted",
            "generation_id": generation_id,
            "message": "Video generation started. Use 'status' command to check progress.",
            "check_command": f"python3 higgsfield_skill.py status {generation_id}"
        })

    except Exception as e:
        output({"error": f"Image-to-video failed: {str(e)}"})


def cmd_text_to_video(args):
    """Generate video from text prompt."""
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    if not args.prompt:
        output({
            "error": "Prompt required",
            "usage": "python3 higgsfield_skill.py t2v \"A sunset over the ocean with gentle waves\""
        })
        return

    try:
        payload = {
            "prompt": args.prompt,
            "duration": args.duration or 4,
            "fps": args.fps or 24,
            "aspect_ratio": args.aspect_ratio or "16:9",
        }

        if args.negative_prompt:
            payload["negative_prompt"] = args.negative_prompt

        if args.style:
            payload["style"] = args.style

        response = requests.post(
            f"{API_BASE}/generations/text-to-video",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 200 and response.status_code != 201:
            output({"error": f"API error: {response.status_code}", "detail": response.text})
            return

        result = response.json()
        generation_id = result.get('id') or result.get('generation_id')

        output({
            "status": "submitted",
            "generation_id": generation_id,
            "message": "Video generation started. Use 'status' command to check progress.",
            "check_command": f"python3 higgsfield_skill.py status {generation_id}"
        })

    except Exception as e:
        output({"error": f"Text-to-video failed: {str(e)}"})


def cmd_status(args):
    """Check status of a generation."""
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    if not args.generation_id:
        output({"error": "Generation ID required", "usage": "python3 higgsfield_skill.py status GENERATION_ID"})
        return

    try:
        response = requests.get(
            f"{API_BASE}/generations/{args.generation_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            output({"error": f"API error: {response.status_code}", "detail": response.text})
            return

        result = response.json()
        status = result.get('status', 'unknown')

        output_data = {
            "generation_id": args.generation_id,
            "status": status,
            "progress": result.get('progress'),
        }

        # If complete, include download URL and optionally download
        if status in ['completed', 'complete', 'done', 'success']:
            video_url = result.get('video_url') or result.get('output_url') or result.get('url')
            output_data['video_url'] = video_url

            if args.download and video_url:
                OUTPUT_DIR.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"video_{args.generation_id[:8]}_{timestamp}.mp4"
                filepath = OUTPUT_DIR / filename

                video_response = requests.get(video_url, timeout=120)
                with open(filepath, 'wb') as f:
                    f.write(video_response.content)

                output_data['downloaded'] = str(filepath)

        elif status in ['failed', 'error']:
            output_data['error'] = result.get('error') or result.get('message')

        output(output_data)

    except Exception as e:
        output({"error": f"Status check failed: {str(e)}"})


def cmd_download(args):
    """Download a completed generation."""
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    if not args.generation_id:
        output({"error": "Generation ID required"})
        return

    try:
        # Get generation status to get URL
        response = requests.get(
            f"{API_BASE}/generations/{args.generation_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            output({"error": f"API error: {response.status_code}"})
            return

        result = response.json()
        video_url = result.get('video_url') or result.get('output_url') or result.get('url')

        if not video_url:
            output({"error": "No video URL available", "status": result.get('status')})
            return

        # Download video
        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = args.output or f"video_{args.generation_id[:8]}_{timestamp}.mp4"
        filepath = OUTPUT_DIR / filename

        video_response = requests.get(video_url, timeout=120)
        with open(filepath, 'wb') as f:
            f.write(video_response.content)

        output({
            "status": "success",
            "file": str(filepath),
            "size_bytes": len(video_response.content)
        })

    except Exception as e:
        output({"error": f"Download failed: {str(e)}"})


def cmd_list(args):
    """List recent generations."""
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    try:
        response = requests.get(
            f"{API_BASE}/generations",
            headers=headers,
            params={"limit": args.limit or 20},
            timeout=30
        )

        if response.status_code != 200:
            output({"error": f"API error: {response.status_code}", "detail": response.text})
            return

        result = response.json()
        generations = result.get('generations') or result.get('data') or result

        if isinstance(generations, list):
            items = []
            for gen in generations:
                items.append({
                    "id": gen.get('id') or gen.get('generation_id'),
                    "type": gen.get('type'),
                    "status": gen.get('status'),
                    "created_at": gen.get('created_at'),
                    "prompt": gen.get('prompt', '')[:50] + "..." if gen.get('prompt', '') and len(gen.get('prompt', '')) > 50 else gen.get('prompt')
                })
            output({"generations": items, "count": len(items)})
        else:
            output({"generations": generations})

    except Exception as e:
        output({"error": f"List failed: {str(e)}"})


def cmd_wait(args):
    """Wait for a generation to complete and download."""
    headers, error = get_headers()
    if error:
        output({"error": error})
        return

    if not args.generation_id:
        output({"error": "Generation ID required"})
        return

    try:
        max_attempts = args.timeout or 60  # Default 5 minutes (60 * 5 sec intervals)
        attempt = 0

        while attempt < max_attempts:
            response = requests.get(
                f"{API_BASE}/generations/{args.generation_id}",
                headers=headers,
                timeout=30
            )

            if response.status_code != 200:
                output({"error": f"API error: {response.status_code}"})
                return

            result = response.json()
            status = result.get('status', 'unknown').lower()

            if status in ['completed', 'complete', 'done', 'success']:
                video_url = result.get('video_url') or result.get('output_url') or result.get('url')

                if video_url:
                    OUTPUT_DIR.mkdir(exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"video_{args.generation_id[:8]}_{timestamp}.mp4"
                    filepath = OUTPUT_DIR / filename

                    video_response = requests.get(video_url, timeout=120)
                    with open(filepath, 'wb') as f:
                        f.write(video_response.content)

                    output({
                        "status": "success",
                        "file": str(filepath),
                        "generation_id": args.generation_id
                    })
                    return
                else:
                    output({"status": "complete", "message": "No video URL available"})
                    return

            elif status in ['failed', 'error']:
                output({
                    "status": "failed",
                    "error": result.get('error') or result.get('message') or "Generation failed"
                })
                return

            # Still processing
            attempt += 1
            time.sleep(5)

        output({"error": "Timeout waiting for generation", "last_status": status})

    except Exception as e:
        output({"error": f"Wait failed: {str(e)}"})


def main():
    parser = argparse.ArgumentParser(description="Higgsfield AI Video Generation")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Setup
    setup_parser = subparsers.add_parser("setup", help="Configure API key")
    setup_parser.add_argument("api_key", nargs="?", help="Higgsfield API key")

    # Image to video
    i2v_parser = subparsers.add_parser("i2v", help="Generate video from image")
    i2v_parser.add_argument("image", nargs="?", help="Path to input image")
    i2v_parser.add_argument("--prompt", "-p", help="Motion/animation prompt")
    i2v_parser.add_argument("--negative-prompt", "-n", help="What to avoid")
    i2v_parser.add_argument("--duration", "-d", type=int, default=4, help="Video duration in seconds")
    i2v_parser.add_argument("--fps", type=int, default=24, help="Frames per second")
    i2v_parser.add_argument("--motion", "-m", type=float, default=0.5, help="Motion strength 0.0-1.0")

    # Text to video
    t2v_parser = subparsers.add_parser("t2v", help="Generate video from text")
    t2v_parser.add_argument("prompt", nargs="?", help="Video description prompt")
    t2v_parser.add_argument("--negative-prompt", "-n", help="What to avoid")
    t2v_parser.add_argument("--duration", "-d", type=int, default=4, help="Video duration")
    t2v_parser.add_argument("--fps", type=int, default=24, help="Frames per second")
    t2v_parser.add_argument("--aspect-ratio", "-a", default="16:9", help="Aspect ratio")
    t2v_parser.add_argument("--style", "-s", help="Style preset")

    # Status
    status_parser = subparsers.add_parser("status", help="Check generation status")
    status_parser.add_argument("generation_id", nargs="?", help="Generation ID")
    status_parser.add_argument("--download", "-d", action="store_true", help="Download if complete")

    # Download
    download_parser = subparsers.add_parser("download", help="Download completed video")
    download_parser.add_argument("generation_id", nargs="?", help="Generation ID")
    download_parser.add_argument("--output", "-o", help="Output filename")

    # List
    list_parser = subparsers.add_parser("list", help="List recent generations")
    list_parser.add_argument("--limit", "-l", type=int, default=20, help="Number of items")

    # Wait (submit and wait for completion)
    wait_parser = subparsers.add_parser("wait", help="Wait for generation and download")
    wait_parser.add_argument("generation_id", nargs="?", help="Generation ID")
    wait_parser.add_argument("--timeout", "-t", type=int, default=60, help="Max wait attempts (5 sec each)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "setup": cmd_setup,
        "i2v": cmd_image_to_video,
        "t2v": cmd_text_to_video,
        "status": cmd_status,
        "download": cmd_download,
        "list": cmd_list,
        "wait": cmd_wait,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
