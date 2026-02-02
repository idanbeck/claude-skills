#!/usr/bin/env python3
"""
Twitter/X Skill - Post, read, and engage on Twitter/X.

Supports multiple accounts with OAuth 2.0 PKCE flow.

Usage:
    python twitter_skill.py me [--account LABEL]
    python twitter_skill.py tweet --text "..." [--reply-to ID] [--quote ID]
    python twitter_skill.py delete-tweet TWEET_ID
    python twitter_skill.py get-tweet TWEET_ID
    python twitter_skill.py timeline [--count N]
    python twitter_skill.py mentions [--count N]
    python twitter_skill.py user-tweets USERNAME [--count N]
    python twitter_skill.py search "query" [--count N]
    python twitter_skill.py like TWEET_ID
    python twitter_skill.py unlike TWEET_ID
    python twitter_skill.py retweet TWEET_ID
    python twitter_skill.py unretweet TWEET_ID
    python twitter_skill.py bookmark TWEET_ID
    python twitter_skill.py unbookmark TWEET_ID
    python twitter_skill.py bookmarks [--count N]
    python twitter_skill.py follow USERNAME
    python twitter_skill.py unfollow USERNAME
    python twitter_skill.py followers [USERNAME] [--count N]
    python twitter_skill.py following [USERNAME] [--count N]
    python twitter_skill.py accounts
    python twitter_skill.py login [--account LABEL]
    python twitter_skill.py logout [--account EMAIL]
"""

import argparse
import base64
import hashlib
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
ACCOUNTS_META_FILE = SKILL_DIR / "accounts.json"

# Twitter OAuth 2.0 endpoints
TWITTER_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
TWITTER_API_BASE = "https://api.twitter.com/2"

# OAuth 2.0 scopes
# See: https://developer.twitter.com/en/docs/authentication/oauth-2-0/authorization-code
SCOPES = [
    "tweet.read",
    "tweet.write",
    "tweet.moderate.write",
    "users.read",
    "follows.read",
    "follows.write",
    "offline.access",  # Required for refresh tokens
    "like.read",
    "like.write",
    "bookmark.read",
    "bookmark.write",
    "list.read",
    "mute.read",
    "block.read",
]


def get_client_config() -> dict:
    """Load OAuth client configuration."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)

    print("\n" + "=" * 60)
    print("FIRST-TIME SETUP REQUIRED")
    print("=" * 60)
    print("\nTo use Twitter Skill, you need to create a Twitter Developer App.")
    print("This is a one-time setup:\n")
    print("1. Go to: https://developer.twitter.com/en/portal/dashboard")
    print("2. Create a Project and App (or use existing)")
    print("3. In your App settings:")
    print("   - Set up User Authentication Settings")
    print("   - App permissions: Read and write")
    print("   - Type of App: Web App, Automated App or Bot")
    print("   - Callback URI: http://localhost:9998")
    print("   - Website URL: http://localhost (or your site)")
    print("4. Note the Client ID and Client Secret from Keys and Tokens")
    print("5. Create credentials.json in this directory:")
    print(f"   {CREDENTIALS_FILE}")
    print('   {"client_id": "YOUR_CLIENT_ID", "client_secret": "YOUR_CLIENT_SECRET"}')
    print("\n** IMPORTANT: Twitter API Access Levels **")
    print("   - Free: Write-only, 1,500 tweets/month, no read access")
    print("   - Basic ($100/mo): Read + Write, 10K tweets/month read")
    print("   - Pro ($5,000/mo): Full access")
    print("\nThen run this command again.")
    print("=" * 60 + "\n")

    try:
        response = input("Open Twitter Developer Portal now? [Y/n]: ").strip().lower()
        if response != "n":
            webbrowser.open("https://developer.twitter.com/en/portal/dashboard")
    except:
        pass

    sys.exit(1)


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge."""
    # Code verifier: 43-128 character random string
    code_verifier = secrets.token_urlsafe(64)[:128]

    # Code challenge: base64url(sha256(code_verifier))
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    return code_verifier, code_challenge


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to receive OAuth callback."""

    def log_message(self, format, *args):
        pass  # Suppress logging

    def do_GET(self):
        """Handle the OAuth callback."""
        query = parse_qs(urlparse(self.path).query)

        if "code" in query:
            self.server.auth_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"""
                <html><body style="font-family: system-ui; text-align: center; padding: 50px;">
                <h1>Authentication Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                <script>window.close();</script>
                </body></html>
            """
            )
        elif "error" in query:
            self.server.auth_error = query.get("error", ["Unknown error"])[0]
            error_desc = query.get("error_description", [""])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h1>Error: {self.server.auth_error}</h1><p>{error_desc}</p></body></html>".encode()
            )
        else:
            self.send_response(400)
            self.end_headers()


def do_oauth_flow(client_config: dict) -> dict:
    """Perform OAuth 2.0 PKCE flow with browser and local callback server."""
    client_id = client_config["client_id"]
    client_secret = client_config.get("client_secret")

    # Fixed port for callback
    port = 9998
    redirect_uri = f"http://localhost:{port}"

    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Build authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{TWITTER_AUTH_URL}?{urlencode(auth_params)}"

    # Start local server
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.auth_code = None
    server.auth_error = None
    server.timeout = 120  # 2 minute timeout

    print("\n" + "=" * 50)
    print("  AUTHENTICATING WITH TWITTER/X")
    print("=" * 50)
    print(f"Opening browser for authentication.")
    print(f"If browser doesn't open, visit:\n{auth_url}\n")

    # Open browser
    webbrowser.open(auth_url)

    # Wait for callback
    while server.auth_code is None and server.auth_error is None:
        server.handle_request()

    if server.auth_error:
        print(f"Authentication error: {server.auth_error}")
        sys.exit(1)

    # Exchange code for tokens
    token_data = {
        "grant_type": "authorization_code",
        "code": server.auth_code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    # Twitter requires Basic auth for confidential clients
    auth = None
    if client_secret:
        auth = (client_id, client_secret)
        # Remove client_id from body when using Basic auth
        del token_data["client_id"]

    response = requests.post(
        TWITTER_TOKEN_URL,
        data=token_data,
        auth=auth,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        print(f"Token exchange failed: {response.text}")
        sys.exit(1)

    tokens = response.json()

    # Calculate and store absolute expiry time
    if "expires_in" in tokens:
        expiry = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        tokens["expiry"] = expiry.isoformat() + "Z"

    # Get user profile info
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_response = requests.get(
        f"{TWITTER_API_BASE}/users/me",
        headers=headers,
        params={"user.fields": "id,name,username,profile_image_url,description"},
    )

    if user_response.status_code == 200:
        user_data = user_response.json().get("data", {})
        tokens["user_id"] = user_data.get("id")
        tokens["username"] = user_data.get("username")
        tokens["name"] = user_data.get("name")

    return tokens


def refresh_tokens(client_config: dict, refresh_token: str) -> dict:
    """Refresh access token using refresh token."""
    client_id = client_config["client_id"]
    client_secret = client_config.get("client_secret")

    token_data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }

    auth = None
    if client_secret:
        auth = (client_id, client_secret)
        del token_data["client_id"]

    response = requests.post(
        TWITTER_TOKEN_URL,
        data=token_data,
        auth=auth,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        return None

    tokens = response.json()

    if "expires_in" in tokens:
        expiry = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
        tokens["expiry"] = expiry.isoformat() + "Z"

    return tokens


def get_token_path(account: Optional[str] = None) -> Path:
    """Get token file path for an account."""
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)

    if account:
        safe_name = re.sub(r"[^\w\-.]", "_", account.lower())
        return TOKENS_DIR / f"token_{safe_name}.json"

    tokens = list(TOKENS_DIR.glob("token_*.json"))
    if tokens:
        return tokens[0]

    return TOKENS_DIR / "token_default.json"


def load_accounts_meta() -> dict:
    """Load account metadata."""
    if ACCOUNTS_META_FILE.exists():
        try:
            with open(ACCOUNTS_META_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_accounts_meta(meta: dict):
    """Save account metadata."""
    with open(ACCOUNTS_META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def set_account_meta(username: str, label: str = None, is_default: bool = False):
    """Set metadata for an account."""
    meta = load_accounts_meta()
    if username not in meta:
        meta[username] = {}
    if label:
        meta[username]["label"] = label
    if is_default:
        for u in meta:
            meta[u]["is_default"] = False
        meta[username]["is_default"] = True
    save_accounts_meta(meta)


def list_accounts() -> list[dict]:
    """List all authenticated accounts."""
    accounts = []
    meta = load_accounts_meta()

    if TOKENS_DIR.exists():
        for token_file in TOKENS_DIR.glob("token_*.json"):
            try:
                with open(token_file) as f:
                    data = json.load(f)
                    username = data.get("username", "unknown")
                    name = data.get("name", "")
                    account_meta = meta.get(username, {})
                    accounts.append(
                        {
                            "username": username,
                            "name": name,
                            "user_id": data.get("user_id"),
                            "label": account_meta.get("label", ""),
                            "is_default": account_meta.get("is_default", False),
                            "file": str(token_file),
                        }
                    )
            except:
                pass
    return accounts


def resolve_account(account: Optional[str]) -> Optional[str]:
    """Resolve account alias to username."""
    if not account:
        return None

    if account.startswith("@"):
        return account[1:]

    meta = load_accounts_meta()
    for username, info in meta.items():
        if info.get("label", "").lower() == account.lower():
            return username

    return account


def get_credentials(account: Optional[str] = None) -> dict:
    """Get or refresh OAuth2 credentials for an account."""
    client_config = get_client_config()

    account_name = resolve_account(account)
    token_path = get_token_path(account_name or account)

    tokens = None

    if token_path.exists():
        try:
            with open(token_path) as f:
                tokens = json.load(f)

            # Check if expired
            if "expiry" in tokens:
                expiry = datetime.fromisoformat(tokens["expiry"].replace("Z", "+00:00"))
                if datetime.now(expiry.tzinfo) >= expiry:
                    # Try to refresh
                    if "refresh_token" in tokens:
                        print("Token expired, refreshing...")
                        new_tokens = refresh_tokens(client_config, tokens["refresh_token"])
                        if new_tokens:
                            # Preserve user info
                            new_tokens["user_id"] = tokens.get("user_id")
                            new_tokens["username"] = tokens.get("username")
                            new_tokens["name"] = tokens.get("name")
                            tokens = new_tokens
                            with open(token_path, "w") as f:
                                json.dump(tokens, f, indent=2)
                        else:
                            print("Refresh failed, re-authenticating...")
                            tokens = None
                    else:
                        print("Token expired, re-authenticating...")
                        tokens = None
        except Exception as e:
            print(f"Warning: Could not load existing token: {e}")
            tokens = None

    if not tokens:
        tokens = do_oauth_flow(client_config)
        token_path = get_token_path(tokens.get("username", account or "default"))
        with open(token_path, "w") as f:
            json.dump(tokens, f, indent=2)
        print(f"Authenticated as: @{tokens.get('username', 'unknown')}")

    return tokens


def api_request(
    method: str,
    endpoint: str,
    account: Optional[str] = None,
    data: dict = None,
    params: dict = None,
) -> dict:
    """Make an authenticated Twitter API request."""
    tokens = get_credentials(account)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    url = f"{TWITTER_API_BASE}{endpoint}"

    if method.upper() == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif method.upper() == "POST":
        headers["Content-Type"] = "application/json"
        response = requests.post(url, headers=headers, json=data, params=params)
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


def get_user_id(account: Optional[str] = None) -> str:
    """Get the authenticated user's ID."""
    tokens = get_credentials(account)
    return tokens.get("user_id")


def get_user_id_by_username(username: str, account: Optional[str] = None) -> Optional[str]:
    """Get a user's ID by their username."""
    username = username.lstrip("@")
    result = api_request("GET", f"/users/by/username/{username}", account=account)
    if result.get("error"):
        return None
    return result.get("data", {}).get("id")


# ============ Commands ============


def cmd_accounts(args):
    """List authenticated accounts."""
    accounts = list_accounts()
    if not accounts:
        print(json.dumps({"accounts": [], "message": "No accounts authenticated yet"}))
    else:
        print(json.dumps({"accounts": accounts}, indent=2))


def cmd_login(args):
    """Authenticate a new account."""
    client_config = get_client_config()
    tokens = do_oauth_flow(client_config)

    username = tokens.get("username", args.account or "default")
    token_path = get_token_path(username)
    with open(token_path, "w") as f:
        json.dump(tokens, f, indent=2)

    if args.account and tokens.get("username"):
        set_account_meta(tokens["username"], label=args.account)

    print(
        json.dumps(
            {
                "success": True,
                "username": tokens.get("username"),
                "name": tokens.get("name"),
                "user_id": tokens.get("user_id"),
                "label": args.account or "",
            },
            indent=2,
        )
    )


def cmd_logout(args):
    """Remove an account's credentials."""
    account_name = resolve_account(args.account)
    token_path = get_token_path(account_name)
    if token_path.exists():
        token_path.unlink()
        print(
            json.dumps(
                {"success": True, "message": f"Logged out: {args.account or 'default account'}"}
            )
        )
    else:
        print(json.dumps({"success": False, "message": "Account not found"}))


def cmd_me(args):
    """Get authenticated user's profile."""
    tokens = get_credentials(args.account)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = requests.get(
        f"{TWITTER_API_BASE}/users/me",
        headers=headers,
        params={
            "user.fields": "id,name,username,description,profile_image_url,public_metrics,created_at,verified"
        },
    )

    if response.status_code != 200:
        print(json.dumps({"error": response.text}))
        sys.exit(1)

    data = response.json().get("data", {})
    print(json.dumps(data, indent=2))


def cmd_tweet(args):
    """Create a tweet."""
    tweet_data = {"text": args.text}

    if args.reply_to:
        tweet_data["reply"] = {"in_reply_to_tweet_id": args.reply_to}

    if args.quote:
        tweet_data["quote_tweet_id"] = args.quote

    result = api_request("POST", "/tweets", account=args.account, data=tweet_data)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "tweet": result.get("data", {})}, indent=2))


def cmd_delete_tweet(args):
    """Delete a tweet."""
    result = api_request("DELETE", f"/tweets/{args.tweet_id}", account=args.account)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "deleted": args.tweet_id}, indent=2))


def cmd_get_tweet(args):
    """Get a single tweet."""
    params = {
        "tweet.fields": "id,text,author_id,created_at,public_metrics,conversation_id,in_reply_to_user_id",
        "expansions": "author_id",
        "user.fields": "name,username",
    }

    result = api_request("GET", f"/tweets/{args.tweet_id}", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_timeline(args):
    """Get home timeline."""
    user_id = get_user_id(args.account)
    params = {
        "max_results": min(args.count, 100),
        "tweet.fields": "id,text,author_id,created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "name,username",
    }

    result = api_request(
        "GET", f"/users/{user_id}/timelines/reverse_chronological", account=args.account, params=params
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_mentions(args):
    """Get mentions."""
    user_id = get_user_id(args.account)
    params = {
        "max_results": min(args.count, 100),
        "tweet.fields": "id,text,author_id,created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "name,username",
    }

    result = api_request("GET", f"/users/{user_id}/mentions", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_user_tweets(args):
    """Get tweets from a specific user."""
    username = args.username.lstrip("@")
    user_id = get_user_id_by_username(username, args.account)

    if not user_id:
        print(json.dumps({"error": f"User @{username} not found"}))
        sys.exit(1)

    params = {
        "max_results": min(args.count, 100),
        "tweet.fields": "id,text,created_at,public_metrics",
    }

    result = api_request("GET", f"/users/{user_id}/tweets", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_search(args):
    """Search tweets."""
    params = {
        "query": args.query,
        "max_results": min(args.count, 100),
        "tweet.fields": "id,text,author_id,created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "name,username",
    }

    result = api_request("GET", "/tweets/search/recent", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_like(args):
    """Like a tweet."""
    user_id = get_user_id(args.account)
    result = api_request(
        "POST",
        f"/users/{user_id}/likes",
        account=args.account,
        data={"tweet_id": args.tweet_id},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "liked": args.tweet_id}, indent=2))


def cmd_unlike(args):
    """Unlike a tweet."""
    user_id = get_user_id(args.account)
    result = api_request(
        "DELETE", f"/users/{user_id}/likes/{args.tweet_id}", account=args.account
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "unliked": args.tweet_id}, indent=2))


def cmd_retweet(args):
    """Retweet a tweet."""
    user_id = get_user_id(args.account)
    result = api_request(
        "POST",
        f"/users/{user_id}/retweets",
        account=args.account,
        data={"tweet_id": args.tweet_id},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "retweeted": args.tweet_id}, indent=2))


def cmd_unretweet(args):
    """Remove a retweet."""
    user_id = get_user_id(args.account)
    result = api_request(
        "DELETE", f"/users/{user_id}/retweets/{args.tweet_id}", account=args.account
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "unretweeted": args.tweet_id}, indent=2))


def cmd_bookmark(args):
    """Bookmark a tweet."""
    user_id = get_user_id(args.account)
    result = api_request(
        "POST",
        f"/users/{user_id}/bookmarks",
        account=args.account,
        data={"tweet_id": args.tweet_id},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "bookmarked": args.tweet_id}, indent=2))


def cmd_unbookmark(args):
    """Remove a bookmark."""
    user_id = get_user_id(args.account)
    result = api_request(
        "DELETE", f"/users/{user_id}/bookmarks/{args.tweet_id}", account=args.account
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "unbookmarked": args.tweet_id}, indent=2))


def cmd_bookmarks(args):
    """List bookmarks."""
    user_id = get_user_id(args.account)
    params = {
        "max_results": min(args.count, 100),
        "tweet.fields": "id,text,author_id,created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "name,username",
    }

    result = api_request("GET", f"/users/{user_id}/bookmarks", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_follow(args):
    """Follow a user."""
    user_id = get_user_id(args.account)
    target_id = get_user_id_by_username(args.username, args.account)

    if not target_id:
        print(json.dumps({"error": f"User @{args.username} not found"}))
        sys.exit(1)

    result = api_request(
        "POST",
        f"/users/{user_id}/following",
        account=args.account,
        data={"target_user_id": target_id},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "following": args.username}, indent=2))


def cmd_unfollow(args):
    """Unfollow a user."""
    user_id = get_user_id(args.account)
    target_id = get_user_id_by_username(args.username, args.account)

    if not target_id:
        print(json.dumps({"error": f"User @{args.username} not found"}))
        sys.exit(1)

    result = api_request(
        "DELETE", f"/users/{user_id}/following/{target_id}", account=args.account
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "unfollowed": args.username}, indent=2))


def cmd_followers(args):
    """List followers."""
    if args.username:
        target_id = get_user_id_by_username(args.username, args.account)
        if not target_id:
            print(json.dumps({"error": f"User @{args.username} not found"}))
            sys.exit(1)
    else:
        target_id = get_user_id(args.account)

    params = {
        "max_results": min(args.count, 1000),
        "user.fields": "id,name,username,description,public_metrics",
    }

    result = api_request("GET", f"/users/{target_id}/followers", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_following(args):
    """List accounts being followed."""
    if args.username:
        target_id = get_user_id_by_username(args.username, args.account)
        if not target_id:
            print(json.dumps({"error": f"User @{args.username} not found"}))
            sys.exit(1)
    else:
        target_id = get_user_id(args.account)

    params = {
        "max_results": min(args.count, 1000),
        "user.fields": "id,name,username,description,public_metrics",
    }

    result = api_request("GET", f"/users/{target_id}/following", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def add_account_arg(parser):
    """Add --account argument to a parser."""
    parser.add_argument(
        "--account",
        "-a",
        help="Account to use (username or label, default: first authenticated account)",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Twitter/X Skill - Post, read, and engage on Twitter/X"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Account management
    accounts_parser = subparsers.add_parser("accounts", help="List authenticated accounts")
    accounts_parser.set_defaults(func=cmd_accounts)

    login_parser = subparsers.add_parser("login", help="Authenticate a new account")
    login_parser.add_argument("--account", "-a", help="Label for this account")
    login_parser.set_defaults(func=cmd_login)

    logout_parser = subparsers.add_parser("logout", help="Remove account credentials")
    logout_parser.add_argument("--account", "-a", help="Account to logout (username or label)")
    logout_parser.set_defaults(func=cmd_logout)

    # Profile
    me_parser = subparsers.add_parser("me", help="Get authenticated user's profile")
    add_account_arg(me_parser)
    me_parser.set_defaults(func=cmd_me)

    # Tweets
    tweet_parser = subparsers.add_parser("tweet", help="Create a tweet")
    tweet_parser.add_argument("--text", "-t", required=True, help="Tweet text")
    tweet_parser.add_argument("--reply-to", help="Tweet ID to reply to")
    tweet_parser.add_argument("--quote", help="Tweet ID to quote")
    add_account_arg(tweet_parser)
    tweet_parser.set_defaults(func=cmd_tweet)

    delete_tweet_parser = subparsers.add_parser("delete-tweet", help="Delete a tweet")
    delete_tweet_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(delete_tweet_parser)
    delete_tweet_parser.set_defaults(func=cmd_delete_tweet)

    get_tweet_parser = subparsers.add_parser("get-tweet", help="Get a single tweet")
    get_tweet_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(get_tweet_parser)
    get_tweet_parser.set_defaults(func=cmd_get_tweet)

    # Timelines
    timeline_parser = subparsers.add_parser("timeline", help="Get home timeline")
    timeline_parser.add_argument("--count", "-c", type=int, default=20, help="Number of tweets")
    add_account_arg(timeline_parser)
    timeline_parser.set_defaults(func=cmd_timeline)

    mentions_parser = subparsers.add_parser("mentions", help="Get mentions")
    mentions_parser.add_argument("--count", "-c", type=int, default=20, help="Number of tweets")
    add_account_arg(mentions_parser)
    mentions_parser.set_defaults(func=cmd_mentions)

    user_tweets_parser = subparsers.add_parser("user-tweets", help="Get tweets from a user")
    user_tweets_parser.add_argument("username", help="Username (with or without @)")
    user_tweets_parser.add_argument("--count", "-c", type=int, default=20, help="Number of tweets")
    add_account_arg(user_tweets_parser)
    user_tweets_parser.set_defaults(func=cmd_user_tweets)

    # Search
    search_parser = subparsers.add_parser("search", help="Search tweets")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--count", "-c", type=int, default=20, help="Number of results")
    add_account_arg(search_parser)
    search_parser.set_defaults(func=cmd_search)

    # Likes
    like_parser = subparsers.add_parser("like", help="Like a tweet")
    like_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(like_parser)
    like_parser.set_defaults(func=cmd_like)

    unlike_parser = subparsers.add_parser("unlike", help="Unlike a tweet")
    unlike_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(unlike_parser)
    unlike_parser.set_defaults(func=cmd_unlike)

    # Retweets
    retweet_parser = subparsers.add_parser("retweet", help="Retweet a tweet")
    retweet_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(retweet_parser)
    retweet_parser.set_defaults(func=cmd_retweet)

    unretweet_parser = subparsers.add_parser("unretweet", help="Remove a retweet")
    unretweet_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(unretweet_parser)
    unretweet_parser.set_defaults(func=cmd_unretweet)

    # Bookmarks
    bookmark_parser = subparsers.add_parser("bookmark", help="Bookmark a tweet")
    bookmark_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(bookmark_parser)
    bookmark_parser.set_defaults(func=cmd_bookmark)

    unbookmark_parser = subparsers.add_parser("unbookmark", help="Remove a bookmark")
    unbookmark_parser.add_argument("tweet_id", help="Tweet ID")
    add_account_arg(unbookmark_parser)
    unbookmark_parser.set_defaults(func=cmd_unbookmark)

    bookmarks_parser = subparsers.add_parser("bookmarks", help="List bookmarks")
    bookmarks_parser.add_argument("--count", "-c", type=int, default=20, help="Number of tweets")
    add_account_arg(bookmarks_parser)
    bookmarks_parser.set_defaults(func=cmd_bookmarks)

    # Following
    follow_parser = subparsers.add_parser("follow", help="Follow a user")
    follow_parser.add_argument("username", help="Username to follow")
    add_account_arg(follow_parser)
    follow_parser.set_defaults(func=cmd_follow)

    unfollow_parser = subparsers.add_parser("unfollow", help="Unfollow a user")
    unfollow_parser.add_argument("username", help="Username to unfollow")
    add_account_arg(unfollow_parser)
    unfollow_parser.set_defaults(func=cmd_unfollow)

    followers_parser = subparsers.add_parser("followers", help="List followers")
    followers_parser.add_argument("username", nargs="?", help="Username (default: self)")
    followers_parser.add_argument("--count", "-c", type=int, default=100, help="Max followers")
    add_account_arg(followers_parser)
    followers_parser.set_defaults(func=cmd_followers)

    following_parser = subparsers.add_parser("following", help="List following")
    following_parser.add_argument("username", nargs="?", help="Username (default: self)")
    following_parser.add_argument("--count", "-c", type=int, default=100, help="Max following")
    add_account_arg(following_parser)
    following_parser.set_defaults(func=cmd_following)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
