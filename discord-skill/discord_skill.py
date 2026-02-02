#!/usr/bin/env python3
"""
Discord Skill - Send messages, manage servers, and interact with Discord.

Supports both bot tokens and user OAuth2 authentication.

Usage:
    python discord_skill.py me [--account NAME]
    python discord_skill.py guilds [--account NAME]
    python discord_skill.py channels GUILD_ID [--account NAME]
    python discord_skill.py send CHANNEL_ID "message" [--account NAME]
    python discord_skill.py messages CHANNEL_ID [--limit N] [--account NAME]
    python discord_skill.py reply CHANNEL_ID MESSAGE_ID "message" [--account NAME]
    python discord_skill.py react CHANNEL_ID MESSAGE_ID EMOJI [--account NAME]
    python discord_skill.py dm USER_ID "message" [--account NAME]
    python discord_skill.py members GUILD_ID [--limit N] [--account NAME]
    python discord_skill.py search GUILD_ID "query" [--account NAME]
    python discord_skill.py accounts
    python discord_skill.py login [--account NAME] [--bot]
    python discord_skill.py logout [--account NAME]
"""

import argparse
import json
import os
import re
import secrets
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, parse_qs, urlparse

try:
    import requests
except ImportError:
    print("Error: requests library not installed.")
    print("Install with: pip install requests")
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
TOKENS_DIR = SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"
ACCOUNTS_FILE = SKILL_DIR / "accounts.json"

# Discord API
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

# OAuth2 scopes
SCOPES = [
    "identify",
    "guilds",
    "guilds.members.read",
    "messages.read",
]

# Ensure directories exist
TOKENS_DIR.mkdir(parents=True, exist_ok=True)


def get_client_config() -> dict:
    """Load OAuth client configuration."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)

    print("\n" + "=" * 60)
    print("FIRST-TIME SETUP REQUIRED")
    print("=" * 60)
    print("\nTo use Discord Skill, you need a Discord application.")
    print("This is a one-time setup:\n")
    print("1. Go to: https://discord.com/developers/applications")
    print("2. Click 'New Application' and give it a name")
    print("3. Go to OAuth2 section:")
    print("   - Add redirect: http://localhost:9997")
    print("   - Note the Client ID and Client Secret")
    print("4. For BOT usage (recommended):")
    print("   - Go to 'Bot' section")
    print("   - Click 'Reset Token' and copy the bot token")
    print("   - Enable 'Message Content Intent' under Privileged Intents")
    print("5. Create credentials.json:")
    print(f"   {CREDENTIALS_FILE}")
    print("""   {
     "client_id": "YOUR_CLIENT_ID",
     "client_secret": "YOUR_CLIENT_SECRET",
     "bot_token": "YOUR_BOT_TOKEN"
   }""")
    print("\n6. Invite bot to your server:")
    print("   OAuth2 → URL Generator → Select 'bot' + permissions")
    print("\nThen run this command again.")
    print("=" * 60 + "\n")

    try:
        response = input("Open Discord Developer Portal now? [Y/n]: ").strip().lower()
        if response != "n":
            webbrowser.open("https://discord.com/developers/applications")
    except:
        pass

    sys.exit(1)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)

        if "code" in query:
            self.server.auth_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family: system-ui; text-align: center; padding: 50px;">
                <h1>Authentication Successful!</h1>
                <p>You can close this window.</p>
                <script>window.close();</script>
                </body></html>
            """)
        elif "error" in query:
            self.server.auth_error = query.get("error", ["Unknown"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h1>Error: {self.server.auth_error}</h1></body></html>".encode())
        else:
            self.send_response(400)
            self.end_headers()


def do_oauth_flow(client_config: dict) -> dict:
    """Perform OAuth2 flow for user authentication."""
    client_id = client_config["client_id"]
    client_secret = client_config["client_secret"]

    port = 9997
    redirect_uri = f"http://localhost:{port}"
    state = secrets.token_urlsafe(32)

    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
    }

    auth_url = f"{DISCORD_AUTH_URL}?{urlencode(auth_params)}"

    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.auth_code = None
    server.auth_error = None
    server.timeout = 120

    print("\n" + "=" * 50)
    print("  AUTHENTICATING WITH DISCORD")
    print("=" * 50)
    print(f"Opening browser for authentication.")
    print(f"If browser doesn't open, visit:\n{auth_url}\n")

    webbrowser.open(auth_url)

    while server.auth_code is None and server.auth_error is None:
        server.handle_request()

    if server.auth_error:
        print(f"Authentication error: {server.auth_error}")
        sys.exit(1)

    # Exchange code for token
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": server.auth_code,
        "redirect_uri": redirect_uri,
    }

    response = requests.post(
        DISCORD_TOKEN_URL,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        print(f"Token exchange failed: {response.text}")
        sys.exit(1)

    tokens = response.json()

    if "expires_in" in tokens:
        expiry = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        tokens["expiry"] = expiry.isoformat() + "Z"

    # Get user info
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_response = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)

    if user_response.status_code == 200:
        user_data = user_response.json()
        tokens["user_id"] = user_data.get("id")
        tokens["username"] = user_data.get("username")
        tokens["discriminator"] = user_data.get("discriminator")

    tokens["type"] = "oauth"
    return tokens


def get_token_path(account: Optional[str] = None) -> Path:
    """Get token file path for an account."""
    if account:
        safe_name = re.sub(r"[^\w\-.]", "_", account.lower())
        return TOKENS_DIR / f"token_{safe_name}.json"

    tokens = list(TOKENS_DIR.glob("token_*.json"))
    if tokens:
        return tokens[0]

    return TOKENS_DIR / "token_default.json"


def load_accounts() -> dict:
    """Load account metadata."""
    if ACCOUNTS_FILE.exists():
        try:
            with open(ACCOUNTS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_accounts(accounts: dict):
    """Save account metadata."""
    with open(ACCOUNTS_FILE, "w") as f:
        json.dump(accounts, f, indent=2)


def list_accounts() -> list[dict]:
    """List all authenticated accounts."""
    accounts = []

    if TOKENS_DIR.exists():
        for token_file in TOKENS_DIR.glob("token_*.json"):
            try:
                with open(token_file) as f:
                    data = json.load(f)
                    accounts.append({
                        "name": token_file.stem.replace("token_", ""),
                        "type": data.get("type", "unknown"),
                        "username": data.get("username"),
                        "user_id": data.get("user_id"),
                        "file": str(token_file),
                    })
            except:
                pass
    return accounts


def get_credentials(account: Optional[str] = None) -> dict:
    """Get credentials for an account."""
    config = get_client_config()
    token_path = get_token_path(account)

    if token_path.exists():
        try:
            with open(token_path) as f:
                tokens = json.load(f)

            # Check expiry for OAuth tokens
            if tokens.get("type") == "oauth" and "expiry" in tokens:
                expiry = datetime.fromisoformat(tokens["expiry"].replace("Z", "+00:00"))
                if datetime.now(expiry.tzinfo) >= expiry:
                    if "refresh_token" in tokens:
                        # Refresh the token
                        new_tokens = refresh_token(config, tokens["refresh_token"])
                        if new_tokens:
                            new_tokens["user_id"] = tokens.get("user_id")
                            new_tokens["username"] = tokens.get("username")
                            tokens = new_tokens
                            with open(token_path, "w") as f:
                                json.dump(tokens, f, indent=2)
                        else:
                            tokens = None
                    else:
                        tokens = None

            if tokens:
                return tokens
        except:
            pass

    # No valid token, need to authenticate
    print("No valid credentials found. Run 'login' command first.")
    sys.exit(1)


def refresh_token(config: dict, refresh_token: str) -> Optional[dict]:
    """Refresh OAuth token."""
    token_data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    response = requests.post(
        DISCORD_TOKEN_URL,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        return None

    tokens = response.json()
    if "expires_in" in tokens:
        expiry = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        tokens["expiry"] = expiry.isoformat() + "Z"
    tokens["type"] = "oauth"
    return tokens


def get_headers(account: Optional[str] = None) -> dict:
    """Get authorization headers."""
    creds = get_credentials(account)

    if creds.get("type") == "bot":
        return {"Authorization": f"Bot {creds['bot_token']}"}
    else:
        return {"Authorization": f"Bearer {creds['access_token']}"}


def api_request(
    method: str,
    endpoint: str,
    account: Optional[str] = None,
    data: dict = None,
    params: dict = None,
) -> dict:
    """Make Discord API request."""
    headers = get_headers(account)
    url = f"{DISCORD_API_BASE}{endpoint}"

    if method.upper() == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif method.upper() == "POST":
        headers["Content-Type"] = "application/json"
        response = requests.post(url, headers=headers, json=data)
    elif method.upper() == "PUT":
        headers["Content-Type"] = "application/json"
        response = requests.put(url, headers=headers, json=data)
    elif method.upper() == "DELETE":
        response = requests.delete(url, headers=headers)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if response.status_code >= 400:
        try:
            error_data = response.json()
        except:
            error_data = {"message": response.text}
        return {"error": True, "status": response.status_code, "details": error_data}

    if response.status_code == 204:
        return {"success": True}

    try:
        return response.json()
    except:
        return {"success": True, "status": response.status_code}


# ============ Commands ============


def cmd_accounts(args):
    """List authenticated accounts."""
    accounts = list_accounts()
    if not accounts:
        print(json.dumps({"accounts": [], "message": "No accounts authenticated"}))
    else:
        print(json.dumps({"accounts": accounts}, indent=2))


def cmd_login(args):
    """Authenticate with Discord."""
    config = get_client_config()

    if args.bot:
        # Bot token authentication
        if "bot_token" not in config:
            print(json.dumps({"error": "No bot_token in credentials.json"}))
            sys.exit(1)

        tokens = {
            "type": "bot",
            "bot_token": config["bot_token"],
        }

        # Verify bot token
        headers = {"Authorization": f"Bot {config['bot_token']}"}
        response = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)

        if response.status_code != 200:
            print(json.dumps({"error": "Invalid bot token", "details": response.text}))
            sys.exit(1)

        user_data = response.json()
        tokens["user_id"] = user_data.get("id")
        tokens["username"] = user_data.get("username")
    else:
        # OAuth2 flow
        tokens = do_oauth_flow(config)

    # Save tokens
    account_name = args.account or tokens.get("username", "default")
    token_path = get_token_path(account_name)
    with open(token_path, "w") as f:
        json.dump(tokens, f, indent=2)

    print(json.dumps({
        "success": True,
        "type": tokens.get("type"),
        "username": tokens.get("username"),
        "user_id": tokens.get("user_id"),
        "account": account_name,
    }, indent=2))


def cmd_logout(args):
    """Remove account credentials."""
    token_path = get_token_path(args.account)
    if token_path.exists():
        token_path.unlink()
        print(json.dumps({"success": True, "message": f"Logged out: {args.account or 'default'}"}))
    else:
        print(json.dumps({"success": False, "message": "Account not found"}))


def cmd_me(args):
    """Get current user info."""
    result = api_request("GET", "/users/@me", account=args.account)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_guilds(args):
    """List guilds (servers) the user/bot is in."""
    result = api_request("GET", "/users/@me/guilds", account=args.account)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    guilds = [{
        "id": g["id"],
        "name": g["name"],
        "owner": g.get("owner", False),
        "permissions": g.get("permissions"),
    } for g in result]

    print(json.dumps({"guilds": guilds, "count": len(guilds)}, indent=2))


def cmd_channels(args):
    """List channels in a guild."""
    result = api_request("GET", f"/guilds/{args.guild_id}/channels", account=args.account)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Filter to text channels
    channels = [{
        "id": c["id"],
        "name": c["name"],
        "type": c["type"],
        "position": c.get("position"),
    } for c in result if c["type"] in [0, 5]]  # 0=text, 5=announcement

    print(json.dumps({"channels": channels, "count": len(channels)}, indent=2))


def cmd_send(args):
    """Send a message to a channel."""
    data = {"content": args.message}

    result = api_request(
        "POST",
        f"/channels/{args.channel_id}/messages",
        account=args.account,
        data=data,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({
        "success": True,
        "message_id": result.get("id"),
        "channel_id": args.channel_id,
    }, indent=2))


def cmd_messages(args):
    """Get messages from a channel."""
    params = {"limit": min(args.limit, 100)}

    result = api_request(
        "GET",
        f"/channels/{args.channel_id}/messages",
        account=args.account,
        params=params,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    messages = [{
        "id": m["id"],
        "content": m["content"],
        "author": m["author"]["username"],
        "author_id": m["author"]["id"],
        "timestamp": m["timestamp"],
    } for m in result]

    print(json.dumps({"messages": messages, "count": len(messages)}, indent=2))


def cmd_reply(args):
    """Reply to a message."""
    data = {
        "content": args.message,
        "message_reference": {"message_id": args.message_id},
    }

    result = api_request(
        "POST",
        f"/channels/{args.channel_id}/messages",
        account=args.account,
        data=data,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({
        "success": True,
        "message_id": result.get("id"),
        "reply_to": args.message_id,
    }, indent=2))


def cmd_react(args):
    """Add reaction to a message."""
    # URL encode the emoji
    emoji = args.emoji
    if not emoji.startswith("<"):  # Not a custom emoji
        import urllib.parse
        emoji = urllib.parse.quote(emoji)

    result = api_request(
        "PUT",
        f"/channels/{args.channel_id}/messages/{args.message_id}/reactions/{emoji}/@me",
        account=args.account,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "emoji": args.emoji}, indent=2))


def cmd_dm(args):
    """Send a direct message."""
    # Create DM channel
    dm_result = api_request(
        "POST",
        "/users/@me/channels",
        account=args.account,
        data={"recipient_id": args.user_id},
    )

    if dm_result.get("error"):
        print(json.dumps(dm_result, indent=2))
        sys.exit(1)

    channel_id = dm_result["id"]

    # Send message
    result = api_request(
        "POST",
        f"/channels/{channel_id}/messages",
        account=args.account,
        data={"content": args.message},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({
        "success": True,
        "message_id": result.get("id"),
        "user_id": args.user_id,
    }, indent=2))


def cmd_members(args):
    """List members of a guild."""
    params = {"limit": min(args.limit, 1000)}

    result = api_request(
        "GET",
        f"/guilds/{args.guild_id}/members",
        account=args.account,
        params=params,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    members = [{
        "user_id": m["user"]["id"],
        "username": m["user"]["username"],
        "nick": m.get("nick"),
        "joined_at": m.get("joined_at"),
    } for m in result]

    print(json.dumps({"members": members, "count": len(members)}, indent=2))


def cmd_search(args):
    """Search messages in a guild (bot only)."""
    params = {
        "content": args.query,
    }

    result = api_request(
        "GET",
        f"/guilds/{args.guild_id}/messages/search",
        account=args.account,
        params=params,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    messages = []
    for group in result.get("messages", []):
        for m in group:
            messages.append({
                "id": m["id"],
                "content": m["content"],
                "author": m["author"]["username"],
                "channel_id": m["channel_id"],
                "timestamp": m["timestamp"],
            })

    print(json.dumps({
        "query": args.query,
        "messages": messages,
        "total": result.get("total_results", len(messages)),
    }, indent=2))


def add_account_arg(parser):
    """Add --account argument."""
    parser.add_argument("--account", "-a", help="Account to use")


def main():
    parser = argparse.ArgumentParser(description="Discord Skill")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Accounts
    accounts_parser = subparsers.add_parser("accounts", help="List accounts")
    accounts_parser.set_defaults(func=cmd_accounts)

    login_parser = subparsers.add_parser("login", help="Authenticate")
    login_parser.add_argument("--account", "-a", help="Account label")
    login_parser.add_argument("--bot", "-b", action="store_true", help="Use bot token")
    login_parser.set_defaults(func=cmd_login)

    logout_parser = subparsers.add_parser("logout", help="Remove credentials")
    logout_parser.add_argument("--account", "-a", help="Account to logout")
    logout_parser.set_defaults(func=cmd_logout)

    # User
    me_parser = subparsers.add_parser("me", help="Get current user")
    add_account_arg(me_parser)
    me_parser.set_defaults(func=cmd_me)

    # Guilds
    guilds_parser = subparsers.add_parser("guilds", help="List servers")
    add_account_arg(guilds_parser)
    guilds_parser.set_defaults(func=cmd_guilds)

    # Channels
    channels_parser = subparsers.add_parser("channels", help="List channels")
    channels_parser.add_argument("guild_id", help="Server ID")
    add_account_arg(channels_parser)
    channels_parser.set_defaults(func=cmd_channels)

    # Send
    send_parser = subparsers.add_parser("send", help="Send message")
    send_parser.add_argument("channel_id", help="Channel ID")
    send_parser.add_argument("message", help="Message text")
    add_account_arg(send_parser)
    send_parser.set_defaults(func=cmd_send)

    # Messages
    messages_parser = subparsers.add_parser("messages", help="Get messages")
    messages_parser.add_argument("channel_id", help="Channel ID")
    messages_parser.add_argument("--limit", "-l", type=int, default=20)
    add_account_arg(messages_parser)
    messages_parser.set_defaults(func=cmd_messages)

    # Reply
    reply_parser = subparsers.add_parser("reply", help="Reply to message")
    reply_parser.add_argument("channel_id", help="Channel ID")
    reply_parser.add_argument("message_id", help="Message ID to reply to")
    reply_parser.add_argument("message", help="Reply text")
    add_account_arg(reply_parser)
    reply_parser.set_defaults(func=cmd_reply)

    # React
    react_parser = subparsers.add_parser("react", help="Add reaction")
    react_parser.add_argument("channel_id", help="Channel ID")
    react_parser.add_argument("message_id", help="Message ID")
    react_parser.add_argument("emoji", help="Emoji to react with")
    add_account_arg(react_parser)
    react_parser.set_defaults(func=cmd_react)

    # DM
    dm_parser = subparsers.add_parser("dm", help="Send direct message")
    dm_parser.add_argument("user_id", help="User ID")
    dm_parser.add_argument("message", help="Message text")
    add_account_arg(dm_parser)
    dm_parser.set_defaults(func=cmd_dm)

    # Members
    members_parser = subparsers.add_parser("members", help="List server members")
    members_parser.add_argument("guild_id", help="Server ID")
    members_parser.add_argument("--limit", "-l", type=int, default=100)
    add_account_arg(members_parser)
    members_parser.set_defaults(func=cmd_members)

    # Search
    search_parser = subparsers.add_parser("search", help="Search messages")
    search_parser.add_argument("guild_id", help="Server ID")
    search_parser.add_argument("query", help="Search query")
    add_account_arg(search_parser)
    search_parser.set_defaults(func=cmd_search)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
