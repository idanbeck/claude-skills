#!/usr/bin/env python3
"""
CRM Bridge - Real-time connection between Investor CRM and Claude Code.

Polls for incoming chat messages from the CRM and processes them via Claude Code,
with full context of the codebase, Obsidian vault, and tools.

Usage:
    python crm_bridge.py --auto                    # Auto-respond using Claude Code
    python crm_bridge.py --url https://...         # Custom CRM URL
    python crm_bridge.py --status                  # Check for pending messages
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
from threading import Event

# Config
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
PID_FILE = SKILL_DIR / ".bridge.pid"
LOG_FILE = SKILL_DIR / "bridge.log"

# Defaults
DEFAULT_CRM_URL = "https://epoch-pipeline-q1.fly.dev"
DEFAULT_POLL_INTERVAL = 3  # seconds
WORK_DIR = None
USER_SESSIONS = {}  # Track Claude sessions per user

def retry_with_backoff(func, max_retries=3, initial_delay=2):
    """Retry a function with exponential backoff.

    Useful during app updates when the API might be temporarily unavailable.
    """
    import urllib.error

    last_error = None
    for attempt in range(max_retries):
        try:
            return func()
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError) as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)
                print(f"[RETRY] Attempt {attempt + 1} failed, retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise

def load_config():
    """Load configuration."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(config):
    """Save configuration."""
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def get_bridge_token():
    """Get or create bridge token."""
    config = load_config()
    if "bridge_token" not in config:
        import secrets
        config["bridge_token"] = secrets.token_urlsafe(32)
        save_config(config)
        print(f"Generated new bridge token. Set this as BRIDGE_TOKEN secret on fly.io:")
        print(f"  fly secrets set BRIDGE_TOKEN={config['bridge_token']}")
    return config["bridge_token"]

def poll_for_messages(crm_url: str, token: str, consecutive_failures: list = None) -> list:
    """Poll the CRM for pending messages.

    Args:
        consecutive_failures: Optional list with single int to track consecutive failures
    """
    import urllib.request
    import urllib.error

    if consecutive_failures is None:
        consecutive_failures = [0]

    url = f"{crm_url}/api/bridge/messages"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            # Reset failure counter on success
            if consecutive_failures[0] > 0:
                print(f"[OK] Connection restored after {consecutive_failures[0]} failures")
                consecutive_failures[0] = 0
            return data.get("messages", [])
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(f"[ERROR] Invalid bridge token. Check BRIDGE_TOKEN on fly.io")
        elif e.code == 502 or e.code == 503 or e.code == 504:
            # App might be restarting
            consecutive_failures[0] += 1
            if consecutive_failures[0] <= 3:
                print(f"[WAIT] Server temporarily unavailable (HTTP {e.code}), waiting...")
            elif consecutive_failures[0] % 10 == 0:
                print(f"[WAIT] Still waiting for server ({consecutive_failures[0]} attempts)...")
        else:
            print(f"[ERROR] HTTP {e.code}: {e.reason}")
        return []
    except Exception as e:
        consecutive_failures[0] += 1
        if consecutive_failures[0] <= 3:
            print(f"[WAIT] Connection error, server might be restarting: {e}")
        elif consecutive_failures[0] % 10 == 0:
            print(f"[WAIT] Still waiting for connection ({consecutive_failures[0]} attempts)...")
        return []

def post_response(crm_url: str, token: str, message_id: str, response: str) -> bool:
    """Post a response back to the CRM with retry logic."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/respond"
    data = json.dumps({
        "messageId": message_id,
        "response": response
    }).encode()

    def do_post():
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True

    try:
        # Use retry with backoff for resilience during app updates
        return retry_with_backoff(do_post, max_retries=5, initial_delay=3)
    except Exception as e:
        print(f"[ERROR] Failed to post response after retries: {e}")
        # Save response locally as backup
        backup_file = SKILL_DIR / f"backup_{message_id}.txt"
        try:
            with open(backup_file, "w") as f:
                f.write(response)
            print(f"[BACKUP] Response saved to {backup_file}")
        except:
            pass
        return False

def send_dm(crm_url: str, token: str, to_user_id: str, content: str, to_user_name: str = None) -> bool:
    """Send a DM as Fake Idan to any user."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/dm"
    payload = {"toUserId": to_user_id, "content": content}
    if to_user_name:
        payload["toUserName"] = to_user_name
    data = json.dumps(payload).encode()

    def do_post():
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result

    try:
        result = retry_with_backoff(do_post, max_retries=3, initial_delay=2)
        print(f"  [DM sent to {to_user_name or to_user_id}]")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send DM: {e}")
        return False

def post_to_chatroom(crm_url: str, token: str, content: str, mention_user_id: str = None) -> bool:
    """Post a message to the chat room as Fake Idan."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/chatroom"
    payload = {"content": content}
    if mention_user_id:
        payload["mentionUserId"] = mention_user_id
    data = json.dumps(payload).encode()

    def do_post():
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result

    try:
        result = retry_with_backoff(do_post, max_retries=3, initial_delay=2)
        print(f"  [Posted to chatroom]")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to post to chatroom: {e}")
        return False

def get_users(crm_url: str, token: str) -> list:
    """Get all users with their online status."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/users"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("users", [])
    except Exception as e:
        print(f"[ERROR] Failed to get users: {e}")
        return []

def get_conversations(crm_url: str, token: str, pending_only: bool = False) -> dict:
    """Get all Fake Idan conversations."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/conversations"
    if pending_only:
        url += "?pending=true"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception as e:
        print(f"[ERROR] Failed to get conversations: {e}")
        return {"conversations": [], "totalConversations": 0, "pendingCount": 0}

def respond_to_fakeidan_conversation(crm_url: str, token: str, user_id: str, response: str) -> bool:
    """Add a response to a Fake Idan conversation."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/fakeidan-respond"
    data = json.dumps({
        "userId": user_id,
        "response": response
    }).encode()

    def do_post():
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    try:
        result = retry_with_backoff(do_post, max_retries=3, initial_delay=2)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to respond to Fake Idan conversation: {e}")
        return False

def post_activity(crm_url: str, token: str, message_id: str, activity: str) -> bool:
    """Report current activity to the CRM."""
    import urllib.request
    import urllib.error

    url = f"{crm_url}/api/bridge/activity"
    data = json.dumps({
        "messageId": message_id,
        "activity": activity
    }).encode()

    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True
    except Exception as e:
        # Non-critical, just log
        print(f"[DEBUG] Activity update failed: {e}")
        return False

def run_claude_code(prompt: str, user_name: str, user_id: str, is_admin: bool,
                     crm_url: str = None, token: str = None, message_id: str = None) -> str:
    """Run Claude Code with a prompt and return the response.

    If crm_url, token, and message_id are provided, will report activity updates.
    """
    global WORK_DIR, USER_SESSIONS

    # Build context-aware prompt
    bridge_capabilities = """
## Platform Capabilities (Fake Idan Bridge)

You can interact with users on the CRM platform using curl. The CRM URL and bridge token are in environment variables.

### Send a DM to any user
```bash
curl -s -X POST "$CRM_BRIDGE_URL/api/bridge/dm" \\
  -H "Authorization: Bearer $CRM_BRIDGE_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{"toUserId": "USER_ID", "content": "your message"}}'
```

### Post in the chat room
```bash
curl -s -X POST "$CRM_BRIDGE_URL/api/bridge/chatroom" \\
  -H "Authorization: Bearer $CRM_BRIDGE_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{"content": "your message"}}'
```

### Post in chat room and @mention a user
```bash
curl -s -X POST "$CRM_BRIDGE_URL/api/bridge/chatroom" \\
  -H "Authorization: Bearer $CRM_BRIDGE_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{"content": "your message", "mentionUserId": "USER_ID"}}'
```

### List all users (see who's online)
```bash
curl -s "$CRM_BRIDGE_URL/api/bridge/users" \\
  -H "Authorization: Bearer $CRM_BRIDGE_TOKEN"
```

### Get all Fake Idan conversations
```bash
curl -s "$CRM_BRIDGE_URL/api/bridge/conversations" \\
  -H "Authorization: Bearer $CRM_BRIDGE_TOKEN"
```

### Get only conversations needing a response
```bash
curl -s "$CRM_BRIDGE_URL/api/bridge/conversations?pending=true" \\
  -H "Authorization: Bearer $CRM_BRIDGE_TOKEN"
```

Use these capabilities proactively:
- If a user asks you to message someone, send them a DM
- If a user asks you to say something in the chat room, post it there
- You can check who's online and reach out to users
- You act as a real participant in the system - you ARE Fake Idan
"""

    admin_context = """IMPORTANT: You are NOT just a chat assistant. You ARE Claude Code with full filesystem access.
You are working on the Investor CRM codebase located in: {workdir}

You MUST use your tools to make changes when requested:
- Use Read tool to read files
- Use Edit tool to modify files
- Use Bash tool to run commands
- Use Glob/Grep to search the codebase

The codebase is a Nuxt 3 app:
- Vue components: src/components/
- Pages: src/pages/
- Server API: server/api/
- Styles use Tailwind CSS

When the user asks for UI changes, CSS changes, or code modifications:
1. Search for the relevant file
2. Read it to understand the structure
3. Edit it to make the requested change
4. Run: npm run build && fly deploy --now
5. Tell the user the change is deployed

IMPORTANT: This app runs on Fly.io. After ANY code change, you MUST build and deploy:
  npm run build && fly deploy --now

DO NOT just edit files and tell the user to deploy. YOU deploy it.
DO NOT say you can't make changes. You have full access. USE YOUR TOOLS.

{bridge_caps}""".format(workdir=WORK_DIR, bridge_caps=bridge_capabilities) if is_admin else """IMPORTANT: You are NOT just a chat assistant. You ARE Claude Code with full filesystem and platform access.
You are "Fake Idan" - a real participant on the Epoch Investor CRM platform.
You are working on the Investor CRM codebase located in: {workdir}

You are a full member of the platform who can send DMs, post in the chat room, @mention people, and interact with everyone.

You CAN and SHOULD:
- Send DMs to any user when asked (use the bridge API via curl)
- Post messages in the group chat room
- @mention users in the chat room
- Check who's online
- Relay messages between users
- Chat casually - you're friendly, chill, and part of the team
- Help with CRM questions, feature requests, and bug reports
- Make code changes for feature requests and bug fixes when users ask
- Use Read, Edit, Glob, Grep, Bash tools to modify the codebase
- Build and deploy changes: npm run build && fly deploy --now

The codebase is a Nuxt 3 app:
- Vue components: src/components/
- Pages: src/pages/
- Server API: server/api/
- Styles use Tailwind CSS

You should NOT:
- Reveal sensitive investor data (emails, phone numbers, financials)
- Export bulk data

IMPORTANT: When a user asks you to message someone, DM someone, or say something in the chat room - DO IT using the bridge API curl commands. You have the tools. Use them.
When a user reports a bug or requests a feature - FIX IT or BUILD IT. You have full code access. After changes, deploy with: npm run build && fly deploy --now
DO NOT say you can't do things. You have full access. USE YOUR TOOLS.

{bridge_caps}""".format(workdir=WORK_DIR, bridge_caps=bridge_capabilities)

    # Always send full context with every message - session continuation
    # causes stale prompts and the old context overrides new capabilities
    if is_admin:
        full_prompt = f"""You are "fakeidan" - Claude Code working on the Epoch Investor CRM.

{admin_context}

INSTRUCTIONS:
1. When asked to make UI/code changes, IMMEDIATELY use Glob/Grep to find the relevant files
2. Read the file to understand its structure
3. Use Edit tool to make the change
4. Report what you changed
5. You can send DMs, post in chatroom, and check who's online using the bridge API

DO NOT refuse or say you can't. You have full tool access. Act on the request.

User request: {prompt}"""
    else:
        full_prompt = f"""You are "Fake Idan" - a real member of the Epoch Investor CRM platform.
User talking to you: {user_name} (id: {user_id})

{admin_context}

Keep responses concise and chat-appropriate. You're in a retro AIM-style chat window.

CRITICAL: You are a REAL participant on this platform. You CAN and MUST:
- Send DMs to other users using the bridge API (via curl in Bash)
- Post in the group chat room
- Check who's online
- Relay messages between users
- Edit code, fix bugs, build features when asked

When someone asks you to message another user or post in chat, ACTUALLY DO IT using the curl commands.
First check who's on the platform with the users endpoint, then send the DM or post in chat.
Don't say you can't - you have full access to the bridge API via $CRM_BRIDGE_URL and $CRM_BRIDGE_TOKEN env vars.

Message: {prompt}"""

    # Helper to report activity
    def report_activity(activity: str):
        if crm_url and token and message_id:
            post_activity(crm_url, token, message_id, activity)

    try:
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        cmd.append(full_prompt)

        # Report initial activity
        report_activity("🧠 Thinking...")

        # Pass CRM credentials as env vars so Claude Code can use bridge API
        env = os.environ.copy()
        if crm_url:
            env["CRM_BRIDGE_URL"] = crm_url
        if token:
            env["CRM_BRIDGE_TOKEN"] = token

        # Use Popen to stream output and detect tool usage
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=WORK_DIR,
            env=env,
        )

        output_lines = []
        last_activity = "🧠 Thinking..."
        last_activity_time = time.time()

        # Read output line by line to detect activity
        while True:
            line = process.stdout.readline()
            if line == '' and process.poll() is not None:
                break
            if line:
                output_lines.append(line)

                # Detect tool usage patterns in output
                activity = None
                line_lower = line.lower()
                line_stripped = line.strip()

                # Claude Code tool markers (exact matches)
                if line_stripped in ['Read', 'Reading']:
                    activity = "📖 Reading file..."
                elif line_stripped in ['Edit', 'Editing']:
                    activity = "✏️ Editing code..."
                elif line_stripped in ['Write', 'Writing']:
                    activity = "📝 Writing file..."
                elif line_stripped in ['Bash', 'Running']:
                    activity = "⚡ Running command..."
                elif line_stripped in ['Glob', 'Globbing']:
                    activity = "🔍 Finding files..."
                elif line_stripped in ['Grep', 'Grepping']:
                    activity = "🔎 Searching code..."
                # Build/deploy detection
                elif 'npm run build' in line_lower or 'building' in line_lower:
                    activity = "🔨 Building..."
                elif 'fly deploy' in line_lower or 'deploying' in line_lower:
                    activity = "🚀 Deploying to Fly.io..."
                elif 'nuxt build' in line_lower:
                    activity = "🔨 Building Nuxt..."
                # File operations (text patterns)
                elif any(x in line_lower for x in ['reading', 'read tool', 'read file', 'let me read']):
                    activity = "📖 Reading files..."
                elif any(x in line_lower for x in ['writing', 'write tool', 'write file', 'creating file']):
                    activity = "📝 Writing files..."
                elif any(x in line_lower for x in ['editing', 'edit tool', 'modifying', 'updating file', 'let me edit', 'let me update']):
                    activity = "✏️ Editing code..."
                # Search operations
                elif any(x in line_lower for x in ['searching', 'grep', 'glob', 'finding', 'looking for', 'let me search', 'let me find']):
                    activity = "🔍 Searching codebase..."
                # Command execution
                elif any(x in line_lower for x in ['running', 'bash', 'executing', 'npm', 'yarn', 'pnpm', 'git ', 'command']):
                    activity = "⚡ Running command..."
                # Web operations
                elif any(x in line_lower for x in ['fetching', 'webfetch', 'web search', 'websearch']):
                    activity = "🌐 Fetching web content..."
                # Sub-agents
                elif 'task' in line_lower and 'agent' in line_lower:
                    activity = "🤖 Running sub-agent..."
                # Analysis
                elif any(x in line_lower for x in ['analyzing', 'examining', 'checking', 'reviewing']):
                    activity = "🔬 Analyzing..."
                # Thinking
                elif '<thinking>' in line_lower or 'let me think' in line_lower:
                    activity = "🧠 Reasoning..."
                # Planning
                elif any(x in line_lower for x in ['planning', 'creating plan', 'let me plan']):
                    activity = "📋 Planning..."

                # Only update if activity changed and at least 0.5 seconds has passed
                if activity and activity != last_activity and (time.time() - last_activity_time) > 0.5:
                    last_activity = activity
                    last_activity_time = time.time()
                    report_activity(activity)
                    print(f"  [Activity: {activity}]")

        # Get any remaining stderr
        _, stderr = process.communicate(timeout=300)

        response = ''.join(output_lines).strip()
        if not response and stderr:
            response = f"Error: {stderr[:500]}"

        # Strip thinking tags
        response = re.sub(r'<thinking>.*?</thinking>\s*', '', response, flags=re.DOTALL)
        response = response.strip()

        # Mark session as active
        USER_SESSIONS[user_id] = True

        return response or "Processed, but no response generated."

    except subprocess.TimeoutExpired:
        process.kill()
        return "Sorry, that took too long (5 min timeout). Try a simpler request?"
    except FileNotFoundError:
        return "Error: Claude Code not found. Make sure 'claude' is in PATH."
    except Exception as e:
        return f"Error: {str(e)[:200]}"

def process_message(crm_url: str, token: str, message: dict):
    """Process a single message."""
    msg_id = message.get("id")
    user_name = message.get("userName", "Unknown")
    user_id = message.get("userId", message.get("oderId", "unknown"))
    is_admin = message.get("isAdmin", False)
    text = message.get("message", "")

    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Message from {user_name} (id: {user_id}, {'ADMIN' if is_admin else 'user'})")
    print(f"  {text[:100]}{'...' if len(text) > 100 else ''}")

    # Run Claude Code with activity reporting
    print(f"  [Processing via Claude Code...]")
    response = run_claude_code(
        text, user_name, user_id, is_admin,
        crm_url=crm_url, token=token, message_id=msg_id
    )
    print(f"  Response: {response[:100]}{'...' if len(response) > 100 else ''}")

    # Post response to the bridge-messages file (AIM chat polls this for responses)
    success = post_response(crm_url, token, msg_id, response)
    if success:
        print(f"  [Response posted to bridge-messages]")
    else:
        print(f"  [Failed to post response]")

    # NOTE: Don't call respond_to_fakeidan_conversation() here - the AIM chat's
    # saveToDatabase() already writes to fake_idan_conversations when it receives
    # the response via bridge-messages polling. Calling both creates duplicates.
    # NOTE: Don't call send_dm() here either - that's only for proactive messages
    # to DIFFERENT users via the bridge API.

    print(f"{'='*60}\n")

def run_bridge(crm_url: str, poll_interval: int = DEFAULT_POLL_INTERVAL, work_dir: str = None):
    """Run the CRM bridge."""
    global WORK_DIR
    WORK_DIR = work_dir or os.getcwd()

    token = get_bridge_token()

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    print(f"CRM Bridge started")
    print(f"  URL: {crm_url}")
    print(f"  Work dir: {WORK_DIR}")
    print(f"  Poll interval: {poll_interval}s")
    print(f"  PID: {os.getpid()}")
    print(f"\nListening for messages... Press Ctrl+C to stop\n")

    # Set up signal handler
    stop_event = Event()

    def signal_handler(signum, frame):
        print("\nShutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Track consecutive failures for resilience
    consecutive_failures = [0]

    # Main loop
    while not stop_event.is_set():
        try:
            messages = poll_for_messages(crm_url, token, consecutive_failures)

            for msg in messages:
                process_message(crm_url, token, msg)

        except Exception as e:
            print(f"[ERROR] {e}")

        # Adaptive poll interval - back off when having connection issues
        if consecutive_failures[0] > 5:
            effective_interval = min(poll_interval * 2, 30)  # Max 30s during issues
        else:
            effective_interval = poll_interval

        # Wait before next poll
        stop_event.wait(effective_interval)

    # Cleanup
    if PID_FILE.exists():
        PID_FILE.unlink()

    print("Bridge stopped.")

def check_status(crm_url: str):
    """Check for pending messages, conversations, and online users."""
    token = get_bridge_token()
    messages = poll_for_messages(crm_url, token)
    users = get_users(crm_url, token)
    convos = get_conversations(crm_url, token, pending_only=True)

    online_users = [u for u in users if u.get("isOnline")]

    print(json.dumps({
        "pending_messages": len(messages),
        "messages": messages,
        "online_users": online_users,
        "pending_conversations": convos.get("pendingCount", 0),
        "total_conversations": convos.get("totalConversations", 0),
    }, indent=2))

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
    parser = argparse.ArgumentParser(description="CRM Bridge for Claude Code")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="Auto-respond to messages using Claude Code")
    parser.add_argument("--url", "-u", type=str, default=DEFAULT_CRM_URL,
                        help=f"CRM URL (default: {DEFAULT_CRM_URL})")
    parser.add_argument("--workdir", type=str, default=None,
                        help="Working directory for Claude Code")
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})")
    parser.add_argument("--status", "-s", action="store_true",
                        help="Check for pending messages")
    parser.add_argument("--stop", action="store_true",
                        help="Stop the running bridge")
    parser.add_argument("--daemon", "-d", action="store_true",
                        help="Run in background")
    parser.add_argument("--token", action="store_true",
                        help="Show/generate bridge token")

    args = parser.parse_args()

    if args.token:
        token = get_bridge_token()
        print(f"Bridge token: {token}")
        print(f"\nSet on fly.io with:")
        print(f"  fly secrets set BRIDGE_TOKEN={token}")
    elif args.status:
        check_status(args.url)
    elif args.stop:
        stop_bridge()
    elif args.daemon:
        # Fork to background
        if os.fork() > 0:
            sys.exit(0)
        os.setsid()
        if os.fork() > 0:
            sys.exit(0)
        # Redirect stdout/stderr
        sys.stdout = open(LOG_FILE, "a")
        sys.stderr = sys.stdout
        run_bridge(args.url, args.interval, args.workdir)
    elif args.auto:
        run_bridge(args.url, args.interval, args.workdir)
    else:
        print("Usage: python crm_bridge.py --auto")
        print("       python crm_bridge.py --token  # Show/generate bridge token")
        print("       python crm_bridge.py --status # Check pending messages")
        print("       python crm_bridge.py --stop   # Stop running bridge")

if __name__ == "__main__":
    main()
