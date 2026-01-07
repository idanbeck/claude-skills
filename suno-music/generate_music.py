#!/usr/bin/env python3
"""
Suno Music Generation Script
Generates music using Suno AI's API directly.
"""

import argparse
import os
import sys
import re
import json
import time
import random
from datetime import datetime
from pathlib import Path
import requests


BASE_URL = "https://studio-api.prod.suno.com"


def sanitize_filename(text: str, max_length: int = 50) -> str:
    """Create a safe filename from text."""
    clean = re.sub(r'[^\w\s-]', '', text.lower())
    clean = re.sub(r'\s+', '_', clean)
    return clean[:max_length].rstrip('_')


def get_token() -> str:
    """Get the session token from environment."""
    cookie = os.environ.get("SUNO_COOKIE")
    if not cookie:
        print("Error: SUNO_COOKIE environment variable not set.")
        print("\nTo get your cookie:")
        print("1. Sign in to https://app.suno.ai/")
        print("2. Open DevTools (F12) → Console tab")
        print("3. Run: document.cookie")
        print("4. Find the __session=eyJ... value")
        print("5. Run: export SUNO_COOKIE='__session=eyJ...'")
        sys.exit(1)

    # Extract __session token from cookie string
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('__session='):
            return part.split('=', 1)[1]

    # If no __session found, assume the whole thing is the token
    if cookie.startswith('eyJ'):
        return cookie

    print("Error: Could not find __session token in SUNO_COOKIE")
    print("Make sure the cookie contains __session=eyJ...")
    sys.exit(1)


def api_request(method: str, endpoint: str, token: str, json_data: dict = None) -> dict:
    """Make an authenticated API request."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    url = f"{BASE_URL}{endpoint}"

    if method.upper() == "GET":
        response = requests.get(url, headers=headers)
    else:
        response = requests.post(url, headers=headers, json=json_data)

    if response.status_code != 200:
        print(f"API Error: {response.status_code}")
        print(response.text)
        sys.exit(1)

    return response.json()


def check_credits(token: str) -> None:
    """Display current credit balance."""
    data = api_request("GET", "/api/billing/info/", token)
    print(f"Credits remaining: {data.get('total_credits_left', 'N/A')}")
    print(f"Monthly limit: {data.get('monthly_limit', 'N/A')}")
    print(f"Monthly usage: {data.get('monthly_usage', 'N/A')}")

    # Show available models
    models = data.get('models', [])
    usable = [m for m in models if m.get('can_use')]
    if usable:
        print(f"\nAvailable models:")
        for m in usable:
            badges = ' '.join(f"[{b}]" for b in m.get('badges', []))
            default = " (default)" if m.get('is_default_model') else ""
            print(f"  - {m['name']}: {m['external_key']}{default} {badges}")


def wait_for_clips(clip_ids: list, token: str, timeout: int = 120) -> list:
    """Wait for clips to finish generating."""
    start = time.time()
    while time.time() - start < timeout:
        ids_str = ",".join(clip_ids)
        data = api_request("GET", f"/api/feed/?ids={ids_str}", token)

        all_done = True
        for clip in data:
            status = clip.get('status', '')
            if status not in ['streaming', 'complete']:
                all_done = False
                break

        if all_done:
            return data

        print("  Waiting for generation...")
        time.sleep(random.uniform(3, 6))

    print("  Timeout waiting for clips")
    return data


def download_clip(clip: dict, output_dir: Path, timestamp: str, index: int) -> str:
    """Download a clip to the output directory."""
    audio_url = clip.get('audio_url')
    if not audio_url:
        print(f"  No audio URL for clip {clip.get('id')}")
        return None

    title = clip.get('title') or 'untitled'
    safe_title = sanitize_filename(title)
    filename = f"{timestamp}_{safe_title}_{index}.mp3"
    filepath = output_dir / filename

    print(f"  Downloading: {title}")
    response = requests.get(audio_url, stream=True)
    response.raise_for_status()

    with open(filepath, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return str(filepath)


def generate_music(
    prompt: str,
    is_custom: bool = False,
    tags: str = None,
    title: str = None,
    instrumental: bool = False,
    output_dir: str = "./generated_music",
    model: str = None
) -> list:
    """Generate music and download the results."""

    token = get_token()

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Build payload
    payload = {
        "make_instrumental": instrumental,
        "prompt": ""
    }

    if model:
        payload["mv"] = model

    if is_custom:
        payload["tags"] = tags or ""
        payload["title"] = title or ""
        payload["prompt"] = prompt
    else:
        payload["gpt_description_prompt"] = prompt

    print(f"Generating music...")
    print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    if tags:
        print(f"  Tags: {tags}")
    if title:
        print(f"  Title: {title}")
    if instrumental:
        print(f"  Mode: Instrumental")

    # Generate
    data = api_request("POST", "/api/generate/v2/", token, payload)

    clips = data.get('clips', [])
    if not clips:
        print("Error: No clips returned")
        sys.exit(1)

    clip_ids = [c['id'] for c in clips]
    print(f"  Generated {len(clip_ids)} clip(s), waiting for audio...")

    # Wait for completion
    completed_clips = wait_for_clips(clip_ids, token)

    # Download
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    downloaded = []

    for i, clip in enumerate(completed_clips):
        filepath = download_clip(clip, output_path, timestamp, i + 1)
        if filepath:
            downloaded.append(filepath)
            print(f"  Saved: {filepath}")

    return downloaded


def main():
    parser = argparse.ArgumentParser(
        description="Generate music using Suno AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Generate from description:
    %(prog)s "upbeat electronic track for a tech demo"

  Custom lyrics with style:
    %(prog)s "[Verse] Walking in the light" --custom --tags "indie folk" --title "Morning"

  Instrumental:
    %(prog)s "epic orchestral trailer music" --instrumental

  Check credits:
    %(prog)s --credits
"""
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="Music description or lyrics (if --custom)"
    )

    parser.add_argument(
        "--custom",
        action="store_true",
        help="Treat prompt as lyrics instead of description"
    )

    parser.add_argument(
        "--tags",
        type=str,
        help="Style/voice tags (e.g., 'female voice, pop, upbeat')"
    )

    parser.add_argument(
        "--title",
        type=str,
        help="Song title"
    )

    parser.add_argument(
        "--instrumental",
        action="store_true",
        help="Generate instrumental only (no vocals)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="./generated_music",
        help="Output directory (default: ./generated_music)"
    )

    parser.add_argument(
        "--model",
        type=str,
        help="Model external key (e.g., chirp-auk-turbo)"
    )

    parser.add_argument(
        "--credits",
        action="store_true",
        help="Check remaining credits and exit"
    )

    args = parser.parse_args()

    # Handle credits check
    if args.credits:
        token = get_token()
        check_credits(token)
        sys.exit(0)

    # Require prompt for generation
    if not args.prompt:
        parser.error("prompt is required for music generation (use --credits to check balance)")

    # Generate music
    files = generate_music(
        prompt=args.prompt,
        is_custom=args.custom,
        tags=args.tags,
        title=args.title,
        instrumental=args.instrumental,
        output_dir=args.output,
        model=args.model
    )

    if files:
        print(f"\n{'='*50}")
        print(f"Successfully generated {len(files)} file(s):")
        for f in files:
            print(f"  {f}")


if __name__ == "__main__":
    main()
