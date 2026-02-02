#!/usr/bin/env python3
"""
Reddit Skill - Post, comment, and browse Reddit.

Usage:
    python reddit_skill.py me [--account NAME]
    python reddit_skill.py frontpage [--limit N] [--sort hot|new|top]
    python reddit_skill.py subreddit NAME [--limit N] [--sort hot|new|top|rising]
    python reddit_skill.py post SUBREDDIT --title "..." [--text "..."|--url "..."|--image PATH]
    python reddit_skill.py comment THING_ID --text "..."
    python reddit_skill.py reply COMMENT_ID --text "..."
    python reddit_skill.py vote THING_ID --dir up|down|none
    python reddit_skill.py save THING_ID
    python reddit_skill.py unsave THING_ID
    python reddit_skill.py submissions [USERNAME] [--limit N] [--sort new|hot|top]
    python reddit_skill.py comments [USERNAME] [--limit N]
    python reddit_skill.py search "query" [--subreddit NAME] [--limit N]
    python reddit_skill.py inbox [--limit N]
    python reddit_skill.py subscriptions [--limit N]
    python reddit_skill.py accounts
    python reddit_skill.py login [--account NAME]
    python reddit_skill.py logout [--account NAME]
"""

import argparse
import base64
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
    print("Error: requests not installed. Run: pip install requests")
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
TOKENS_DIR = SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"

REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/authorize"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"

USER_AGENT = "claude-code-reddit-skill/1.0"

SCOPES = [
    "identity", "read", "submit", "vote", "save",
    "subscribe", "mysubreddits", "privatemessages", "history"
]

TOKENS_DIR.mkdir(parents=True, exist_ok=True)


def get_client_config() -> dict:
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)

    print("\n" + "=" * 60)
    print("FIRST-TIME SETUP REQUIRED")
    print("=" * 60)
    print("\nTo use Reddit Skill, create a Reddit app:\n")
    print("1. Go to: https://www.reddit.com/prefs/apps")
    print("2. Scroll down and click 'create another app...'")
    print("3. Fill in:")
    print("   - Name: Claude Reddit Skill")
    print("   - Type: 'script' (for personal use) or 'web app'")
    print("   - Redirect URI: http://localhost:9996")
    print("4. Note the client ID (under app name) and secret")
    print("5. Create credentials.json:")
    print(f"   {CREDENTIALS_FILE}")
    print('   {"client_id": "YOUR_ID", "client_secret": "YOUR_SECRET"}')
    print("\nThen run this command again.")
    print("=" * 60 + "\n")

    try:
        if input("Open Reddit apps page? [Y/n]: ").strip().lower() != "n":
            webbrowser.open("https://www.reddit.com/prefs/apps")
    except:
        pass
    sys.exit(1)


class OAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            self.server.auth_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Success!</h1><p>Close this window.</p></body></html>")
        elif "error" in query:
            self.server.auth_error = query.get("error", ["Unknown"])[0]
            self.send_response(400)
            self.end_headers()
        else:
            self.send_response(400)
            self.end_headers()


def do_oauth_flow(config: dict) -> dict:
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    port = 9996
    redirect_uri = f"http://localhost:{port}"
    state = secrets.token_urlsafe(32)

    auth_params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri,
        "duration": "permanent",
        "scope": " ".join(SCOPES),
    }

    auth_url = f"{REDDIT_AUTH_URL}?{urlencode(auth_params)}"

    server = HTTPServer(("localhost", port), OAuthHandler)
    server.auth_code = None
    server.auth_error = None
    server.timeout = 120

    print(f"\nOpening browser for Reddit authentication...")
    print(f"If browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    while server.auth_code is None and server.auth_error is None:
        server.handle_request()

    if server.auth_error:
        print(f"Auth error: {server.auth_error}")
        sys.exit(1)

    # Exchange code for token
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        REDDIT_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": server.auth_code,
            "redirect_uri": redirect_uri,
        },
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": USER_AGENT,
        },
    )

    if response.status_code != 200:
        print(f"Token error: {response.text}")
        sys.exit(1)

    tokens = response.json()
    if "expires_in" in tokens:
        tokens["expiry"] = (datetime.utcnow() + timedelta(seconds=tokens["expires_in"])).isoformat() + "Z"

    # Get username
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "User-Agent": USER_AGENT}
    me = requests.get(f"{REDDIT_API_BASE}/api/v1/me", headers=headers)
    if me.status_code == 200:
        tokens["username"] = me.json().get("name")

    return tokens


def refresh_tokens(config: dict, refresh_token: str) -> Optional[dict]:
    auth = base64.b64encode(f"{config['client_id']}:{config['client_secret']}".encode()).decode()
    response = requests.post(
        REDDIT_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers={"Authorization": f"Basic {auth}", "User-Agent": USER_AGENT},
    )
    if response.status_code != 200:
        return None
    tokens = response.json()
    tokens["refresh_token"] = refresh_token  # Reddit doesn't return new refresh token
    if "expires_in" in tokens:
        tokens["expiry"] = (datetime.utcnow() + timedelta(seconds=tokens["expires_in"])).isoformat() + "Z"
    return tokens


def get_token_path(account: Optional[str] = None) -> Path:
    if account:
        return TOKENS_DIR / f"token_{re.sub(r'[^w.-]', '_', account.lower())}.json"
    tokens = list(TOKENS_DIR.glob("token_*.json"))
    return tokens[0] if tokens else TOKENS_DIR / "token_default.json"


def get_credentials(account: Optional[str] = None) -> dict:
    config = get_client_config()
    token_path = get_token_path(account)

    if token_path.exists():
        with open(token_path) as f:
            tokens = json.load(f)

        if "expiry" in tokens:
            expiry = datetime.fromisoformat(tokens["expiry"].replace("Z", "+00:00"))
            if datetime.now(expiry.tzinfo) >= expiry and "refresh_token" in tokens:
                new_tokens = refresh_tokens(config, tokens["refresh_token"])
                if new_tokens:
                    new_tokens["username"] = tokens.get("username")
                    tokens = new_tokens
                    with open(token_path, "w") as f:
                        json.dump(tokens, f, indent=2)

        return tokens

    print("Not authenticated. Run 'login' first.")
    sys.exit(1)


def api_request(method: str, endpoint: str, account: Optional[str] = None, data: dict = None, params: dict = None) -> dict:
    tokens = get_credentials(account)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "User-Agent": USER_AGENT}
    url = f"{REDDIT_API_BASE}{endpoint}"

    if method == "GET":
        r = requests.get(url, headers=headers, params=params)
    elif method == "POST":
        r = requests.post(url, headers=headers, data=data)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if r.status_code >= 400:
        return {"error": True, "status": r.status_code, "details": r.text}

    try:
        return r.json()
    except:
        return {"success": True}


def format_post(p: dict) -> dict:
    d = p.get("data", p)
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "title": d.get("title"),
        "author": d.get("author"),
        "subreddit": d.get("subreddit"),
        "score": d.get("score"),
        "num_comments": d.get("num_comments"),
        "url": d.get("url"),
        "selftext": d.get("selftext", "")[:500],
        "created_utc": d.get("created_utc"),
        "permalink": f"https://reddit.com{d.get('permalink', '')}",
    }


def format_comment(c: dict) -> dict:
    d = c.get("data", c)
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "author": d.get("author"),
        "body": d.get("body", "")[:500],
        "score": d.get("score"),
        "created_utc": d.get("created_utc"),
        "link_id": d.get("link_id"),
        "parent_id": d.get("parent_id"),
    }


# Commands

def cmd_accounts(args):
    accounts = []
    for f in TOKENS_DIR.glob("token_*.json"):
        with open(f) as tf:
            data = json.load(tf)
            accounts.append({"name": f.stem.replace("token_", ""), "username": data.get("username")})
    print(json.dumps({"accounts": accounts}, indent=2))


def cmd_login(args):
    config = get_client_config()
    tokens = do_oauth_flow(config)
    account = args.account or tokens.get("username", "default")
    with open(get_token_path(account), "w") as f:
        json.dump(tokens, f, indent=2)
    print(json.dumps({"success": True, "username": tokens.get("username"), "account": account}, indent=2))


def cmd_logout(args):
    p = get_token_path(args.account)
    if p.exists():
        p.unlink()
        print(json.dumps({"success": True}))
    else:
        print(json.dumps({"error": "Account not found"}))


def cmd_me(args):
    result = api_request("GET", "/api/v1/me", args.account)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({
            "username": result.get("name"),
            "karma": result.get("total_karma"),
            "comment_karma": result.get("comment_karma"),
            "link_karma": result.get("link_karma"),
            "created_utc": result.get("created_utc"),
        }, indent=2))


def cmd_frontpage(args):
    params = {"limit": args.limit}
    result = api_request("GET", f"/{args.sort}", args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        posts = [format_post(p) for p in result.get("data", {}).get("children", [])]
        print(json.dumps({"posts": posts, "count": len(posts)}, indent=2))


def cmd_subreddit(args):
    params = {"limit": args.limit}
    result = api_request("GET", f"/r/{args.name}/{args.sort}", args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        posts = [format_post(p) for p in result.get("data", {}).get("children", [])]
        print(json.dumps({"subreddit": args.name, "posts": posts, "count": len(posts)}, indent=2))


def cmd_post(args):
    data = {
        "sr": args.subreddit,
        "title": args.title,
        "kind": "self",
    }
    if args.text:
        data["kind"] = "self"
        data["text"] = args.text
    elif args.url:
        data["kind"] = "link"
        data["url"] = args.url

    result = api_request("POST", "/api/submit", args.account, data=data)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"success": True, "url": result.get("json", {}).get("data", {}).get("url")}, indent=2))


def cmd_comment(args):
    data = {"thing_id": args.thing_id, "text": args.text}
    result = api_request("POST", "/api/comment", args.account, data=data)
    print(json.dumps(result if result.get("error") else {"success": True}, indent=2))


def cmd_reply(args):
    data = {"thing_id": f"t1_{args.comment_id}", "text": args.text}
    result = api_request("POST", "/api/comment", args.account, data=data)
    print(json.dumps(result if result.get("error") else {"success": True}, indent=2))


def cmd_vote(args):
    dir_map = {"up": 1, "down": -1, "none": 0}
    data = {"id": args.thing_id, "dir": dir_map.get(args.dir, 0)}
    result = api_request("POST", "/api/vote", args.account, data=data)
    print(json.dumps({"success": True, "vote": args.dir} if not result.get("error") else result, indent=2))


def cmd_save(args):
    result = api_request("POST", "/api/save", args.account, data={"id": args.thing_id})
    print(json.dumps({"success": True} if not result.get("error") else result, indent=2))


def cmd_unsave(args):
    result = api_request("POST", "/api/unsave", args.account, data={"id": args.thing_id})
    print(json.dumps({"success": True} if not result.get("error") else result, indent=2))


def cmd_submissions(args):
    user = args.username or get_credentials(args.account).get("username", "me")
    params = {"limit": args.limit, "sort": args.sort}
    result = api_request("GET", f"/user/{user}/submitted", args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        posts = [format_post(p) for p in result.get("data", {}).get("children", [])]
        print(json.dumps({"user": user, "posts": posts}, indent=2))


def cmd_comments_list(args):
    user = args.username or get_credentials(args.account).get("username", "me")
    params = {"limit": args.limit}
    result = api_request("GET", f"/user/{user}/comments", args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        comments = [format_comment(c) for c in result.get("data", {}).get("children", [])]
        print(json.dumps({"user": user, "comments": comments}, indent=2))


def cmd_search(args):
    params = {"q": args.query, "limit": args.limit, "type": "link"}
    endpoint = f"/r/{args.subreddit}/search" if args.subreddit else "/search"
    if args.subreddit:
        params["restrict_sr"] = "on"
    result = api_request("GET", endpoint, args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        posts = [format_post(p) for p in result.get("data", {}).get("children", [])]
        print(json.dumps({"query": args.query, "posts": posts}, indent=2))


def cmd_inbox(args):
    params = {"limit": args.limit}
    result = api_request("GET", "/message/inbox", args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        messages = [{
            "id": m["data"]["id"],
            "author": m["data"].get("author"),
            "subject": m["data"].get("subject"),
            "body": m["data"].get("body", "")[:500],
            "created_utc": m["data"].get("created_utc"),
            "new": m["data"].get("new"),
        } for m in result.get("data", {}).get("children", [])]
        print(json.dumps({"messages": messages}, indent=2))


def cmd_subscriptions(args):
    params = {"limit": args.limit}
    result = api_request("GET", "/subreddits/mine/subscriber", args.account, params=params)
    if result.get("error"):
        print(json.dumps(result, indent=2))
    else:
        subs = [{
            "name": s["data"]["display_name"],
            "title": s["data"].get("title"),
            "subscribers": s["data"].get("subscribers"),
            "url": s["data"].get("url"),
        } for s in result.get("data", {}).get("children", [])]
        print(json.dumps({"subscriptions": subs}, indent=2))


def add_account_arg(p):
    p.add_argument("--account", "-a", help="Account to use")


def main():
    parser = argparse.ArgumentParser(description="Reddit Skill")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("accounts").set_defaults(func=cmd_accounts)

    login = subs.add_parser("login")
    login.add_argument("--account", "-a")
    login.set_defaults(func=cmd_login)

    logout = subs.add_parser("logout")
    logout.add_argument("--account", "-a")
    logout.set_defaults(func=cmd_logout)

    me = subs.add_parser("me")
    add_account_arg(me)
    me.set_defaults(func=cmd_me)

    fp = subs.add_parser("frontpage")
    fp.add_argument("--limit", "-l", type=int, default=25)
    fp.add_argument("--sort", "-s", choices=["hot", "new", "top"], default="hot")
    add_account_arg(fp)
    fp.set_defaults(func=cmd_frontpage)

    sr = subs.add_parser("subreddit")
    sr.add_argument("name")
    sr.add_argument("--limit", "-l", type=int, default=25)
    sr.add_argument("--sort", "-s", choices=["hot", "new", "top", "rising"], default="hot")
    add_account_arg(sr)
    sr.set_defaults(func=cmd_subreddit)

    post = subs.add_parser("post")
    post.add_argument("subreddit")
    post.add_argument("--title", "-t", required=True)
    post.add_argument("--text")
    post.add_argument("--url")
    add_account_arg(post)
    post.set_defaults(func=cmd_post)

    comment = subs.add_parser("comment")
    comment.add_argument("thing_id")
    comment.add_argument("--text", "-t", required=True)
    add_account_arg(comment)
    comment.set_defaults(func=cmd_comment)

    reply = subs.add_parser("reply")
    reply.add_argument("comment_id")
    reply.add_argument("--text", "-t", required=True)
    add_account_arg(reply)
    reply.set_defaults(func=cmd_reply)

    vote = subs.add_parser("vote")
    vote.add_argument("thing_id")
    vote.add_argument("--dir", "-d", choices=["up", "down", "none"], required=True)
    add_account_arg(vote)
    vote.set_defaults(func=cmd_vote)

    save = subs.add_parser("save")
    save.add_argument("thing_id")
    add_account_arg(save)
    save.set_defaults(func=cmd_save)

    unsave = subs.add_parser("unsave")
    unsave.add_argument("thing_id")
    add_account_arg(unsave)
    unsave.set_defaults(func=cmd_unsave)

    submissions = subs.add_parser("submissions")
    submissions.add_argument("username", nargs="?")
    submissions.add_argument("--limit", "-l", type=int, default=25)
    submissions.add_argument("--sort", "-s", choices=["new", "hot", "top"], default="new")
    add_account_arg(submissions)
    submissions.set_defaults(func=cmd_submissions)

    comments_p = subs.add_parser("comments")
    comments_p.add_argument("username", nargs="?")
    comments_p.add_argument("--limit", "-l", type=int, default=25)
    add_account_arg(comments_p)
    comments_p.set_defaults(func=cmd_comments_list)

    search = subs.add_parser("search")
    search.add_argument("query")
    search.add_argument("--subreddit", "-r")
    search.add_argument("--limit", "-l", type=int, default=25)
    add_account_arg(search)
    search.set_defaults(func=cmd_search)

    inbox = subs.add_parser("inbox")
    inbox.add_argument("--limit", "-l", type=int, default=25)
    add_account_arg(inbox)
    inbox.set_defaults(func=cmd_inbox)

    subscriptions = subs.add_parser("subscriptions")
    subscriptions.add_argument("--limit", "-l", type=int, default=100)
    add_account_arg(subscriptions)
    subscriptions.set_defaults(func=cmd_subscriptions)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
