#!/usr/bin/env python3
"""
Slack Bridge - Real-time connection between Slack and Claude Code.

Listens for incoming Slack messages via Socket Mode and writes them to
an inbox file. Claude Code can read the inbox and respond.

Usage:
    python slack_bridge.py              # Run the bridge (foreground)
    python slack_bridge.py --auto       # Auto-respond using Claude Code
    python slack_bridge.py --daemon     # Run in background
    python slack_bridge.py --status     # Check if running
    python slack_bridge.py --stop       # Stop the daemon
    python slack_bridge.py --inbox      # Show recent inbox messages
    python slack_bridge.py --reply CH TS "message"  # Reply to a message
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event

# Global config for auto-responder
AUTO_RESPOND = False
WORK_DIR = None
ALLOWED_USERS = {"U04R0EJACMR"}  # Idan only - add user IDs to allow others
USER_SESSIONS = {}  # Track session IDs per user for continuity

# Check for required library
try:
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
except ImportError:
    print("Error: slack_sdk not installed or missing socket mode support.")
    print("Install with: pip install 'slack_sdk[socket_mode]'")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
INBOX_FILE = SKILL_DIR / "inbox.jsonl"
PID_FILE = SKILL_DIR / ".bridge.pid"


def load_config():
    """Load configuration."""
    if not CONFIG_FILE.exists():
        print(json.dumps({"error": "No config file found"}))
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_tokens(workspace: str = "default"):
    """Get bot and app tokens for workspace."""
    config = load_config()
    ws_config = config.get(workspace, config.get("default", {}))
    return ws_config.get("token"), ws_config.get("app_token")


def write_to_inbox(message: dict):
    """Append a message to the inbox file."""
    message["received_at"] = datetime.now().isoformat()
    with open(INBOX_FILE, "a") as f:
        f.write(json.dumps(message) + "\n")


def run_claude_code(prompt: str, user_name: str, channel_name: str, user_id: str) -> str:
    """Run Claude Code with a prompt and return the response."""
    global WORK_DIR, USER_SESSIONS

    # Build context-aware prompt (only for new sessions)
    # For continuing sessions, just send the message directly
    if user_id in USER_SESSIONS:
        full_prompt = prompt
    else:
        full_prompt = f"""You are responding to Slack messages from {user_name}. Keep responses concise and conversational (Slack-appropriate).

You have full access to this workspace including Obsidian vault, skills, and tools. You can read files, send emails, etc.

When the user confirms something (like "yes", "do it", "send it"), execute the action you proposed.

First message: {prompt}"""

    try:
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]

        # Continue existing session if we have one for this user
        if user_id in USER_SESSIONS:
            cmd.extend(["--continue"])

        cmd.append(full_prompt)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=WORK_DIR,
            timeout=180,  # 3 minute timeout
        )

        # Try to extract session ID from output for future continuation
        # Claude Code outputs session info we could parse

        response = result.stdout.strip()
        if not response and result.stderr:
            response = f"Error: {result.stderr[:500]}"

        # Mark that this user has an active session
        USER_SESSIONS[user_id] = True

        return response or "I processed that but have no response."
    except subprocess.TimeoutExpired:
        return "Sorry, that took too long to process."
    except Exception as e:
        return f"Error running Claude Code: {str(e)[:200]}"


def send_slack_response(web_client: WebClient, channel: str, text: str, thread_ts: str = None):
    """Send a response back to Slack."""
    try:
        # Slack has a 4000 char limit per message, split if needed
        max_len = 3900
        if len(text) <= max_len:
            web_client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
            )
        else:
            # Split into chunks
            chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for i, chunk in enumerate(chunks):
                prefix = f"({i+1}/{len(chunks)}) " if len(chunks) > 1 else ""
                web_client.chat_postMessage(
                    channel=channel,
                    text=prefix + chunk,
                    thread_ts=thread_ts,
                )
    except Exception as e:
        print(f"Error sending Slack response: {e}")


def handle_message(client: SocketModeClient, req: SocketModeRequest, web_client: WebClient):
    """Handle incoming message events."""
    if req.type == "events_api":
        # Acknowledge the request immediately
        response = SocketModeResponse(envelope_id=req.envelope_id)
        client.send_socket_mode_response(response)

        event = req.payload.get("event", {})
        event_type = event.get("type")

        # Handle DMs and mentions
        if event_type == "message" and "subtype" not in event:
            # Skip bot's own messages
            if event.get("bot_id"):
                return

            channel = event.get("channel")
            user = event.get("user")
            text = event.get("text", "")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")

            # Get user info if possible
            user_name = user
            try:
                user_info = web_client.users_info(user=user)
                user_name = user_info["user"].get("real_name") or user_info["user"].get("name") or user
            except:
                pass

            # Get channel info
            channel_name = channel
            try:
                if channel.startswith("D"):
                    channel_name = f"DM:{user_name}"
                else:
                    channel_info = web_client.conversations_info(channel=channel)
                    channel_name = f"#{channel_info['channel']['name']}"
            except:
                pass

            inbox_msg = {
                "type": "message",
                "channel_id": channel,
                "channel": channel_name,
                "user_id": user,
                "user": user_name,
                "text": text,
                "ts": ts,
                "thread_ts": thread_ts,
            }

            write_to_inbox(inbox_msg)

            # Print to console
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] New message from {user_name} in {channel_name}")
            print(f"  {text}")

            # Check if user is allowed
            if ALLOWED_USERS and user not in ALLOWED_USERS:
                print(f"  [User {user} not in allowed list, ignoring]")
                print(f"{'='*60}\n")
                return

            # Auto-respond if enabled
            if AUTO_RESPOND:
                print(f"  [Auto-responding via Claude Code...]")
                response = run_claude_code(text, user_name, channel_name, user)
                print(f"  Response: {response[:100]}{'...' if len(response) > 100 else ''}")
                # Reply directly in chat, not in thread
                send_slack_response(web_client, channel, response, None)
            else:
                print(f"  Reply: python slack_bridge.py --reply {channel} {ts} \"your message\"")

            print(f"{'='*60}\n")

        elif event_type == "app_mention":
            channel = event.get("channel")
            user = event.get("user")
            text = event.get("text", "")
            ts = event.get("ts")

            inbox_msg = {
                "type": "mention",
                "channel_id": channel,
                "user_id": user,
                "text": text,
                "ts": ts,
            }

            write_to_inbox(inbox_msg)
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Mentioned by {user} in {channel}: {text}\n")


def run_bridge(workspace: str = "default", auto_respond: bool = False, work_dir: str = None):
    """Run the Socket Mode bridge."""
    global AUTO_RESPOND, WORK_DIR
    AUTO_RESPOND = auto_respond
    WORK_DIR = work_dir or os.getcwd()

    bot_token, app_token = get_tokens(workspace)

    if not app_token:
        print("Error: No app_token found in config. Add your xapp- token.")
        sys.exit(1)

    web_client = WebClient(token=bot_token)
    socket_client = SocketModeClient(app_token=app_token, web_client=web_client)

    # Set up message handler
    def handler(client, req):
        handle_message(client, req, web_client)

    socket_client.socket_mode_request_listeners.append(handler)

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    print(f"Slack Bridge started for workspace: {workspace}")
    print(f"Listening for messages... (PID: {os.getpid()})")
    print(f"Inbox: {INBOX_FILE}")
    if AUTO_RESPOND:
        print(f"Auto-respond: ENABLED (Claude Code in {WORK_DIR})")
    print("Press Ctrl+C to stop\n")

    # Connect and run
    socket_client.connect()

    # Keep running until interrupted
    stop_event = Event()

    def signal_handler(signum, frame):
        print("\nShutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while not stop_event.is_set():
        time.sleep(1)

    socket_client.close()
    if PID_FILE.exists():
        PID_FILE.unlink()


def show_inbox(limit: int = 10):
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
    recent = messages[-limit:]

    print(json.dumps({
        "messages": recent,
        "total": len(messages),
        "showing": len(recent),
    }, indent=2))


def reply_to_message(channel: str, thread_ts: str, text: str, workspace: str = "default"):
    """Reply to a message."""
    bot_token, _ = get_tokens(workspace)
    client = WebClient(token=bot_token)

    try:
        result = client.chat_postMessage(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
        )
        print(json.dumps({
            "success": True,
            "channel": channel,
            "thread_ts": thread_ts,
            "message_ts": result["ts"],
            "text": text,
        }, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


def check_status():
    """Check if bridge is running."""
    if PID_FILE.exists():
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)  # Check if process exists
            print(json.dumps({"running": True, "pid": pid}))
            return True
        except ProcessLookupError:
            PID_FILE.unlink()

    print(json.dumps({"running": False}))
    return False


def stop_bridge():
    """Stop the running bridge."""
    if PID_FILE.exists():
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(json.dumps({"stopped": True, "pid": pid}))
            return
        except ProcessLookupError:
            PID_FILE.unlink()

    print(json.dumps({"stopped": False, "error": "Bridge not running"}))


def main():
    parser = argparse.ArgumentParser(description="Slack Bridge for Claude Code")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="Auto-respond to messages using Claude Code")
    parser.add_argument("--workdir", type=str, default=None,
                        help="Working directory for Claude Code (default: current dir)")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run in background")
    parser.add_argument("--status", "-s", action="store_true", help="Check if running")
    parser.add_argument("--stop", action="store_true", help="Stop the daemon")
    parser.add_argument("--inbox", "-i", action="store_true", help="Show inbox messages")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Number of inbox messages")
    parser.add_argument("--reply", "-r", nargs=3, metavar=("CHANNEL", "TS", "MESSAGE"),
                        help="Reply to a message")
    parser.add_argument("--workspace", "-w", default="default", help="Workspace to use")

    args = parser.parse_args()

    if args.status:
        check_status()
    elif args.stop:
        stop_bridge()
    elif args.inbox:
        show_inbox(args.limit)
    elif args.reply:
        channel, ts, message = args.reply
        reply_to_message(channel, ts, message, args.workspace)
    elif args.daemon:
        # Fork to background
        if os.fork() > 0:
            sys.exit(0)
        os.setsid()
        if os.fork() > 0:
            sys.exit(0)
        # Redirect stdout/stderr
        log_file = SKILL_DIR / "bridge.log"
        sys.stdout = open(log_file, "a")
        sys.stderr = sys.stdout
        run_bridge(args.workspace, args.auto, args.workdir)
    else:
        run_bridge(args.workspace, args.auto, args.workdir)


if __name__ == "__main__":
    main()
