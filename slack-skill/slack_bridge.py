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
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Thread

# Global config for auto-responder
AUTO_RESPOND = False
WORK_DIR = None
ALLOWED_USERS = {"U04R0EJACMR"}  # Idan only - add user IDs to allow others
USER_SESSIONS = {}  # Track session IDs per user for continuity
ACTIVE_THREADS = {}  # Track threads we've posted to: {thread_ts: {channel, last_response_ts}}
PENDING_WORK = {}  # Track messages with hourglass: {(channel, ts): {"start_time": float, "text": str, ...}}
PENDING_WORK_FILE = None  # Set after SKILL_DIR is defined

# Emoji constants
EMOJI_WORKING = "hourglass_flowing_sand"
EMOJI_DONE = "white_check_mark"
EMOJI_ACK = "eyes"
EMOJI_ERROR = "x"
EMOJI_RETRY = "arrows_counterclockwise"

# Timeout for stuck work items (seconds)
WORK_TIMEOUT = 300  # 5 minutes
CLEANUP_INTERVAL = 300  # Check every 5 minutes

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
PENDING_WORK_FILE = SKILL_DIR / "pending_work.json"  # For persistent pending work tracking


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


def run_claude_code(prompt: str, user_name: str, channel_name: str, user_id: str,
                     channel_id: str = None, thread_ts: str = None) -> str:
    """Run Claude Code with a prompt and return the response."""
    global WORK_DIR, USER_SESSIONS

    # Build thread context for uploads
    thread_flag = f" -t {thread_ts}" if thread_ts else ""
    channel_for_upload = channel_id or "CHANNEL_ID"

    # Build context-aware prompt (only for new sessions)
    # For continuing sessions, just send the message directly
    if user_id in USER_SESSIONS:
        full_prompt = prompt
    else:
        full_prompt = f"""You are responding to Slack messages from {user_name}. Keep responses concise and conversational (Slack-appropriate).

You have full access to this workspace including Obsidian vault, skills, and tools. You can read files, send emails, etc.

When the user confirms something (like "yes", "do it", "send it"), execute the action you proposed.

IMPORTANT CONTEXT:
- Channel ID: {channel_for_upload}
- Thread TS: {thread_ts or "none (post to channel)"}
- ALWAYS respond in the same thread if one exists. Include -t {thread_ts} in upload commands when thread_ts is set.

IMAGE GENERATION: If the user asks for an image, picture, or visual:
1. Generate: python ~/.claude/skills/nano-banana-pro/generate_image.py "prompt" --output /tmp
2. Upload to Slack: python ~/.claude/skills/slack-skill/slack_skill.py upload {channel_for_upload} /tmp/generated_images/[filename].png -m "caption"{thread_flag}

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
            timeout=600,  # 10 minute timeout for image generation tasks
        )

        # Try to extract session ID from output for future continuation
        # Claude Code outputs session info we could parse

        response = result.stdout.strip()
        if not response and result.stderr:
            response = f"Error: {result.stderr[:500]}"

        # Strip thinking tags from response
        response = re.sub(r'<thinking>.*?</thinking>\s*', '', response, flags=re.DOTALL)
        response = response.strip()

        # Mark that this user has an active session
        USER_SESSIONS[user_id] = True

        return response or "I processed that but have no response."
    except subprocess.TimeoutExpired:
        return "Sorry, that took too long to process (10 min timeout)."
    except Exception as e:
        return f"Error running Claude Code: {str(e)[:200]}"


def run_claude_with_progress(web_client: WebClient, channel: str, thread_ts: str,
                              prompt: str, user_name: str, channel_name: str, user_id: str) -> str:
    """Run Claude Code with a progress message that updates with elapsed time."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    # Post initial progress message
    start_time = time.time()
    progress_ts = None

    try:
        result = web_client.chat_postMessage(
            channel=channel,
            text="⏳ Working on your request...",
            thread_ts=thread_ts,
        )
        progress_ts = result["ts"]
    except Exception as e:
        print(f"Error posting progress message: {e}")

    # Run Claude Code in a thread so we can update progress
    response = None
    error = None

    def run_claude():
        nonlocal response, error
        try:
            response = run_claude_code(prompt, user_name, channel_name, user_id,
                                       channel_id=channel, thread_ts=thread_ts)
        except Exception as e:
            error = str(e)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_claude)

        # Update progress message every 15 seconds while waiting
        while not future.done():
            try:
                future.result(timeout=15)  # Wait up to 15 seconds
            except FuturesTimeoutError:
                # Still running - update progress message
                elapsed = int(time.time() - start_time)
                mins, secs = divmod(elapsed, 60)
                time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

                if progress_ts:
                    try:
                        web_client.chat_update(
                            channel=channel,
                            ts=progress_ts,
                            text=f"⏳ Working on your request... ({time_str})",
                        )
                    except Exception as e:
                        print(f"Error updating progress: {e}")

    # Delete progress message
    if progress_ts:
        try:
            web_client.chat_delete(channel=channel, ts=progress_ts)
        except Exception as e:
            print(f"Error deleting progress message: {e}")

    if error:
        return f"Error: {error}"

    return response or "I processed that but have no response."


def send_slack_response(web_client: WebClient, channel: str, text: str, thread_ts: str = None) -> str:
    """Send a response back to Slack. Returns the message timestamp."""
    try:
        # Slack has a 4000 char limit per message, split if needed
        max_len = 3900
        result_ts = None
        if len(text) <= max_len:
            result = web_client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
            )
            result_ts = result["ts"]
        else:
            # Split into chunks
            chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for i, chunk in enumerate(chunks):
                prefix = f"({i+1}/{len(chunks)}) " if len(chunks) > 1 else ""
                result = web_client.chat_postMessage(
                    channel=channel,
                    text=prefix + chunk,
                    thread_ts=thread_ts,
                )
                if i == 0:
                    result_ts = result["ts"]

        # Track this thread if we posted to one
        if thread_ts and result_ts:
            ACTIVE_THREADS[thread_ts] = {"channel": channel, "last_response_ts": result_ts}

        return result_ts
    except Exception as e:
        print(f"Error sending Slack response: {e}")
        return None


def add_reaction(web_client: WebClient, channel: str, ts: str, emoji: str):
    """Add an emoji reaction to a message."""
    try:
        web_client.reactions_add(channel=channel, timestamp=ts, name=emoji)
    except Exception as e:
        # Ignore "already_reacted" errors
        if "already_reacted" not in str(e):
            print(f"Error adding reaction: {e}")


def remove_reaction(web_client: WebClient, channel: str, ts: str, emoji: str):
    """Remove an emoji reaction from a message."""
    try:
        web_client.reactions_remove(channel=channel, timestamp=ts, name=emoji)
    except Exception as e:
        # Ignore "no_reaction" errors
        if "no_reaction" not in str(e):
            print(f"Error removing reaction: {e}")


def should_respond_to_thread_reply(text: str, user_name: str) -> bool:
    """Decide whether to respond to a thread reply or just acknowledge it.

    Returns True if we should respond, False if we should just ack.
    Default to responding - only ack for clear "end of conversation" signals.
    """
    lower = text.lower().strip()

    # Only ACK (don't respond) for clear conversation-ending signals
    ack_only = [
        "thanks", "thank you", "thx", "ty", "cool", "nice", "great",
        "got it", "perfect", "awesome", "ok thanks", "okay thanks",
        "👍", "🙏", "✅"
    ]
    for signal in ack_only:
        if lower == signal or lower.rstrip("!.") == signal:
            return False

    # Respond to everything else in tracked threads
    return True


def load_pending_work():
    """Load pending work from file."""
    global PENDING_WORK
    if PENDING_WORK_FILE.exists():
        try:
            with open(PENDING_WORK_FILE) as f:
                data = json.load(f)
                # Convert string keys back to tuples
                PENDING_WORK = {tuple(k.split("|")): v for k, v in data.items()}
                print(f"[STARTUP] Loaded {len(PENDING_WORK)} pending work items")
        except Exception as e:
            print(f"[STARTUP] Error loading pending work: {e}")
            PENDING_WORK = {}


def save_pending_work():
    """Save pending work to file."""
    try:
        # Convert tuple keys to strings for JSON
        data = {f"{k[0]}|{k[1]}": v for k, v in PENDING_WORK.items()}
        with open(PENDING_WORK_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[ERROR] Failed to save pending work: {e}")


def mark_work_started(channel: str, ts: str, text: str, user_id: str, thread_ts: str = None):
    """Track that we've started working on a message."""
    PENDING_WORK[(channel, ts)] = {
        "start_time": time.time(),
        "text": text,
        "user_id": user_id,
        "thread_ts": thread_ts,
        "channel": channel,
    }
    save_pending_work()


def mark_work_completed(channel: str, ts: str):
    """Mark work as completed (remove from pending)."""
    PENDING_WORK.pop((channel, ts), None)
    save_pending_work()


def cleanup_stuck_work(web_client: WebClient):
    """Check for and clean up stuck work items. Retries once before marking as error."""
    now = time.time()
    stuck_items = []

    for (channel, ts), info in list(PENDING_WORK.items()):
        elapsed = now - info["start_time"]
        if elapsed > WORK_TIMEOUT:
            stuck_items.append((channel, ts, info))

    for channel, ts, info in stuck_items:
        retry_count = info.get("retry_count", 0)

        if retry_count == 0:
            # First timeout - retry
            print(f"\n[CLEANUP] Retrying stuck work item: {info['text'][:50]}... (waited {WORK_TIMEOUT}s)")
            info["retry_count"] = 1
            info["start_time"] = time.time()  # Reset timer for retry
            save_pending_work()

            # Add retry emoji to show we're working on it
            add_reaction(web_client, channel, ts, EMOJI_RETRY)

            # Try to process again
            try:
                user_id = info.get("user_id", "unknown")
                thread_ts = info.get("thread_ts")
                reply_to_thread = thread_ts or ts

                response_text = run_claude_code(info["text"], user_id, channel, user_id,
                                                channel_id=channel, thread_ts=reply_to_thread)

                # Success - send response
                reply_to_thread = thread_ts or ts
                send_slack_response(web_client, channel, response_text, reply_to_thread)

                # Mark complete - remove working and retry emojis, add done
                remove_reaction(web_client, channel, ts, EMOJI_WORKING)
                remove_reaction(web_client, channel, ts, EMOJI_RETRY)
                add_reaction(web_client, channel, ts, EMOJI_DONE)
                mark_work_completed(channel, ts)
                print(f"[CLEANUP] Retry successful!")

            except Exception as e:
                print(f"[CLEANUP] Retry failed: {e}")
                # Remove retry emoji, will be caught on next cleanup cycle as retry_count=1
                remove_reaction(web_client, channel, ts, EMOJI_RETRY)
        else:
            # Already retried - give up
            print(f"\n[CLEANUP] Giving up on stuck work item after retry: {info['text'][:50]}...")
            remove_reaction(web_client, channel, ts, EMOJI_WORKING)
            remove_reaction(web_client, channel, ts, EMOJI_RETRY)
            add_reaction(web_client, channel, ts, EMOJI_ERROR)
            mark_work_completed(channel, ts)

            # Notify in thread
            try:
                thread = info.get("thread_ts") or ts
                web_client.chat_postMessage(
                    channel=channel,
                    text="Sorry, that request failed after retrying. Please try again later.",
                    thread_ts=thread,
                )
            except Exception as e:
                print(f"[CLEANUP] Error sending failure message: {e}")


def run_cleanup_loop(web_client: WebClient, stop_event: Event):
    """Periodically check for stuck work items."""
    while not stop_event.is_set():
        try:
            cleanup_stuck_work(web_client)
        except Exception as e:
            print(f"[CLEANUP] Error in cleanup loop: {e}")
        # Check every 5 minutes
        stop_event.wait(CLEANUP_INTERVAL)


def handle_message(client: SocketModeClient, req: SocketModeRequest, web_client: WebClient):
    """Handle incoming message events."""
    if req.type == "events_api":
        # Acknowledge the request immediately
        response = SocketModeResponse(envelope_id=req.envelope_id)
        client.send_socket_mode_response(response)

        event = req.payload.get("event", {})
        event_type = event.get("type")

        # Handle DMs and thread replies ONLY (not all channel messages)
        # @mentions are handled separately by app_mention event
        if event_type == "message" and "subtype" not in event:
            # Skip bot's own messages
            if event.get("bot_id"):
                return

            channel = event.get("channel")
            user = event.get("user")
            text = event.get("text", "")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")

            # Check if this is a DM (channel starts with D)
            is_dm = channel.startswith("D")

            # Check if this is a reply to a thread we're tracking
            is_tracked_thread_reply = thread_ts and thread_ts in ACTIVE_THREADS

            # IMPORTANT: Only process DMs and tracked thread replies
            # Ignore all other channel messages (those come via app_mention if directed at us)
            if not is_dm and not is_tracked_thread_reply:
                return

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
                if is_dm:
                    channel_name = f"DM:{user_name}"
                else:
                    channel_info = web_client.conversations_info(channel=channel)
                    channel_name = f"#{channel_info['channel']['name']}"
            except:
                pass

            inbox_msg = {
                "type": "thread_reply" if is_tracked_thread_reply else "dm",
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
            msg_type = "Thread reply" if is_tracked_thread_reply else "DM"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg_type} from {user_name} in {channel_name}")
            print(f"  {text}")

            # Check if user is allowed
            if ALLOWED_USERS and user not in ALLOWED_USERS:
                print(f"  [User {user} not in allowed list, ignoring]")
                print(f"{'='*60}\n")
                return

            # Auto-respond if enabled
            if AUTO_RESPOND:
                # For thread replies, decide if we should respond or just ack
                if is_tracked_thread_reply and not should_respond_to_thread_reply(text, user_name):
                    print(f"  [Thread reply - acknowledging without response]")
                    add_reaction(web_client, channel, ts, EMOJI_ACK)
                    print(f"{'='*60}\n")
                    return

                # Add working emoji and track pending work
                add_reaction(web_client, channel, ts, EMOJI_WORKING)
                mark_work_started(channel, ts, text, user, thread_ts)

                # Reply in thread if this was a thread reply, otherwise in channel
                reply_thread_ts = thread_ts if is_tracked_thread_reply else None

                print(f"  [Auto-responding via Claude Code...]")
                response_text = run_claude_with_progress(
                    web_client, channel, reply_thread_ts,
                    text, user_name, channel_name, user
                )
                print(f"  Response: {response_text[:100]}{'...' if len(response_text) > 100 else ''}")

                response_ts = send_slack_response(web_client, channel, response_text, reply_thread_ts)

                # Remove working emoji, add done emoji, mark completed
                remove_reaction(web_client, channel, ts, EMOJI_WORKING)
                add_reaction(web_client, channel, ts, EMOJI_DONE)
                mark_work_completed(channel, ts)

                # Track this as an active thread if we started one
                if response_ts and not reply_thread_ts:
                    # We posted a new message - track it as potential thread parent
                    ACTIVE_THREADS[response_ts] = {"channel": channel, "last_response_ts": response_ts}
            else:
                print(f"  Reply: python slack_bridge.py --reply {channel} {ts} \"your message\"")

            print(f"{'='*60}\n")

        elif event_type == "app_mention":
            channel = event.get("channel")
            user = event.get("user")
            text = event.get("text", "")
            ts = event.get("ts")
            thread_ts = event.get("thread_ts")  # Will be set if mention is in a thread

            # Get user name
            user_name = user
            try:
                user_info = web_client.users_info(user=user)
                user_name = user_info["user"].get("real_name") or user_info["user"].get("name") or user
            except:
                pass

            # Get channel name
            channel_name = channel
            try:
                channel_info = web_client.conversations_info(channel=channel)
                channel_name = f"#{channel_info['channel']['name']}"
            except:
                pass

            # Strip the @mention from the text
            clean_text = text.split(">", 1)[-1].strip() if ">" in text else text

            inbox_msg = {
                "type": "mention",
                "channel_id": channel,
                "channel": channel_name,
                "user_id": user,
                "user": user_name,
                "text": clean_text,
                "ts": ts,
                "thread_ts": thread_ts,
            }

            write_to_inbox(inbox_msg)

            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Mentioned by {user_name} in {channel_name}")
            print(f"  {clean_text}")

            # Check if user is allowed
            if ALLOWED_USERS and user not in ALLOWED_USERS:
                print(f"  [User {user} not in allowed list, rejecting]")
                add_reaction(web_client, channel, ts, "no_entry")
                print(f"{'='*60}\n")
                return

            # Auto-respond if enabled
            if AUTO_RESPOND and clean_text:
                # Add working emoji and track pending work
                add_reaction(web_client, channel, ts, EMOJI_WORKING)
                mark_work_started(channel, ts, clean_text, user, thread_ts)

                # If mention is in a thread, respond in that thread
                # Otherwise start a new thread from the mention
                reply_to_thread = thread_ts or ts

                print(f"  [Auto-responding via Claude Code...]")
                response_text = run_claude_with_progress(
                    web_client, channel, reply_to_thread,
                    clean_text, user_name, channel_name, user
                )
                print(f"  Response: {response_text[:100]}{'...' if len(response_text) > 100 else ''}")

                response_ts = send_slack_response(web_client, channel, response_text, reply_to_thread)

                # Remove working emoji, add done emoji, mark completed
                remove_reaction(web_client, channel, ts, EMOJI_WORKING)
                add_reaction(web_client, channel, ts, EMOJI_DONE)
                mark_work_completed(channel, ts)

                # Track this thread for future replies
                if response_ts:
                    thread_parent = thread_ts or ts
                    ACTIVE_THREADS[thread_parent] = {"channel": channel, "last_response_ts": response_ts}

            print(f"{'='*60}\n")


def run_bridge(workspace: str = "default", auto_respond: bool = False, work_dir: str = None):
    """Run the Socket Mode bridge."""
    global AUTO_RESPOND, WORK_DIR
    AUTO_RESPOND = auto_respond
    WORK_DIR = work_dir or os.getcwd()

    # Load any pending work from previous session
    load_pending_work()

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

    # Start cleanup thread for stuck work items
    cleanup_thread = Thread(target=run_cleanup_loop, args=(web_client, stop_event), daemon=True)
    cleanup_thread.start()
    print("Cleanup thread started (checks every 5min, retries once before error)")

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


def run_cleanup_now(workspace: str = "default"):
    """Run cleanup once and exit. Finds messages with hourglass and processes them."""
    bot_token, _ = get_tokens(workspace)
    web_client = WebClient(token=bot_token)

    # Load pending work from file
    load_pending_work()

    print(f"[CLEANUP] Checking for stuck work items...")
    print(f"[CLEANUP] Found {len(PENDING_WORK)} items in pending_work.json")

    if not PENDING_WORK:
        print("[CLEANUP] No pending work items found.")
        return

    # Run cleanup
    cleanup_stuck_work(web_client)
    print("[CLEANUP] Done.")


def scan_for_orphaned_hourglasses(workspace: str = "default", work_dir: str = None):
    """Scan inbox for messages with orphaned hourglass emoji and process them."""
    global WORK_DIR
    WORK_DIR = work_dir or os.getcwd()

    bot_token, _ = get_tokens(workspace)
    web_client = WebClient(token=bot_token)

    # Get bot's user ID
    try:
        auth_response = web_client.auth_test()
        bot_user_id = auth_response["user_id"]
        print(f"[SCAN] Bot user ID: {bot_user_id}")
    except Exception as e:
        print(f"[SCAN] Error getting bot ID: {e}")
        return

    # Read recent inbox messages
    if not INBOX_FILE.exists():
        print("[SCAN] No inbox file found.")
        return

    messages = []
    with open(INBOX_FILE) as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))

    # Check last 50 messages for orphaned hourglasses
    recent = messages[-50:]
    print(f"[SCAN] Checking {len(recent)} recent messages for orphaned hourglasses...")

    orphaned = []
    for msg in recent:
        channel = msg.get("channel_id")
        ts = msg.get("ts")
        if not channel or not ts:
            continue

        # Check reactions on this message
        try:
            result = web_client.reactions_get(channel=channel, timestamp=ts)
            message_data = result.get("message", {})
            reactions = message_data.get("reactions", [])

            has_hourglass = False
            has_done = False
            has_error = False

            for r in reactions:
                if r["name"] == EMOJI_WORKING:
                    # Check if our bot added it
                    if bot_user_id in r.get("users", []):
                        has_hourglass = True
                elif r["name"] == EMOJI_DONE:
                    has_done = True
                elif r["name"] == EMOJI_ERROR:
                    has_error = True

            # Orphaned = has hourglass but no done/error
            if has_hourglass and not has_done and not has_error:
                orphaned.append(msg)
                print(f"[SCAN] Found orphaned: {msg.get('text', '')[:50]}...")

        except Exception as e:
            # Message may have been deleted or we don't have access
            continue

    if not orphaned:
        print("[SCAN] No orphaned hourglasses found.")
        return

    print(f"\n[SCAN] Processing {len(orphaned)} orphaned messages...")

    for msg in orphaned:
        channel = msg.get("channel_id")
        ts = msg.get("ts")
        text = msg.get("text", "")
        user_id = msg.get("user_id", "unknown")
        user_name = msg.get("user", user_id)
        thread_ts = msg.get("thread_ts")

        print(f"\n[SCAN] Processing: {text[:50]}...")

        # Add retry emoji
        add_reaction(web_client, channel, ts, EMOJI_RETRY)

        # Determine thread for response
        reply_to_thread = thread_ts or ts

        try:
            response_text = run_claude_code(text, user_name, channel, user_id,
                                            channel_id=channel, thread_ts=reply_to_thread)
            send_slack_response(web_client, channel, response_text, reply_to_thread)

            # Update emojis
            remove_reaction(web_client, channel, ts, EMOJI_WORKING)
            remove_reaction(web_client, channel, ts, EMOJI_RETRY)
            add_reaction(web_client, channel, ts, EMOJI_DONE)
            print(f"[SCAN] Success!")

        except Exception as e:
            print(f"[SCAN] Failed: {e}")
            remove_reaction(web_client, channel, ts, EMOJI_WORKING)
            remove_reaction(web_client, channel, ts, EMOJI_RETRY)
            add_reaction(web_client, channel, ts, EMOJI_ERROR)

    print("\n[SCAN] Done.")


def main():
    parser = argparse.ArgumentParser(description="Slack Bridge for Claude Code")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="Auto-respond to messages using Claude Code")
    parser.add_argument("--workdir", type=str, default=None,
                        help="Working directory for Claude Code (default: current dir)")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run in background")
    parser.add_argument("--status", "-s", action="store_true", help="Check if running")
    parser.add_argument("--stop", action="store_true", help="Stop the daemon")
    parser.add_argument("--cleanup", "-c", action="store_true", help="Run cleanup for stuck hourglasses once and exit")
    parser.add_argument("--scan", action="store_true", help="Scan inbox for orphaned hourglasses and process them")
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
    elif args.cleanup:
        run_cleanup_now(args.workspace)
    elif args.scan:
        scan_for_orphaned_hourglasses(args.workspace, args.workdir)
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
