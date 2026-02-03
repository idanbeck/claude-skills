#!/usr/bin/env python3
"""Eleven Labs Skill - AI Voice Generation, Cloning, and Sound Effects."""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime

try:
    from elevenlabs import ElevenLabs, Voice, VoiceSettings
    from elevenlabs.client import ElevenLabs as ElevenLabsClient
except ImportError:
    print(json.dumps({"error": "elevenlabs not installed. Run: pip3 install elevenlabs"}))
    sys.exit(1)

CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / "config.json"
OUTPUT_DIR = CONFIG_DIR / "output"


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


def get_client():
    """Get authenticated ElevenLabs client."""
    config = load_config()
    api_key = config.get('api_key') or os.environ.get('ELEVENLABS_API_KEY')

    if not api_key:
        return None, "API key not configured. Run: python3 eleven_labs_skill.py setup YOUR_API_KEY"

    try:
        client = ElevenLabsClient(api_key=api_key)
        return client, None
    except Exception as e:
        return None, f"Failed to initialize client: {str(e)}"


def cmd_setup(args):
    """Set up API key."""
    if not args.api_key:
        output({
            "error": "API key required",
            "usage": "python3 eleven_labs_skill.py setup YOUR_API_KEY",
            "get_key": "Get your API key at https://elevenlabs.io/api"
        })
        return

    config = load_config()
    config['api_key'] = args.api_key
    save_config(config)

    # Verify the key works
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        # Test by listing voices
        voices = client.voices.get_all()
        output({
            "status": "success",
            "message": "Eleven Labs configured successfully",
            "voices_available": len(voices.voices)
        })
    except Exception as e:
        output({"error": f"API key validation failed: {str(e)}"})


def cmd_voices(args):
    """List available voices."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        response = client.voices.get_all()
        voices = []

        for voice in response.voices:
            voice_info = {
                "voice_id": voice.voice_id,
                "name": voice.name,
                "category": voice.category if hasattr(voice, 'category') else None,
                "labels": voice.labels if hasattr(voice, 'labels') else None,
            }

            # Filter by category if specified
            if args.category:
                if voice_info.get('category') and args.category.lower() in voice_info['category'].lower():
                    voices.append(voice_info)
            else:
                voices.append(voice_info)

        output({"voices": voices, "count": len(voices)})

    except Exception as e:
        output({"error": f"Failed to list voices: {str(e)}"})


def cmd_speak(args):
    """Generate speech from text."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    if not args.text:
        output({"error": "Text required", "usage": "python3 eleven_labs_skill.py speak \"Hello world\""})
        return

    try:
        # Find voice by name or use voice_id directly
        voice_id = args.voice
        if args.voice and not args.voice.startswith("EXA"):  # Not already a voice ID
            response = client.voices.get_all()
            for v in response.voices:
                if args.voice.lower() in v.name.lower():
                    voice_id = v.voice_id
                    break

        # Default to Rachel if no voice specified
        if not voice_id:
            voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel

        # Generate audio
        audio = client.generate(
            text=args.text,
            voice=voice_id,
            model=args.model or "eleven_monolingual_v1"
        )

        # Save to file
        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"speech_{timestamp}.mp3"
        filepath = OUTPUT_DIR / filename

        with open(filepath, 'wb') as f:
            for chunk in audio:
                f.write(chunk)

        output({
            "status": "success",
            "file": str(filepath),
            "text": args.text[:100] + "..." if len(args.text) > 100 else args.text,
            "voice": voice_id
        })

    except Exception as e:
        output({"error": f"Speech generation failed: {str(e)}"})


def cmd_clone(args):
    """Clone a voice from audio samples."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    if not args.name or not args.files:
        output({
            "error": "Name and audio files required",
            "usage": "python3 eleven_labs_skill.py clone \"Voice Name\" file1.mp3 file2.mp3"
        })
        return

    try:
        # Read audio files
        audio_files = []
        for file_path in args.files:
            path = Path(file_path)
            if not path.exists():
                output({"error": f"File not found: {file_path}"})
                return
            audio_files.append(open(path, 'rb'))

        # Create cloned voice
        voice = client.clone(
            name=args.name,
            description=args.description or f"Cloned voice: {args.name}",
            files=audio_files
        )

        # Close files
        for f in audio_files:
            f.close()

        output({
            "status": "success",
            "voice_id": voice.voice_id,
            "name": voice.name,
            "message": f"Voice '{args.name}' cloned successfully"
        })

    except Exception as e:
        output({"error": f"Voice cloning failed: {str(e)}"})


def cmd_sfx(args):
    """Generate sound effects from text description."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    if not args.description:
        output({
            "error": "Description required",
            "usage": "python3 eleven_labs_skill.py sfx \"thunder rolling in the distance\""
        })
        return

    try:
        # Generate sound effect
        audio = client.text_to_sound_effects.convert(
            text=args.description,
            duration_seconds=args.duration or 5.0
        )

        # Save to file
        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Create safe filename from description
        safe_desc = "".join(c if c.isalnum() else "_" for c in args.description[:30])
        filename = f"sfx_{safe_desc}_{timestamp}.mp3"
        filepath = OUTPUT_DIR / filename

        with open(filepath, 'wb') as f:
            for chunk in audio:
                f.write(chunk)

        output({
            "status": "success",
            "file": str(filepath),
            "description": args.description,
            "duration": args.duration or 5.0
        })

    except Exception as e:
        output({"error": f"Sound effect generation failed: {str(e)}"})


def cmd_models(args):
    """List available models."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        models = client.models.get_all()
        model_list = []

        for model in models:
            model_list.append({
                "model_id": model.model_id,
                "name": model.name,
                "description": model.description if hasattr(model, 'description') else None,
                "can_do_text_to_speech": model.can_do_text_to_speech if hasattr(model, 'can_do_text_to_speech') else None,
                "languages": [lang.language_id for lang in model.languages] if hasattr(model, 'languages') and model.languages else None
            })

        output({"models": model_list, "count": len(model_list)})

    except Exception as e:
        output({"error": f"Failed to list models: {str(e)}"})


def cmd_history(args):
    """Get generation history."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        history = client.history.get_all(page_size=args.limit or 20)
        items = []

        for item in history.history:
            items.append({
                "history_item_id": item.history_item_id,
                "voice_name": item.voice_name if hasattr(item, 'voice_name') else None,
                "text": item.text[:100] + "..." if len(item.text) > 100 else item.text,
                "date_unix": item.date_unix if hasattr(item, 'date_unix') else None,
                "character_count": item.character_count_change_from if hasattr(item, 'character_count_change_from') else None
            })

        output({"history": items, "count": len(items)})

    except Exception as e:
        output({"error": f"Failed to get history: {str(e)}"})


def cmd_delete_voice(args):
    """Delete a cloned voice."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    if not args.voice_id:
        output({"error": "Voice ID required", "usage": "python3 eleven_labs_skill.py delete-voice VOICE_ID"})
        return

    try:
        client.voices.delete(voice_id=args.voice_id)
        output({"status": "success", "message": f"Voice {args.voice_id} deleted"})
    except Exception as e:
        output({"error": f"Failed to delete voice: {str(e)}"})


def main():
    parser = argparse.ArgumentParser(description="Eleven Labs Voice Generation")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Setup
    setup_parser = subparsers.add_parser("setup", help="Configure API key")
    setup_parser.add_argument("api_key", nargs="?", help="Eleven Labs API key")

    # List voices
    voices_parser = subparsers.add_parser("voices", help="List available voices")
    voices_parser.add_argument("--category", "-c", help="Filter by category (premade, cloned, etc)")

    # Generate speech
    speak_parser = subparsers.add_parser("speak", help="Generate speech from text")
    speak_parser.add_argument("text", nargs="?", help="Text to speak")
    speak_parser.add_argument("--voice", "-v", help="Voice name or ID")
    speak_parser.add_argument("--model", "-m", help="Model to use")
    speak_parser.add_argument("--file", "-f", help="Read text from file")

    # Clone voice
    clone_parser = subparsers.add_parser("clone", help="Clone a voice from audio samples")
    clone_parser.add_argument("name", nargs="?", help="Name for the cloned voice")
    clone_parser.add_argument("files", nargs="*", help="Audio files to use for cloning")
    clone_parser.add_argument("--description", "-d", help="Voice description")

    # Sound effects
    sfx_parser = subparsers.add_parser("sfx", help="Generate sound effects")
    sfx_parser.add_argument("description", nargs="?", help="Description of the sound effect")
    sfx_parser.add_argument("--duration", "-d", type=float, default=5.0, help="Duration in seconds")

    # List models
    subparsers.add_parser("models", help="List available models")

    # History
    history_parser = subparsers.add_parser("history", help="Get generation history")
    history_parser.add_argument("--limit", "-l", type=int, default=20, help="Number of items")

    # Delete voice
    delete_parser = subparsers.add_parser("delete-voice", help="Delete a cloned voice")
    delete_parser.add_argument("voice_id", nargs="?", help="Voice ID to delete")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "setup": cmd_setup,
        "voices": cmd_voices,
        "speak": cmd_speak,
        "clone": cmd_clone,
        "sfx": cmd_sfx,
        "models": cmd_models,
        "history": cmd_history,
        "delete-voice": cmd_delete_voice,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
