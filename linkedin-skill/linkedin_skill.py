#!/usr/bin/env python3
"""
LinkedIn Skill - Post, comment, and react on LinkedIn profiles and company pages.

Supports multiple accounts with seamless OAuth browser flow.

Usage:
    python linkedin_skill.py me [--account LABEL]
    python linkedin_skill.py organizations [--account LABEL]
    python linkedin_skill.py post --text "..." [--author ORG_URN] [--visibility PUBLIC|CONNECTIONS]
    python linkedin_skill.py list-posts [--author URN] [--count N] [--account LABEL]
    python linkedin_skill.py get-post POST_URN [--account LABEL]
    python linkedin_skill.py edit-post POST_URN --text "..." [--account LABEL]
    python linkedin_skill.py delete-post POST_URN [--account LABEL]
    python linkedin_skill.py comments POST_URN [--account LABEL]
    python linkedin_skill.py comment POST_URN --text "..." [--account LABEL]
    python linkedin_skill.py reply COMMENT_URN --text "..." [--account LABEL]
    python linkedin_skill.py delete-comment COMMENT_URN [--account LABEL]
    python linkedin_skill.py react POST_URN --type LIKE [--account LABEL]
    python linkedin_skill.py unreact POST_URN [--account LABEL]
    python linkedin_skill.py reactions POST_URN [--account LABEL]
    python linkedin_skill.py accounts
    python linkedin_skill.py login [--account LABEL]
    python linkedin_skill.py logout [--account EMAIL]
"""

import argparse
import json
import os
import re
import secrets
import socket
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

# LinkedIn OAuth endpoints
LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_API_BASE = "https://api.linkedin.com"

# LinkedIn API version header (required for all API calls)
LINKEDIN_VERSION = "202501"

# OAuth scopes
# Basic: openid, profile, email
# Member posting: w_member_social
# Organization posting: w_organization_social (requires Marketing Platform approval)
SCOPES = [
    "openid",
    "profile",
    "email",
    "w_member_social",
]

# Default OAuth client - user must override with their own credentials.json
DEFAULT_CLIENT_CONFIG = {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
}


def get_client_config() -> dict:
    """Load OAuth client configuration."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)

    if DEFAULT_CLIENT_CONFIG["client_id"].startswith("YOUR_"):
        print("\n" + "=" * 60)
        print("FIRST-TIME SETUP REQUIRED")
        print("=" * 60)
        print("\nTo use LinkedIn Skill, you need to create a LinkedIn OAuth app.")
        print("This is a one-time setup:\n")
        print("1. Go to: https://www.linkedin.com/developers/apps")
        print("2. Click 'Create app'")
        print("3. Fill in app details:")
        print("   - App name: LinkedIn Skill (or anything)")
        print("   - LinkedIn Page: Select or create one")
        print("   - App logo: Any image")
        print("4. On the Auth tab:")
        print("   - Add redirect URL: http://localhost (any port)")
        print("   - Note the Client ID and Client Secret")
        print("5. On the Products tab:")
        print("   - Request access to 'Share on LinkedIn'")
        print("   - Request access to 'Sign In with LinkedIn using OpenID Connect'")
        print("6. Create credentials.json in this directory:")
        print(f"   {CREDENTIALS_FILE}")
        print('   {"client_id": "YOUR_ID", "client_secret": "YOUR_SECRET"}')
        print("\nThen run this command again.")
        print("=" * 60 + "\n")

        try:
            response = input("Open LinkedIn Developers now? [Y/n]: ").strip().lower()
            if response != "n":
                webbrowser.open("https://www.linkedin.com/developers/apps")
        except:
            pass

        sys.exit(1)

    return DEFAULT_CLIENT_CONFIG


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


def do_oauth_flow(client_config: dict, force_consent: bool = False) -> dict:
    """Perform OAuth flow with browser and local callback server."""
    client_id = client_config["client_id"]
    client_secret = client_config["client_secret"]

    # Use fixed port to match LinkedIn redirect URI registration
    port = 9999
    redirect_uri = f"http://localhost:{port}"

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Build authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(SCOPES),
    }

    auth_url = f"{LINKEDIN_AUTH_URL}?{urlencode(auth_params)}"

    # Start local server
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.auth_code = None
    server.auth_error = None
    server.timeout = 120  # 2 minute timeout

    print("\n" + "=" * 50)
    print("  AUTHENTICATING WITH LINKEDIN")
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
        "client_secret": client_secret,
    }

    response = requests.post(
        LINKEDIN_TOKEN_URL,
        data=token_data,
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
    headers = get_api_headers(tokens["access_token"])

    # Get basic profile via userinfo endpoint
    user_response = requests.get(
        f"{LINKEDIN_API_BASE}/v2/userinfo",
        headers=headers,
    )

    if user_response.status_code == 200:
        user_data = user_response.json()
        tokens["email"] = user_data.get("email")
        tokens["name"] = user_data.get("name")
        tokens["sub"] = user_data.get("sub")  # LinkedIn member ID

    return tokens


def get_api_headers(access_token: str) -> dict:
    """Get headers required for LinkedIn API calls."""
    return {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def get_token_path(account: Optional[str] = None) -> Path:
    """Get token file path for an account."""
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)

    if account:
        # Sanitize for filename
        safe_name = re.sub(r"[^\w\-.]", "_", account.lower())
        return TOKENS_DIR / f"token_{safe_name}.json"

    # Return default/first token
    tokens = list(TOKENS_DIR.glob("token_*.json"))
    if tokens:
        return tokens[0]

    return TOKENS_DIR / "token_default.json"


def load_accounts_meta() -> dict:
    """Load account metadata (labels, descriptions)."""
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


def set_account_meta(
    email: str,
    label: str = None,
    description: str = None,
    is_default: bool = False,
):
    """Set metadata for an account."""
    meta = load_accounts_meta()
    if email not in meta:
        meta[email] = {}
    if label:
        meta[email]["label"] = label
    if description:
        meta[email]["description"] = description
    if is_default:
        for e in meta:
            meta[e]["is_default"] = False
        meta[email]["is_default"] = True
    save_accounts_meta(meta)


def list_accounts() -> list[dict]:
    """List all authenticated accounts with metadata."""
    accounts = []
    meta = load_accounts_meta()

    if TOKENS_DIR.exists():
        for token_file in TOKENS_DIR.glob("token_*.json"):
            try:
                with open(token_file) as f:
                    data = json.load(f)
                    email = data.get("email", "unknown")
                    name = data.get("name", "")
                    account_meta = meta.get(email, {})
                    accounts.append(
                        {
                            "email": email,
                            "name": name,
                            "label": account_meta.get("label", ""),
                            "description": account_meta.get("description", ""),
                            "is_default": account_meta.get("is_default", False),
                            "file": str(token_file),
                        }
                    )
            except:
                pass
    return accounts


def resolve_account_email(account: Optional[str]) -> Optional[str]:
    """Resolve account alias to actual email address."""
    if not account:
        return None

    # If it looks like an email, return as-is
    if "@" in account:
        return account

    # Check if it's an alias in accounts metadata
    meta = load_accounts_meta()
    for email, info in meta.items():
        if info.get("label", "").lower() == account.lower():
            return email

    return account


def get_credentials(account: Optional[str] = None) -> dict:
    """Get or refresh OAuth2 credentials for an account."""
    client_config = get_client_config()

    # Resolve alias to email first
    account_email = resolve_account_email(account)
    token_path = get_token_path(account_email or account)

    tokens = None

    # Load existing token
    if token_path.exists():
        try:
            with open(token_path) as f:
                tokens = json.load(f)

            # Check if expired
            if "expiry" in tokens:
                expiry = datetime.fromisoformat(tokens["expiry"].replace("Z", "+00:00"))
                if datetime.now(expiry.tzinfo) >= expiry:
                    # Token expired - LinkedIn doesn't support refresh tokens for most apps
                    # Need to re-authenticate
                    print("Token expired, re-authenticating...")
                    tokens = None
        except Exception as e:
            print(f"Warning: Could not load existing token: {e}")
            tokens = None

    if not tokens:
        # Need new authentication
        tokens = do_oauth_flow(client_config)

        # Save token
        token_path = get_token_path(tokens.get("email", account or "default"))
        with open(token_path, "w") as f:
            json.dump(tokens, f, indent=2)

        print(f"Authenticated as: {tokens.get('name', tokens.get('email', 'unknown'))}")

    return tokens


def api_request(
    method: str,
    endpoint: str,
    account: Optional[str] = None,
    data: dict = None,
    params: dict = None,
) -> dict:
    """Make an authenticated LinkedIn API request."""
    tokens = get_credentials(account)
    headers = get_api_headers(tokens["access_token"])

    url = f"{LINKEDIN_API_BASE}{endpoint}"

    if method.upper() == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif method.upper() == "POST":
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


def get_member_urn(account: Optional[str] = None) -> str:
    """Get the authenticated user's member URN."""
    tokens = get_credentials(account)
    sub = tokens.get("sub")
    if sub:
        return f"urn:li:person:{sub}"

    # Fallback: fetch from userinfo
    headers = get_api_headers(tokens["access_token"])
    response = requests.get(f"{LINKEDIN_API_BASE}/v2/userinfo", headers=headers)
    if response.status_code == 200:
        data = response.json()
        return f"urn:li:person:{data.get('sub')}"

    raise ValueError("Could not determine member URN")


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

    # Save token
    email = tokens.get("email", args.account or "default")
    token_path = get_token_path(email)
    with open(token_path, "w") as f:
        json.dump(tokens, f, indent=2)

    # Set label if provided
    if args.account and tokens.get("email"):
        set_account_meta(tokens["email"], label=args.account)

    print(
        json.dumps(
            {
                "success": True,
                "email": tokens.get("email"),
                "name": tokens.get("name"),
                "label": args.account or "",
            },
            indent=2,
        )
    )


def cmd_logout(args):
    """Remove an account's credentials."""
    account_email = resolve_account_email(args.account)
    token_path = get_token_path(account_email)
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
    headers = get_api_headers(tokens["access_token"])

    # Get profile from userinfo
    response = requests.get(f"{LINKEDIN_API_BASE}/v2/userinfo", headers=headers)

    if response.status_code != 200:
        print(json.dumps({"error": response.text}))
        sys.exit(1)

    data = response.json()

    output = {
        "sub": data.get("sub"),
        "name": data.get("name"),
        "given_name": data.get("given_name"),
        "family_name": data.get("family_name"),
        "email": data.get("email"),
        "email_verified": data.get("email_verified"),
        "picture": data.get("picture"),
        "urn": f"urn:li:person:{data.get('sub')}",
    }
    print(json.dumps(output, indent=2))


def cmd_organizations(args):
    """List organizations where user is admin."""
    result = api_request(
        "GET",
        "/v2/organizationAcls",
        account=args.account,
        params={"q": "roleAssignee", "projection": "(elements*(organization~))"},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    orgs = []
    for elem in result.get("elements", []):
        org = elem.get("organization~", {})
        orgs.append(
            {
                "urn": elem.get("organization"),
                "name": org.get("localizedName"),
                "vanityName": org.get("vanityName"),
                "role": elem.get("role"),
            }
        )

    print(json.dumps({"organizations": orgs, "total": len(orgs)}, indent=2))


def cmd_post(args):
    """Create a post."""
    member_urn = get_member_urn(args.account)

    # Determine author (member or organization)
    author = args.author if args.author else member_urn

    # Build post payload
    visibility = args.visibility.upper() if args.visibility else "PUBLIC"

    post_data = {
        "author": author,
        "commentary": args.text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    result = api_request("POST", "/rest/posts", account=args.account, data=post_data)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "post": result}, indent=2))


def cmd_list_posts(args):
    """List posts by author."""
    if args.author:
        author = args.author
    else:
        author = get_member_urn(args.account)

    params = {
        "author": author,
        "q": "author",
        "count": args.count,
        "sortBy": "LAST_MODIFIED",
    }

    result = api_request("GET", "/rest/posts", account=args.account, params=params)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    posts = []
    for post in result.get("elements", []):
        posts.append(
            {
                "urn": post.get("id"),
                "author": post.get("author"),
                "commentary": post.get("commentary"),
                "visibility": post.get("visibility"),
                "lifecycleState": post.get("lifecycleState"),
                "created": post.get("createdAt"),
                "lastModified": post.get("lastModifiedAt"),
            }
        )

    print(json.dumps({"posts": posts, "total": len(posts)}, indent=2))


def cmd_get_post(args):
    """Get a single post."""
    # URL-encode the URN for the path
    post_id = args.post_urn.replace(":", "%3A")

    result = api_request("GET", f"/rest/posts/{post_id}", account=args.account)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result, indent=2))


def cmd_edit_post(args):
    """Edit a post's commentary."""
    post_id = args.post_urn.replace(":", "%3A")

    # LinkedIn uses PATCH for partial updates
    headers = get_api_headers(get_credentials(args.account)["access_token"])
    headers["X-RestLi-Method"] = "PARTIAL_UPDATE"

    patch_data = {
        "patch": {
            "$set": {
                "commentary": args.text,
            }
        }
    }

    url = f"{LINKEDIN_API_BASE}/rest/posts/{post_id}"
    response = requests.post(url, headers=headers, json=patch_data)

    if response.status_code >= 400:
        print(json.dumps({"error": response.text, "status": response.status_code}))
        sys.exit(1)

    print(json.dumps({"success": True, "post_urn": args.post_urn}, indent=2))


def cmd_delete_post(args):
    """Delete a post."""
    post_id = args.post_urn.replace(":", "%3A")

    result = api_request("DELETE", f"/rest/posts/{post_id}", account=args.account)

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "deleted": args.post_urn}, indent=2))


def cmd_comments(args):
    """List comments on a post."""
    # socialActions endpoint uses the post URN
    post_id = args.post_urn.replace(":", "%3A")

    result = api_request(
        "GET",
        f"/rest/socialActions/{post_id}/comments",
        account=args.account,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    comments = []
    for comment in result.get("elements", []):
        comments.append(
            {
                "urn": comment.get("$URN") or comment.get("id"),
                "actor": comment.get("actor"),
                "message": comment.get("message", {}).get("text"),
                "created": comment.get("created", {}).get("time"),
            }
        )

    print(json.dumps({"comments": comments, "total": len(comments)}, indent=2))


def cmd_comment(args):
    """Add a comment to a post."""
    member_urn = get_member_urn(args.account)
    post_id = args.post_urn.replace(":", "%3A")

    comment_data = {
        "actor": member_urn,
        "message": {
            "text": args.text,
        },
    }

    result = api_request(
        "POST",
        f"/rest/socialActions/{post_id}/comments",
        account=args.account,
        data=comment_data,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "comment": result}, indent=2))


def cmd_reply(args):
    """Reply to a comment."""
    member_urn = get_member_urn(args.account)

    # Extract the post URN from the comment URN to find the right endpoint
    # Comment URN format: urn:li:comment:(urn:li:activity:...,commentId)
    # We need to reply on the parent entity

    comment_id = args.comment_urn.replace(":", "%3A")

    reply_data = {
        "actor": member_urn,
        "message": {
            "text": args.text,
        },
        "parentComment": args.comment_urn,
    }

    # For replies, we use the comment's parent post
    result = api_request(
        "POST",
        f"/rest/socialActions/{comment_id}/comments",
        account=args.account,
        data=reply_data,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "reply": result}, indent=2))


def cmd_delete_comment(args):
    """Delete a comment."""
    comment_id = args.comment_urn.replace(":", "%3A")

    result = api_request(
        "DELETE",
        f"/rest/socialActions/{comment_id}",
        account=args.account,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "deleted": args.comment_urn}, indent=2))


def cmd_react(args):
    """Add a reaction to a post."""
    member_urn = get_member_urn(args.account)

    reaction_type = args.type.upper()
    valid_types = ["LIKE", "PRAISE", "EMPATHY", "INTEREST", "APPRECIATION"]
    if reaction_type not in valid_types:
        print(json.dumps({"error": f"Invalid reaction type. Valid types: {valid_types}"}))
        sys.exit(1)

    reaction_data = {
        "root": args.post_urn,
        "reactionType": reaction_type,
        "actor": member_urn,
    }

    result = api_request(
        "POST",
        "/rest/reactions",
        account=args.account,
        data=reaction_data,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "reaction": reaction_type, "post": args.post_urn}, indent=2))


def cmd_unreact(args):
    """Remove reaction from a post."""
    member_urn = get_member_urn(args.account)

    # The reaction ID is a composite of actor and entity
    # Format: urn:li:reaction:(member_urn,entity_urn)
    actor_encoded = member_urn.replace(":", "%3A")
    entity_encoded = args.post_urn.replace(":", "%3A")

    result = api_request(
        "DELETE",
        f"/rest/reactions/({actor_encoded},{entity_encoded})",
        account=args.account,
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps({"success": True, "unreacted": args.post_urn}, indent=2))


def cmd_reactions(args):
    """List reactions on a post."""
    post_id = args.post_urn.replace(":", "%3A")

    result = api_request(
        "GET",
        f"/rest/reactions",
        account=args.account,
        params={"q": "entity", "entity": args.post_urn},
    )

    if result.get("error"):
        print(json.dumps(result, indent=2))
        sys.exit(1)

    reactions = []
    for reaction in result.get("elements", []):
        reactions.append(
            {
                "actor": reaction.get("actor"),
                "type": reaction.get("reactionType"),
                "created": reaction.get("created"),
            }
        )

    print(json.dumps({"reactions": reactions, "total": len(reactions)}, indent=2))


def add_account_arg(parser):
    """Add --account argument to a parser."""
    parser.add_argument(
        "--account",
        "-a",
        help="Account to use (email or label, default: first authenticated account)",
    )


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Skill - Post, comment, and react on LinkedIn"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Account management
    accounts_parser = subparsers.add_parser("accounts", help="List authenticated accounts")
    accounts_parser.set_defaults(func=cmd_accounts)

    login_parser = subparsers.add_parser("login", help="Authenticate a new account")
    login_parser.add_argument("--account", "-a", help="Label for this account")
    login_parser.set_defaults(func=cmd_login)

    logout_parser = subparsers.add_parser("logout", help="Remove account credentials")
    logout_parser.add_argument("--account", "-a", help="Account to logout (email or label)")
    logout_parser.set_defaults(func=cmd_logout)

    # Profile
    me_parser = subparsers.add_parser("me", help="Get authenticated user's profile")
    add_account_arg(me_parser)
    me_parser.set_defaults(func=cmd_me)

    orgs_parser = subparsers.add_parser("organizations", help="List organizations where user is admin")
    add_account_arg(orgs_parser)
    orgs_parser.set_defaults(func=cmd_organizations)

    # Posts
    post_parser = subparsers.add_parser("post", help="Create a post")
    post_parser.add_argument("--text", "-t", required=True, help="Post content")
    post_parser.add_argument("--author", help="Author URN (org URN to post as organization)")
    post_parser.add_argument(
        "--visibility",
        choices=["PUBLIC", "CONNECTIONS"],
        default="PUBLIC",
        help="Post visibility (default: PUBLIC)",
    )
    add_account_arg(post_parser)
    post_parser.set_defaults(func=cmd_post)

    list_posts_parser = subparsers.add_parser("list-posts", help="List posts by author")
    list_posts_parser.add_argument("--author", help="Author URN (default: authenticated user)")
    list_posts_parser.add_argument("--count", type=int, default=10, help="Number of posts (default: 10)")
    add_account_arg(list_posts_parser)
    list_posts_parser.set_defaults(func=cmd_list_posts)

    get_post_parser = subparsers.add_parser("get-post", help="Get a single post")
    get_post_parser.add_argument("post_urn", help="Post URN")
    add_account_arg(get_post_parser)
    get_post_parser.set_defaults(func=cmd_get_post)

    edit_post_parser = subparsers.add_parser("edit-post", help="Edit a post's text")
    edit_post_parser.add_argument("post_urn", help="Post URN")
    edit_post_parser.add_argument("--text", "-t", required=True, help="New post content")
    add_account_arg(edit_post_parser)
    edit_post_parser.set_defaults(func=cmd_edit_post)

    delete_post_parser = subparsers.add_parser("delete-post", help="Delete a post")
    delete_post_parser.add_argument("post_urn", help="Post URN")
    add_account_arg(delete_post_parser)
    delete_post_parser.set_defaults(func=cmd_delete_post)

    # Comments
    comments_parser = subparsers.add_parser("comments", help="List comments on a post")
    comments_parser.add_argument("post_urn", help="Post URN")
    add_account_arg(comments_parser)
    comments_parser.set_defaults(func=cmd_comments)

    comment_parser = subparsers.add_parser("comment", help="Add a comment to a post")
    comment_parser.add_argument("post_urn", help="Post URN")
    comment_parser.add_argument("--text", "-t", required=True, help="Comment text")
    add_account_arg(comment_parser)
    comment_parser.set_defaults(func=cmd_comment)

    reply_parser = subparsers.add_parser("reply", help="Reply to a comment")
    reply_parser.add_argument("comment_urn", help="Comment URN")
    reply_parser.add_argument("--text", "-t", required=True, help="Reply text")
    add_account_arg(reply_parser)
    reply_parser.set_defaults(func=cmd_reply)

    delete_comment_parser = subparsers.add_parser("delete-comment", help="Delete a comment")
    delete_comment_parser.add_argument("comment_urn", help="Comment URN")
    add_account_arg(delete_comment_parser)
    delete_comment_parser.set_defaults(func=cmd_delete_comment)

    # Reactions
    react_parser = subparsers.add_parser("react", help="Add reaction to a post")
    react_parser.add_argument("post_urn", help="Post URN")
    react_parser.add_argument(
        "--type",
        "-t",
        required=True,
        choices=["LIKE", "PRAISE", "EMPATHY", "INTEREST", "APPRECIATION"],
        help="Reaction type",
    )
    add_account_arg(react_parser)
    react_parser.set_defaults(func=cmd_react)

    unreact_parser = subparsers.add_parser("unreact", help="Remove reaction from a post")
    unreact_parser.add_argument("post_urn", help="Post URN")
    add_account_arg(unreact_parser)
    unreact_parser.set_defaults(func=cmd_unreact)

    reactions_parser = subparsers.add_parser("reactions", help="List reactions on a post")
    reactions_parser.add_argument("post_urn", help="Post URN")
    add_account_arg(reactions_parser)
    reactions_parser.set_defaults(func=cmd_reactions)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
