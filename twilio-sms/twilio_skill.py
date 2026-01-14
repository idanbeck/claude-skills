#!/usr/bin/env python3
"""
SMS Skill - Send and receive SMS/MMS via Twilio.

Usage:
    python sms_skill.py send PHONE -m "message" [--media FILE]
    python sms_skill.py inbox [--limit N]
    python sms_skill.py history PHONE [--limit N]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Check for required library
try:
    from twilio.rest import Client
except ImportError:
    print("Error: twilio not installed.")
    print("Install with: pip install twilio")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
INBOX_FILE = SKILL_DIR / "inbox.jsonl"
CONVERSATIONS_FILE = SKILL_DIR / "conversations.json"


def load_config() -> Dict:
    """Load Twilio configuration."""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "error": "No config file found",
            "setup_required": True,
            "instructions": "Create config.json with account_sid, auth_token, phone_number, allowed_numbers"
        }, indent=2))
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_client() -> Client:
    """Get Twilio client."""
    config = load_config()
    return Client(config["account_sid"], config["auth_token"])


def format_phone(phone: str) -> str:
    """Ensure phone number is in E.164 format."""
    phone = phone.strip()
    if not phone.startswith("+"):
        # Assume US number if no country code
        phone = "+1" + phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    return phone


def cmd_send(args):
    """Send an SMS or MMS."""
    config = load_config()
    client = get_client()

    to_number = format_phone(args.phone)
    from_number = config["phone_number"]

    # Build message params
    params = {
        "to": to_number,
        "from_": from_number,
        "body": args.message,
    }

    # Add media if provided (MMS)
    if args.media:
        media_path = Path(args.media)
        if not media_path.exists():
            print(json.dumps({"error": f"Media file not found: {args.media}"}))
            sys.exit(1)
        # For MMS, we need a publicly accessible URL
        # Twilio can't fetch local files directly
        # We'd need to upload to a hosting service first
        # For now, support URLs directly
        if args.media.startswith("http"):
            params["media_url"] = [args.media]
        else:
            print(json.dumps({
                "error": "Local media files not directly supported",
                "hint": "Upload to a public URL first, or use a URL directly",
                "media_path": str(media_path)
            }))
            sys.exit(1)

    try:
        message = client.messages.create(**params)
        print(json.dumps({
            "success": True,
            "sid": message.sid,
            "to": to_number,
            "from": from_number,
            "body": args.message[:100] + "..." if len(args.message) > 100 else args.message,
            "status": message.status,
        }, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


def cmd_inbox(args):
    """Show recent inbox messages."""
    if not INBOX_FILE.exists():
        print(json.dumps({"messages": [], "info": "No messages yet"}))
        return

    messages = []
    with open(INBOX_FILE) as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))

    # Get last N messages
    recent = messages[-args.limit:]

    print(json.dumps({
        "messages": recent,
        "total": len(messages),
        "showing": len(recent),
    }, indent=2))


def cmd_history(args):
    """Show conversation history with a specific number."""
    phone = format_phone(args.phone)

    if not INBOX_FILE.exists():
        print(json.dumps({"messages": [], "info": "No messages yet"}))
        return

    messages = []
    with open(INBOX_FILE) as f:
        for line in f:
            if line.strip():
                msg = json.loads(line)
                if msg.get("from") == phone or msg.get("to") == phone:
                    messages.append(msg)

    # Get last N messages
    recent = messages[-args.limit:]

    print(json.dumps({
        "phone": phone,
        "messages": recent,
        "total": len(messages),
        "showing": len(recent),
    }, indent=2))


def cmd_status(args):
    """Check Twilio account status."""
    config = load_config()
    client = get_client()

    try:
        account = client.api.accounts(config["account_sid"]).fetch()
        print(json.dumps({
            "status": account.status,
            "friendly_name": account.friendly_name,
            "phone_number": config["phone_number"],
            "allowed_numbers": config.get("allowed_numbers", []),
        }, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SMS Skill - Send and receive SMS via Twilio"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Send
    sub = subparsers.add_parser("send", help="Send an SMS/MMS")
    sub.add_argument("phone", help="Phone number to send to")
    sub.add_argument("-m", "--message", required=True, help="Message text")
    sub.add_argument("--media", help="Media URL for MMS")
    sub.set_defaults(func=cmd_send)

    # Inbox
    sub = subparsers.add_parser("inbox", help="Show recent inbox messages")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of messages")
    sub.set_defaults(func=cmd_inbox)

    # History
    sub = subparsers.add_parser("history", help="Show conversation history with a number")
    sub.add_argument("phone", help="Phone number")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of messages")
    sub.set_defaults(func=cmd_history)

    # Status
    sub = subparsers.add_parser("status", help="Check Twilio account status")
    sub.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
