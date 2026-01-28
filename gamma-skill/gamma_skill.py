#!/usr/bin/env python3
"""Gamma Skill - Presentation/document generation via Gamma API.

Generate presentations, documents, webpages, and social content from text.
Supports themes, templates, and PDF/PPTX export.

Usage:
    python gamma_skill.py generate "Your content here" --format presentation
    python gamma_skill.py themes
    python gamma_skill.py status GENERATION_ID
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, Union

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
API_BASE = "https://public-api.gamma.app/v1.0"

# Default preferences
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"  # Gemini - similar to nano-banana
PREFERRED_THEMES = ["zerg", "zerg-ai", "epoch"]  # Auto-detect these themes


def load_config() -> Dict:
    """Load API key from config."""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "error": "No config file found",
            "setup_required": True,
            "instructions": [
                "1. Go to Gamma Settings > Members > API key tab",
                "2. Create a new API key (requires Pro/Ultra/Teams/Business account)",
                f"3. Save: echo '{{\"api_key\": \"sk-gamma-xxx\"}}' > {CONFIG_FILE}"
            ]
        }, indent=2))
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    if not config.get("api_key"):
        print(json.dumps({
            "error": "No api_key in config file",
            "instructions": [
                "Add your API key to config.json:",
                '{"api_key": "sk-gamma-xxxxxxxx"}'
            ]
        }, indent=2))
        sys.exit(1)

    return config


def api_request(method: str, endpoint: str, data: Optional[Dict] = None) -> Union[Dict, list]:
    """Make authenticated API request to Gamma."""
    config = load_config()
    url = f"{API_BASE}{endpoint}"

    headers = {
        "X-API-KEY": config["api_key"],
        "Content-Type": "application/json",
        "User-Agent": "GammaSkill/1.0 (Claude Code Integration)"
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            response_text = response.read().decode()
            if not response_text:
                return {}
            return json.loads(response_text)
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode() if e.fp else str(e)
        except:
            error_body = str(e)

        # Try to parse error as JSON
        try:
            error_json = json.loads(error_body)
            print(json.dumps({
                "error": f"HTTP {e.code}",
                "message": error_json.get("message", error_body),
                "details": error_json
            }, indent=2))
        except:
            print(json.dumps({
                "error": f"HTTP {e.code}",
                "details": error_body
            }, indent=2))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(json.dumps({
            "error": "Network error",
            "details": str(e.reason)
        }, indent=2))
        sys.exit(1)


def poll_until_complete(generation_id: str, interval: int = 5, timeout: int = 300, verbose: bool = False) -> Dict:
    """Poll generation status until complete or timeout."""
    start = time.time()
    attempts = 0

    while time.time() - start < timeout:
        attempts += 1
        result = api_request("GET", f"/generations/{generation_id}")

        status = result.get("status")
        if verbose and attempts > 1:
            elapsed = int(time.time() - start)
            print(json.dumps({"polling": True, "attempt": attempts, "elapsed_seconds": elapsed, "status": status}), file=sys.stderr)

        if status == "completed":
            return result
        if status == "failed":
            return {"error": "Generation failed", "details": result}

        time.sleep(interval)

    return {"error": "Timeout waiting for generation", "generation_id": generation_id, "timeout_seconds": timeout}


def find_preferred_theme() -> Optional[str]:
    """Check for preferred themes (zerg, etc.) and return theme ID if found."""
    try:
        result = api_request("GET", "/themes")
        themes = result.get("data", []) if isinstance(result, dict) else result

        for theme in themes:
            theme_id = theme.get("id", "").lower()
            theme_name = theme.get("name", "").lower()

            for preferred in PREFERRED_THEMES:
                if preferred in theme_id or preferred in theme_name:
                    return theme.get("id")

        return None
    except:
        return None


# Command handlers

def cmd_generate(args):
    """Generate presentation/document from text."""
    # Read input text from file or use directly
    input_text = args.text
    if args.file:
        try:
            with open(args.file) as f:
                input_text = f.read()
        except FileNotFoundError:
            print(json.dumps({"error": f"File not found: {args.file}"}))
            sys.exit(1)

    if not input_text:
        print(json.dumps({"error": "No input text provided. Use positional argument or --file"}))
        sys.exit(1)

    # Auto-detect theme if not specified
    theme_id = args.theme
    if not theme_id and args.auto_theme:
        theme_id = find_preferred_theme()
        if theme_id:
            print(json.dumps({"info": f"Auto-detected theme: {theme_id}"}), file=sys.stderr)

    # Build request data
    data = {
        "inputText": input_text,
        "textMode": args.text_mode,
        "format": args.format,
    }

    # Optional parameters
    if theme_id:
        data["themeId"] = theme_id
    if args.num_cards:
        data["numCards"] = args.num_cards
    if args.instructions:
        data["additionalInstructions"] = args.instructions
    if args.export_as:
        data["exportAs"] = args.export_as
    if args.folder:
        data["folderIds"] = [args.folder]

    # Text options
    text_opts = {}
    if args.tone:
        text_opts["tone"] = args.tone
    if args.audience:
        text_opts["audience"] = args.audience
    if args.language:
        text_opts["language"] = args.language
    if args.text_amount:
        text_opts["amount"] = args.text_amount
    if text_opts:
        data["textOptions"] = text_opts

    # Image options
    image_opts = {}
    if args.image_model:
        image_opts["source"] = "aiGenerated"
        image_opts["model"] = args.image_model
    elif not args.no_images:
        # Default to Gemini (similar to nano-banana)
        image_opts["source"] = "aiGenerated"
        image_opts["model"] = DEFAULT_IMAGE_MODEL
    if args.no_images:
        image_opts["source"] = "noImages"
    if args.image_style:
        image_opts["style"] = args.image_style
    if image_opts:
        data["imageOptions"] = image_opts

    # Note: aspectRatio is not currently supported by the API (returns 400)
    # 16:9 is the default. Keep the arg for future API support but don't send it.
    # if args.aspect_ratio:
    #     data["cardOptions"] = {"aspectRatio": args.aspect_ratio}

    # Make the generation request
    result = api_request("POST", "/generations", data)
    generation_id = result.get("generationId")

    if not generation_id:
        print(json.dumps({"error": "No generation ID returned", "response": result}))
        sys.exit(1)

    # If --wait, poll until complete
    if args.wait and generation_id:
        result = poll_until_complete(generation_id, args.poll_interval, args.timeout, verbose=True)

    result["generation_id"] = generation_id
    print(json.dumps(result, indent=2))


def cmd_from_template(args):
    """Create from existing template."""
    data = {
        "gammaId": args.template_id,
        "prompt": args.prompt,
    }

    if args.theme:
        data["themeId"] = args.theme
    if args.folder:
        data["folderIds"] = [args.folder]
    if args.export_as:
        data["exportAs"] = args.export_as

    result = api_request("POST", "/generations-from-template", data)
    generation_id = result.get("generationId")

    if args.wait and generation_id:
        result = poll_until_complete(generation_id, args.poll_interval, args.timeout, verbose=True)

    if generation_id:
        result["generation_id"] = generation_id
    print(json.dumps(result, indent=2))


def cmd_status(args):
    """Check generation status."""
    result = api_request("GET", f"/generations/{args.generation_id}")
    print(json.dumps(result, indent=2))


def cmd_export(args):
    """Get export URLs (PDF/PPTX) for a generation."""
    result = api_request("GET", f"/generations/{args.generation_id}/file-urls")
    print(json.dumps(result, indent=2))


def cmd_themes(args):
    """List available themes."""
    result = api_request("GET", "/themes")
    if args.limit and isinstance(result, list):
        result = result[:args.limit]
    print(json.dumps(result, indent=2))


def cmd_folders(args):
    """List available folders."""
    result = api_request("GET", "/folders")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Gamma Skill - Generate presentations, documents, and webpages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a presentation
  %(prog)s generate "Introduction to AI..." --format presentation --wait

  # Generate from a file
  %(prog)s generate --file notes.md --format document --num-cards 10

  # Create from template
  %(prog)s from-template TEMPLATE_ID "Update with our company info"

  # List themes
  %(prog)s themes

  # Check status
  %(prog)s status GENERATION_ID

  # Get export URLs
  %(prog)s export GENERATION_ID
"""
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate presentation/document from text")
    p_gen.add_argument("text", nargs="?", default="", help="Input text/content")
    p_gen.add_argument("--file", "-F", help="Read input from file instead")
    p_gen.add_argument("--format", "-f", choices=["presentation", "document", "webpage", "social"],
                       default="presentation", help="Output format (default: presentation)")
    p_gen.add_argument("--text-mode", "-m", choices=["generate", "condense", "preserve"],
                       default="generate", help="Text handling mode (default: generate)")
    p_gen.add_argument("--theme", "-t", help="Theme ID to apply (or use --auto-theme)")
    p_gen.add_argument("--auto-theme", "-T", action="store_true",
                       help="Auto-detect preferred theme (zerg, etc.)")
    p_gen.add_argument("--num-cards", "-n", type=int, help="Number of slides/cards (1-60 for Pro)")
    p_gen.add_argument("--instructions", "-i", help="Additional instructions (max 2000 chars)")
    p_gen.add_argument("--export-as", "-e", choices=["pdf", "pptx"], help="Also export as PDF/PPTX")
    p_gen.add_argument("--folder", help="Folder ID to save to")
    p_gen.add_argument("--tone", help="Content tone (e.g., professional, casual)")
    p_gen.add_argument("--audience", help="Target audience")
    p_gen.add_argument("--language", help="Output language")
    p_gen.add_argument("--text-amount", choices=["less", "default", "more"], help="Text amount per card")
    p_gen.add_argument("--image-style", help="AI image style description")
    p_gen.add_argument("--image-model", help="AI image model (default: gemini-2.5-flash-image)")
    p_gen.add_argument("--no-images", action="store_true", help="Disable AI image generation")
    p_gen.add_argument("--aspect-ratio", choices=["16:9", "4:3", "1:1", "9:16"], help="Card aspect ratio")
    p_gen.add_argument("--wait", "-w", action="store_true", help="Wait for completion")
    p_gen.add_argument("--poll-interval", type=int, default=5, help="Seconds between status checks (default: 5)")
    p_gen.add_argument("--timeout", type=int, default=300, help="Max wait time in seconds (default: 300)")
    p_gen.set_defaults(func=cmd_generate)

    # from-template
    p_tmpl = subparsers.add_parser("from-template", help="Create from existing template")
    p_tmpl.add_argument("template_id", help="Template/Gamma ID to use")
    p_tmpl.add_argument("prompt", help="Content/instructions for the template")
    p_tmpl.add_argument("--theme", "-t", help="Theme ID to apply")
    p_tmpl.add_argument("--folder", help="Folder ID to save to")
    p_tmpl.add_argument("--export-as", "-e", choices=["pdf", "pptx"], help="Also export as PDF/PPTX")
    p_tmpl.add_argument("--wait", "-w", action="store_true", help="Wait for completion")
    p_tmpl.add_argument("--poll-interval", type=int, default=5, help="Seconds between status checks")
    p_tmpl.add_argument("--timeout", type=int, default=300, help="Max wait time in seconds")
    p_tmpl.set_defaults(func=cmd_from_template)

    # status
    p_status = subparsers.add_parser("status", help="Check generation status")
    p_status.add_argument("generation_id", help="Generation ID to check")
    p_status.set_defaults(func=cmd_status)

    # export
    p_export = subparsers.add_parser("export", help="Get export URLs (PDF/PPTX)")
    p_export.add_argument("generation_id", help="Generation ID")
    p_export.set_defaults(func=cmd_export)

    # themes
    p_themes = subparsers.add_parser("themes", help="List available themes")
    p_themes.add_argument("--limit", "-l", type=int, help="Limit number of results")
    p_themes.set_defaults(func=cmd_themes)

    # folders
    p_folders = subparsers.add_parser("folders", help="List available folders")
    p_folders.set_defaults(func=cmd_folders)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
