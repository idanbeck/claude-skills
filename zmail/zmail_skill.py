#!/usr/bin/env python3
"""
Zmail Skill - CLI for interacting with Zmail server.

Usage:
    python zmail_skill.py inbox [--mailbox ADDRESS] [--limit N]
    python zmail_skill.py read MESSAGE_ID
    python zmail_skill.py send --to ADDRESS --subject "Subject" --body "Body"
    python zmail_skill.py reply MESSAGE_ID --body "Reply text"
    python zmail_skill.py mailboxes
    python zmail_skill.py create-mailbox ADDRESS [--description DESC]
    python zmail_skill.py stats
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: requests not installed.")
    print("Install with: pip install requests")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"


def load_config() -> dict:
    """Load configuration."""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "error": "No config file found",
            "setup_required": True,
            "instructions": "Create config.json with api_url, api_key, default_mailbox"
        }, indent=2))
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def api_request(method: str, endpoint: str, **kwargs) -> dict:
    """Make an API request to the zmail server."""
    config = load_config()
    url = f"{config['api_url'].rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = e.response.json()
        except:
            error_detail = {"error": str(e)}
        print(json.dumps({"error": str(e), "detail": error_detail}, indent=2))
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(json.dumps({"error": f"Request failed: {e}"}))
        sys.exit(1)


def format_message_summary(msg: dict) -> str:
    """Format a message summary for display."""
    read_marker = " " if msg.get("read") else "*"
    attach = " [+]" if msg.get("has_attachments") else ""
    date = msg.get("received_at", "")[:16].replace("T", " ")
    from_addr = msg.get("from_addr", "unknown")[:30]
    subject = msg.get("subject", "(no subject)")[:50]
    return f"{read_marker} {msg['id']:>5}  {date}  {from_addr:<30}  {subject}{attach}"


def cmd_inbox(args):
    """List inbox messages."""
    config = load_config()
    params = {
        "limit": args.limit,
        "folder": args.folder,
    }
    if args.mailbox:
        params["mailbox"] = args.mailbox

    result = api_request("GET", "/inbox", params=params)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if not result:
        print("No messages.")
        return

    print(f"\n{'':1} {'ID':>5}  {'Date':<16}  {'From':<30}  Subject")
    print("-" * 90)
    for msg in result:
        print(format_message_summary(msg))
    print(f"\n{len(result)} message(s)")


def cmd_read(args):
    """Read a specific message."""
    result = api_request("GET", f"/messages/{args.message_id}")

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"\n{'='*70}")
    print(f"From:    {result.get('from_addr')}")
    print(f"To:      {result.get('to_addr')}")
    print(f"Date:    {result.get('received_at')}")
    print(f"Subject: {result.get('subject')}")
    print(f"{'='*70}")
    print(result.get('body', '(no body)'))
    print(f"{'='*70}\n")


def cmd_send(args):
    """Send an email."""
    config = load_config()

    payload = {
        "to": args.to,
        "subject": args.subject,
        "body": args.body,
    }

    if args.from_mailbox:
        payload["from_mailbox"] = args.from_mailbox

    result = api_request("POST", "/send", json=payload)
    print(json.dumps(result, indent=2))


def cmd_reply(args):
    """Reply to a message."""
    # First get the original message
    original = api_request("GET", f"/messages/{args.message_id}")

    # Build reply
    to_addr = original.get("from_addr")
    subject = original.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    payload = {
        "to": to_addr,
        "subject": subject,
        "body": args.body,
    }

    result = api_request("POST", "/send", json=payload)
    print(json.dumps(result, indent=2))


def cmd_mailboxes(args):
    """List all mailboxes."""
    result = api_request("GET", "/mailboxes")

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("\nMailboxes:")
    print("-" * 50)
    for mb in result:
        desc = f" - {mb.get('description')}" if mb.get('description') else ""
        print(f"  {mb.get('address')}{desc}")
    print()


def cmd_create_mailbox(args):
    """Create a new mailbox."""
    params = {"address": args.address}
    if args.description:
        params["description"] = args.description

    result = api_request("POST", "/mailboxes", params=params)
    print(json.dumps(result, indent=2))


def cmd_delete(args):
    """Delete a message."""
    result = api_request("DELETE", f"/messages/{args.message_id}")
    print(json.dumps(result, indent=2))


def cmd_stats(args):
    """Get mailbox statistics."""
    result = api_request("GET", "/stats")
    print(json.dumps(result, indent=2))


def cmd_health(args):
    """Check server health."""
    config = load_config()
    url = f"{config['api_url'].rstrip('/')}/health"
    try:
        response = requests.get(url, timeout=5)
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Zmail Skill - CLI for Zmail email server"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Inbox
    sub = subparsers.add_parser("inbox", help="List inbox messages")
    sub.add_argument("-m", "--mailbox", help="Filter by mailbox address")
    sub.add_argument("-f", "--folder", default="inbox", help="Folder to list")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of messages")
    sub.add_argument("--json", action="store_true", help="Output as JSON")
    sub.set_defaults(func=cmd_inbox)

    # Read
    sub = subparsers.add_parser("read", help="Read a message")
    sub.add_argument("message_id", type=int, help="Message ID")
    sub.add_argument("--json", action="store_true", help="Output as JSON")
    sub.set_defaults(func=cmd_read)

    # Send
    sub = subparsers.add_parser("send", help="Send an email")
    sub.add_argument("--to", "-t", required=True, help="Recipient address")
    sub.add_argument("--subject", "-s", required=True, help="Subject line")
    sub.add_argument("--body", "-b", required=True, help="Message body")
    sub.add_argument("--from-mailbox", "-f", help="From mailbox (default: server default)")
    sub.set_defaults(func=cmd_send)

    # Reply
    sub = subparsers.add_parser("reply", help="Reply to a message")
    sub.add_argument("message_id", type=int, help="Message ID to reply to")
    sub.add_argument("--body", "-b", required=True, help="Reply body")
    sub.set_defaults(func=cmd_reply)

    # Mailboxes
    sub = subparsers.add_parser("mailboxes", help="List mailboxes")
    sub.add_argument("--json", action="store_true", help="Output as JSON")
    sub.set_defaults(func=cmd_mailboxes)

    # Create mailbox
    sub = subparsers.add_parser("create-mailbox", help="Create a mailbox")
    sub.add_argument("address", help="Email address")
    sub.add_argument("-d", "--description", help="Description")
    sub.set_defaults(func=cmd_create_mailbox)

    # Delete
    sub = subparsers.add_parser("delete", help="Delete a message")
    sub.add_argument("message_id", type=int, help="Message ID")
    sub.set_defaults(func=cmd_delete)

    # Stats
    sub = subparsers.add_parser("stats", help="Get mailbox statistics")
    sub.set_defaults(func=cmd_stats)

    # Health
    sub = subparsers.add_parser("health", help="Check server health")
    sub.set_defaults(func=cmd_health)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
