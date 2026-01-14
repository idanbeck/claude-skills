#!/usr/bin/env python3
"""
SMS Bridge - Real-time connection between SMS and Claude Code via Twilio.

Runs a webhook server to receive incoming SMS and responds via Claude Code.

Usage:
    python sms_bridge.py              # Run the bridge (foreground)
    python sms_bridge.py --auto       # Auto-respond using Claude Code
    python sms_bridge.py --daemon     # Run in background
    python sms_bridge.py --status     # Check if running
    python sms_bridge.py --stop       # Stop the daemon
    python sms_bridge.py --inbox      # Show recent inbox messages
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
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Check for required libraries
try:
    from twilio.rest import Client
    from twilio.twiml.messaging_response import MessagingResponse
except ImportError:
    print("Error: twilio not installed.")
    print("Install with: pip install twilio")
    sys.exit(1)

try:
    from flask import Flask, request
except ImportError:
    print("Error: flask not installed.")
    print("Install with: pip install flask")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
INBOX_FILE = SKILL_DIR / "inbox.jsonl"
PID_FILE = SKILL_DIR / ".bridge.pid"
CONVERSATIONS_FILE = SKILL_DIR / "conversations.json"

# Global config
AUTO_RESPOND = False
WORK_DIR = None
TWILIO_CLIENT = None
FROM_NUMBER = None
ALLOWED_NUMBERS = set()
USER_SESSIONS = {}  # Track Claude sessions per phone number

# Flask app
app = Flask(__name__)


def load_config():
    """Load configuration."""
    if not CONFIG_FILE.exists():
        print(json.dumps({"error": "No config file found"}))
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def write_to_inbox(message: dict):
    """Append a message to the inbox file."""
    message["received_at"] = datetime.now().isoformat()
    with open(INBOX_FILE, "a") as f:
        f.write(json.dumps(message) + "\n")


def send_sms(to: str, body: str, media_url: str = None):
    """Send an SMS/MMS response."""
    global TWILIO_CLIENT, FROM_NUMBER

    try:
        params = {
            "to": to,
            "from_": FROM_NUMBER,
            "body": body,
        }
        if media_url:
            params["media_url"] = [media_url]

        # SMS has 160 char limit per segment, Twilio handles splitting
        # but we should be aware of it
        message = TWILIO_CLIENT.messages.create(**params)
        print(f"  [SMS sent: {message.sid}]")
        return message.sid
    except Exception as e:
        print(f"  [Error sending SMS: {e}]")
        return None


def run_claude_code(prompt: str, phone_number: str) -> str:
    """Run Claude Code with a prompt and return the response."""
    global WORK_DIR, USER_SESSIONS

    # Build context-aware prompt (only for new sessions)
    if phone_number in USER_SESSIONS:
        full_prompt = prompt
    else:
        full_prompt = f"""You are responding to SMS text messages. Keep responses VERY concise - SMS has character limits.

You have full access to this workspace including Obsidian vault, skills, and tools.

When the user confirms something (like "yes", "do it", "y"), execute the action you proposed.

IMAGE GENERATION: If asked for an image:
1. Generate: python ~/.claude/skills/nano-banana-pro/generate_image.py "prompt" --output /tmp
2. Note: Images need to be hosted publicly for MMS. Mention you generated it and where it's saved.

First message: {prompt}"""

    try:
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]

        if phone_number in USER_SESSIONS:
            cmd.extend(["--continue"])

        cmd.append(full_prompt)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=WORK_DIR,
            timeout=300,  # 5 minute timeout
        )

        response = result.stdout.strip()
        if not response and result.stderr:
            response = f"Error: {result.stderr[:200]}"

        # Strip thinking tags
        response = re.sub(r'<thinking>.*?</thinking>\s*', '', response, flags=re.DOTALL)
        response = response.strip()

        # Mark session as active
        USER_SESSIONS[phone_number] = True

        return response or "Done."
    except subprocess.TimeoutExpired:
        return "Sorry, that took too long (5 min timeout)."
    except Exception as e:
        return f"Error: {str(e)[:100]}"


def run_claude_with_progress(phone: str, prompt: str) -> str:
    """Run Claude Code with progress updates via SMS."""
    # Send initial "working" message
    send_sms(phone, "Working on it...")

    start_time = time.time()
    response = None
    error = None

    def run_claude():
        nonlocal response, error
        try:
            response = run_claude_code(prompt, phone)
        except Exception as e:
            error = str(e)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_claude)

        # Send progress updates every 60 seconds for long tasks
        update_count = 0
        while not future.done():
            try:
                future.result(timeout=60)
            except FuturesTimeoutError:
                update_count += 1
                elapsed = int(time.time() - start_time)
                mins = elapsed // 60
                if update_count <= 3:  # Max 3 progress updates to avoid spam
                    send_sms(phone, f"Still working... ({mins}m)")

    if error:
        return f"Error: {error}"

    return response or "Done."


@app.route("/sms", methods=["POST"])
def handle_sms():
    """Handle incoming SMS webhook from Twilio."""
    global AUTO_RESPOND, ALLOWED_NUMBERS

    # Get message details
    from_number = request.values.get("From", "")
    to_number = request.values.get("To", "")
    body = request.values.get("Body", "").strip()
    num_media = int(request.values.get("NumMedia", 0))

    # Get any media URLs
    media_urls = []
    for i in range(num_media):
        media_url = request.values.get(f"MediaUrl{i}")
        if media_url:
            media_urls.append(media_url)

    # Log to inbox
    inbox_msg = {
        "type": "sms",
        "from": from_number,
        "to": to_number,
        "body": body,
        "media_urls": media_urls,
    }
    write_to_inbox(inbox_msg)

    # Print to console
    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] SMS from {from_number}")
    print(f"  {body}")
    if media_urls:
        print(f"  Media: {media_urls}")

    # Check if number is allowed
    if ALLOWED_NUMBERS and from_number not in ALLOWED_NUMBERS:
        print(f"  [Number {from_number} not in allowed list, ignoring]")
        print(f"{'='*60}\n")
        # Return empty TwiML - don't respond
        return str(MessagingResponse())

    # Auto-respond if enabled
    if AUTO_RESPOND and body:
        print(f"  [Auto-responding via Claude Code...]")

        # Run in a thread so we can return quickly to Twilio
        # (Twilio expects response within 15 seconds)
        def process_and_respond():
            response_text = run_claude_with_progress(from_number, body)
            print(f"  Response: {response_text[:100]}{'...' if len(response_text) > 100 else ''}")

            # Send the actual response
            send_sms(from_number, response_text)

            # Log outgoing
            write_to_inbox({
                "type": "sms_sent",
                "from": to_number,
                "to": from_number,
                "body": response_text,
            })

        Thread(target=process_and_respond, daemon=True).start()

    print(f"{'='*60}\n")

    # Return empty TwiML - we'll send response async
    return str(MessagingResponse())


@app.route("/status", methods=["GET"])
def status():
    """Health check endpoint."""
    return json.dumps({"status": "running", "auto_respond": AUTO_RESPOND})


def run_bridge(port: int = 5001, auto_respond: bool = False, work_dir: str = None):
    """Run the SMS bridge server."""
    global AUTO_RESPOND, WORK_DIR, TWILIO_CLIENT, FROM_NUMBER, ALLOWED_NUMBERS

    config = load_config()

    AUTO_RESPOND = auto_respond
    WORK_DIR = work_dir or os.getcwd()
    TWILIO_CLIENT = Client(config["account_sid"], config["auth_token"])
    FROM_NUMBER = config["phone_number"]
    ALLOWED_NUMBERS = set(config.get("allowed_numbers", []))

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    print(f"SMS Bridge started")
    print(f"Listening on port {port}... (PID: {os.getpid()})")
    print(f"Webhook URL: http://localhost:{port}/sms")
    print(f"Inbox: {INBOX_FILE}")
    print(f"Phone: {FROM_NUMBER}")
    if ALLOWED_NUMBERS:
        print(f"Allowed numbers: {ALLOWED_NUMBERS}")
    if AUTO_RESPOND:
        print(f"Auto-respond: ENABLED (Claude Code in {WORK_DIR})")
    print("Press Ctrl+C to stop\n")
    print("NOTE: Use ngrok or similar to expose this to the internet:")
    print(f"  ngrok http {port}")
    print("Then set the webhook URL in Twilio Console\n")

    # Run Flask
    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
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

    recent = messages[-limit:]

    print(json.dumps({
        "messages": recent,
        "total": len(messages),
        "showing": len(recent),
    }, indent=2))


def check_status():
    """Check if bridge is running."""
    if PID_FILE.exists():
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)
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
    parser = argparse.ArgumentParser(description="SMS Bridge for Claude Code")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="Auto-respond to messages using Claude Code")
    parser.add_argument("--workdir", type=str, default=None,
                        help="Working directory for Claude Code")
    parser.add_argument("--port", "-p", type=int, default=5001,
                        help="Port to run webhook server on")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run in background")
    parser.add_argument("--status", "-s", action="store_true", help="Check if running")
    parser.add_argument("--stop", action="store_true", help="Stop the daemon")
    parser.add_argument("--inbox", "-i", action="store_true", help="Show inbox messages")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Number of inbox messages")

    args = parser.parse_args()

    if args.status:
        check_status()
    elif args.stop:
        stop_bridge()
    elif args.inbox:
        show_inbox(args.limit)
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
        run_bridge(args.port, args.auto, args.workdir)
    else:
        run_bridge(args.port, args.auto, args.workdir)


if __name__ == "__main__":
    main()
