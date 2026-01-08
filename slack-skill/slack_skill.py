#!/usr/bin/env python3
"""
Slack Skill - Read, search, and send Slack messages.

Supports multiple workspaces with simple token-based auth.

Usage:
    python slack_skill.py channels [--workspace NAME]
    python slack_skill.py users [--workspace NAME]
    python slack_skill.py read CHANNEL [--limit N] [--workspace NAME]
    python slack_skill.py send CHANNEL --message "text" [--thread-ts TS] [--workspace NAME]
    python slack_skill.py search "query" [--limit N] [--workspace NAME]
    python slack_skill.py thread CHANNEL THREAD_TS [--workspace NAME]
    python slack_skill.py user USERNAME_OR_ID [--workspace NAME]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

# Check for required library
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    print("Error: slack_sdk not installed.")
    print("Install with: pip install slack_sdk")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"

# Message line width for readability
MESSAGE_LINE_WIDTH = 72


def load_config() -> Dict:
    """Load workspace configurations."""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "error": "No config file found",
            "setup_required": True,
            "instructions": [
                "1. Create a Slack app at https://api.slack.com/apps",
                "2. Add bot scopes: channels:history, channels:read, chat:write, users:read",
                "3. Install to workspace and copy Bot User OAuth Token",
                f"4. Create config: echo '{{\"default\": {{\"token\": \"xoxb-...\", \"workspace\": \"name\"}}}}' > {CONFIG_FILE}"
            ]
        }, indent=2))
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_client(workspace: Optional[str] = None) -> tuple[WebClient, str]:
    """Get Slack client for specified workspace."""
    config = load_config()

    if workspace and workspace in config:
        ws_config = config[workspace]
    elif "default" in config:
        ws_config = config["default"]
        workspace = "default"
    else:
        # Use first available
        workspace = next(iter(config.keys()))
        ws_config = config[workspace]

    token = ws_config.get("token")
    if not token:
        print(json.dumps({"error": f"No token found for workspace: {workspace}"}))
        sys.exit(1)

    return WebClient(token=token), ws_config.get("workspace", workspace)


def resolve_channel(client: WebClient, channel: str) -> tuple[str, str]:
    """Resolve channel name/mention to ID. Returns (id, name)."""
    # Already an ID
    if channel.startswith("C") or channel.startswith("G") or channel.startswith("D"):
        return channel, channel

    # Strip # or @
    clean = channel.lstrip("#@")

    # Check if it's a user (DM)
    if channel.startswith("@"):
        try:
            # Try to find user
            users = client.users_list()
            for user in users["members"]:
                if user.get("name") == clean or user.get("real_name", "").lower() == clean.lower():
                    # Open DM with user
                    dm = client.conversations_open(users=[user["id"]])
                    return dm["channel"]["id"], f"@{user['name']}"
        except SlackApiError as e:
            pass
        return None, channel

    # It's a channel name
    try:
        # List public channels
        result = client.conversations_list(types="public_channel,private_channel")
        for ch in result["channels"]:
            if ch["name"] == clean:
                return ch["id"], f"#{ch['name']}"

        # Paginate if needed
        while result.get("response_metadata", {}).get("next_cursor"):
            result = client.conversations_list(
                types="public_channel,private_channel",
                cursor=result["response_metadata"]["next_cursor"]
            )
            for ch in result["channels"]:
                if ch["name"] == clean:
                    return ch["id"], f"#{ch['name']}"
    except SlackApiError:
        pass

    return None, channel


def format_timestamp(ts: str) -> str:
    """Convert Slack timestamp to readable format."""
    try:
        dt = datetime.fromtimestamp(float(ts))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return ts


def format_message(msg: Dict, users_cache: Dict = None) -> Dict:
    """Format a message for output."""
    user_id = msg.get("user", "")
    user_name = user_id

    if users_cache and user_id in users_cache:
        user_name = users_cache[user_id]

    return {
        "ts": msg.get("ts"),
        "time": format_timestamp(msg.get("ts", "")),
        "user_id": user_id,
        "user": user_name,
        "text": msg.get("text", ""),
        "thread_ts": msg.get("thread_ts"),
        "reply_count": msg.get("reply_count", 0),
        "reactions": [
            {"name": r["name"], "count": r["count"]}
            for r in msg.get("reactions", [])
        ] if msg.get("reactions") else None,
    }


def build_users_cache(client: WebClient) -> Dict[str, str]:
    """Build a cache of user ID to display name."""
    cache = {}
    try:
        result = client.users_list()
        for user in result["members"]:
            display = user.get("real_name") or user.get("name") or user["id"]
            cache[user["id"]] = display
    except SlackApiError:
        pass
    return cache


# ============ Commands ============

def cmd_channels(args):
    """List channels."""
    client, workspace = get_client(args.workspace)

    try:
        channels = []
        result = client.conversations_list(types="public_channel,private_channel")

        for ch in result["channels"]:
            channels.append({
                "id": ch["id"],
                "name": ch["name"],
                "is_private": ch.get("is_private", False),
                "is_member": ch.get("is_member", False),
                "topic": ch.get("topic", {}).get("value", ""),
                "num_members": ch.get("num_members", 0),
            })

        # Paginate
        while result.get("response_metadata", {}).get("next_cursor"):
            result = client.conversations_list(
                types="public_channel,private_channel",
                cursor=result["response_metadata"]["next_cursor"]
            )
            for ch in result["channels"]:
                channels.append({
                    "id": ch["id"],
                    "name": ch["name"],
                    "is_private": ch.get("is_private", False),
                    "is_member": ch.get("is_member", False),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "num_members": ch.get("num_members", 0),
                })

        print(json.dumps({
            "workspace": workspace,
            "channels": sorted(channels, key=lambda x: x["name"]),
            "total": len(channels),
        }, indent=2))

    except SlackApiError as e:
        print(json.dumps({"error": str(e)}))


def cmd_users(args):
    """List users."""
    client, workspace = get_client(args.workspace)

    try:
        users = []
        result = client.users_list()

        for user in result["members"]:
            if user.get("deleted") or user.get("is_bot"):
                continue
            users.append({
                "id": user["id"],
                "name": user.get("name"),
                "real_name": user.get("real_name"),
                "display_name": user.get("profile", {}).get("display_name"),
                "email": user.get("profile", {}).get("email"),
                "is_admin": user.get("is_admin", False),
            })

        print(json.dumps({
            "workspace": workspace,
            "users": sorted(users, key=lambda x: x.get("real_name") or x.get("name") or ""),
            "total": len(users),
        }, indent=2))

    except SlackApiError as e:
        print(json.dumps({"error": str(e)}))


def cmd_read(args):
    """Read messages from a channel."""
    client, workspace = get_client(args.workspace)

    channel_id, channel_name = resolve_channel(client, args.channel)
    if not channel_id:
        print(json.dumps({"error": f"Channel not found: {args.channel}"}))
        return

    try:
        # Build user cache for display names
        users_cache = build_users_cache(client)

        result = client.conversations_history(
            channel=channel_id,
            limit=args.limit or 20
        )

        messages = [format_message(msg, users_cache) for msg in result["messages"]]

        print(json.dumps({
            "workspace": workspace,
            "channel": channel_name,
            "channel_id": channel_id,
            "messages": list(reversed(messages)),  # Oldest first
            "total": len(messages),
        }, indent=2))

    except SlackApiError as e:
        print(json.dumps({"error": str(e)}))


def cmd_send(args):
    """Send a message to a channel or user."""
    client, workspace = get_client(args.workspace)

    channel_id, channel_name = resolve_channel(client, args.channel)
    if not channel_id:
        print(json.dumps({"error": f"Channel/user not found: {args.channel}"}))
        return

    try:
        kwargs = {
            "channel": channel_id,
            "text": args.message,
        }

        if args.thread_ts:
            kwargs["thread_ts"] = args.thread_ts

        result = client.chat_postMessage(**kwargs)

        print(json.dumps({
            "success": True,
            "workspace": workspace,
            "channel": channel_name,
            "channel_id": channel_id,
            "message_ts": result["ts"],
            "thread_ts": args.thread_ts,
            "text": args.message,
        }, indent=2))

    except SlackApiError as e:
        print(json.dumps({"success": False, "error": str(e)}))


def cmd_search(args):
    """Search messages."""
    client, workspace = get_client(args.workspace)

    try:
        result = client.search_messages(
            query=args.query,
            count=args.limit or 20
        )

        messages = []
        for match in result.get("messages", {}).get("matches", []):
            messages.append({
                "ts": match.get("ts"),
                "time": format_timestamp(match.get("ts", "")),
                "channel": match.get("channel", {}).get("name"),
                "user": match.get("username"),
                "text": match.get("text"),
                "permalink": match.get("permalink"),
            })

        print(json.dumps({
            "workspace": workspace,
            "query": args.query,
            "messages": messages,
            "total": result.get("messages", {}).get("total", 0),
        }, indent=2))

    except SlackApiError as e:
        # search:read scope might not be enabled
        if "missing_scope" in str(e):
            print(json.dumps({
                "error": "Search requires 'search:read' scope",
                "instructions": "Add search:read scope to your Slack app and reinstall"
            }))
        else:
            print(json.dumps({"error": str(e)}))


def cmd_thread(args):
    """Get thread replies."""
    client, workspace = get_client(args.workspace)

    channel_id, channel_name = resolve_channel(client, args.channel)
    if not channel_id:
        print(json.dumps({"error": f"Channel not found: {args.channel}"}))
        return

    try:
        users_cache = build_users_cache(client)

        result = client.conversations_replies(
            channel=channel_id,
            ts=args.thread_ts
        )

        messages = [format_message(msg, users_cache) for msg in result["messages"]]

        print(json.dumps({
            "workspace": workspace,
            "channel": channel_name,
            "thread_ts": args.thread_ts,
            "messages": messages,
            "total": len(messages),
        }, indent=2))

    except SlackApiError as e:
        print(json.dumps({"error": str(e)}))


def cmd_user(args):
    """Get user info."""
    client, workspace = get_client(args.workspace)

    try:
        # Try to find user by name or ID
        user_id = args.user

        if not user_id.startswith("U"):
            # Search by name
            result = client.users_list()
            for user in result["members"]:
                if user.get("name") == args.user.lstrip("@") or \
                   user.get("real_name", "").lower() == args.user.lower():
                    user_id = user["id"]
                    break

        result = client.users_info(user=user_id)
        user = result["user"]

        print(json.dumps({
            "workspace": workspace,
            "id": user["id"],
            "name": user.get("name"),
            "real_name": user.get("real_name"),
            "display_name": user.get("profile", {}).get("display_name"),
            "email": user.get("profile", {}).get("email"),
            "phone": user.get("profile", {}).get("phone"),
            "title": user.get("profile", {}).get("title"),
            "status": user.get("profile", {}).get("status_text"),
            "is_admin": user.get("is_admin", False),
            "is_bot": user.get("is_bot", False),
            "tz": user.get("tz"),
        }, indent=2))

    except SlackApiError as e:
        print(json.dumps({"error": str(e)}))


def cmd_workspaces(args):
    """List configured workspaces."""
    config = load_config()

    workspaces = []
    for key, value in config.items():
        workspaces.append({
            "key": key,
            "workspace": value.get("workspace", key),
            "has_token": bool(value.get("token")),
        })

    print(json.dumps({"workspaces": workspaces}, indent=2))


# ============ Main ============

def main():
    parser = argparse.ArgumentParser(
        description="Slack Skill - Read, search, and send Slack messages"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Workspaces
    sub = subparsers.add_parser("workspaces", help="List configured workspaces")
    sub.set_defaults(func=cmd_workspaces)

    # Channels
    sub = subparsers.add_parser("channels", help="List channels")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_channels)

    # Users
    sub = subparsers.add_parser("users", help="List users")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_users)

    # Read
    sub = subparsers.add_parser("read", help="Read channel messages")
    sub.add_argument("channel", help="Channel (#name or ID) or user (@name)")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of messages")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_read)

    # Send
    sub = subparsers.add_parser("send", help="Send a message (requires confirmation)")
    sub.add_argument("channel", help="Channel (#name or ID) or user (@name)")
    sub.add_argument("-m", "--message", required=True, help="Message text")
    sub.add_argument("-t", "--thread-ts", help="Reply in thread")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_send)

    # Search
    sub = subparsers.add_parser("search", help="Search messages")
    sub.add_argument("query", help="Search query")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of results")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_search)

    # Thread
    sub = subparsers.add_parser("thread", help="Get thread replies")
    sub.add_argument("channel", help="Channel (#name or ID)")
    sub.add_argument("thread_ts", help="Thread timestamp")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_thread)

    # User
    sub = subparsers.add_parser("user", help="Get user info")
    sub.add_argument("user", help="Username or user ID")
    sub.add_argument("-w", "--workspace", help="Workspace to use")
    sub.set_defaults(func=cmd_user)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
