#!/usr/bin/env python3
"""
Google Calendar Skill - Read, create, and manage calendar events.

Supports multiple accounts with seamless OAuth browser flow.

Usage:
    python gcal_skill.py today [--account EMAIL]
    python gcal_skill.py week [--account EMAIL]
    python gcal_skill.py agenda [--days N] [--account EMAIL]
    python gcal_skill.py event EVENT_ID [--account EMAIL]
    python gcal_skill.py create --title "..." --start "..." [--end "..."] [--account EMAIL]
    python gcal_skill.py calendars [--account EMAIL]
    python gcal_skill.py search "query" [--account EMAIL]
    python gcal_skill.py accounts
    python gcal_skill.py logout [--account EMAIL]
"""

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlencode, parse_qs, urlparse
import threading
import secrets
from zoneinfo import ZoneInfo

# Check for required libraries
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import requests
except ImportError:
    print("Error: Required libraries not installed.")
    print("Install with: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests")
    sys.exit(1)

# Paths - reuse gmail-skill credentials if available
SKILL_DIR = Path(__file__).parent
GMAIL_SKILL_DIR = SKILL_DIR.parent / "gmail-skill"
TOKENS_DIR = SKILL_DIR / "tokens"

# Use gmail-skill credentials if available, otherwise look locally
if (GMAIL_SKILL_DIR / "credentials.json").exists():
    CREDENTIALS_FILE = GMAIL_SKILL_DIR / "credentials.json"
else:
    CREDENTIALS_FILE = SKILL_DIR / "credentials.json"

ACCOUNTS_META_FILE = SKILL_DIR / "accounts.json"

# Scopes for Calendar access
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",  # For creating/modifying events
    "https://www.googleapis.com/auth/userinfo.email",
]

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Local timezone
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def get_client_config() -> dict:
    """Load OAuth client configuration."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)

    print("\n" + "="*60)
    print("FIRST-TIME SETUP REQUIRED")
    print("="*60)
    print("\nTo use Google Calendar Skill, you need OAuth credentials.")
    print("\nIf you already have gmail-skill set up:")
    print("  1. Enable Calendar API in Google Cloud Console")
    print("  2. The skill will reuse gmail-skill credentials")
    print("\nOtherwise, create a new OAuth client:")
    print("1. Go to: https://console.cloud.google.com/apis/credentials")
    print("2. Create/select a project")
    print("3. Enable Google Calendar API (APIs & Services → Library)")
    print("4. Create OAuth client ID (Desktop app type)")
    print("5. Download JSON and save as:")
    print(f"   {SKILL_DIR / 'credentials.json'}")
    print("\nThen run this command again.")
    print("="*60 + "\n")

    try:
        response = input("Open Google Cloud Console now? [Y/n]: ").strip().lower()
        if response != 'n':
            webbrowser.open("https://console.cloud.google.com/apis/credentials")
    except:
        pass

    sys.exit(1)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to receive OAuth callback."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        """Handle the OAuth callback."""
        query = parse_qs(urlparse(self.path).query)

        if 'code' in query:
            self.server.auth_code = query['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family: system-ui; text-align: center; padding: 50px;">
                <h1>Authentication Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                </body></html>
            """)
        else:
            self.server.auth_code = None
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error = query.get('error', ['Unknown error'])[0]
            self.wfile.write(f"<html><body><h1>Error: {error}</h1></body></html>".encode())


def oauth_flow(target_email: Optional[str] = None) -> Credentials:
    """Run OAuth flow with browser."""
    config = get_client_config()
    client_config = config.get("installed", config.get("web", {}))
    client_id = client_config["client_id"]
    client_secret = client_config["client_secret"]

    # Start local server
    server = HTTPServer(('localhost', 0), OAuthCallbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://localhost:{port}"

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Build auth URL
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if target_email:
        params["login_hint"] = target_email

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    print(f"\nOpening browser for authentication...")
    if target_email:
        print(f"Please sign in with: {target_email}")
    webbrowser.open(auth_url)

    # Wait for callback
    server.auth_code = None
    server.handle_request()

    if not server.auth_code:
        print("Authentication failed or was cancelled.")
        sys.exit(1)

    # Exchange code for tokens
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": server.auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    response = requests.post(GOOGLE_TOKEN_URL, data=token_data)
    if response.status_code != 200:
        print(f"Token exchange failed: {response.text}")
        sys.exit(1)

    tokens = response.json()

    # Get user email
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_response = requests.get(GOOGLE_USERINFO_URL, headers=headers)
    user_email = user_response.json().get("email", "unknown")

    # Save token
    TOKENS_DIR.mkdir(exist_ok=True)
    token_file = TOKENS_DIR / f"{user_email}.json"

    token_info = {
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_uri": GOOGLE_TOKEN_URL,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": SCOPES,
    }
    with open(token_file, "w") as f:
        json.dump(token_info, f, indent=2)

    # Update accounts metadata
    accounts = {}
    if ACCOUNTS_META_FILE.exists():
        with open(ACCOUNTS_META_FILE) as f:
            accounts = json.load(f)
    accounts[user_email] = {"added": datetime.now().isoformat()}
    with open(ACCOUNTS_META_FILE, "w") as f:
        json.dump(accounts, f, indent=2)

    print(f"\nAuthenticated as: {user_email}")

    return Credentials(**token_info)


def get_credentials(account: Optional[str] = None) -> tuple[Credentials, str]:
    """Get credentials for specified account or default."""
    TOKENS_DIR.mkdir(exist_ok=True)

    # Find token file
    token_files = list(TOKENS_DIR.glob("*.json"))

    if account:
        token_file = TOKENS_DIR / f"{account}.json"
        if not token_file.exists():
            print(f"Account {account} not found. Starting authentication...")
            creds = oauth_flow(account)
            return creds, account
    elif token_files:
        token_file = token_files[0]
        account = token_file.stem
    else:
        print("No accounts configured. Starting authentication...")
        creds = oauth_flow()
        token_files = list(TOKENS_DIR.glob("*.json"))
        token_file = token_files[0]
        account = token_file.stem

    # Load credentials
    with open(token_file) as f:
        token_info = json.load(f)

    creds = Credentials(
        token=token_info.get("token"),
        refresh_token=token_info.get("refresh_token"),
        token_uri=token_info.get("token_uri"),
        client_id=token_info.get("client_id"),
        client_secret=token_info.get("client_secret"),
        scopes=token_info.get("scopes"),
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_info["token"] = creds.token
            with open(token_file, "w") as f:
                json.dump(token_info, f, indent=2)
        except Exception as e:
            print(f"Token refresh failed: {e}")
            print("Re-authenticating...")
            creds = oauth_flow(account)

    return creds, account


def get_calendar_service(account: Optional[str] = None):
    """Get Calendar API service."""
    creds, email = get_credentials(account)
    return build("calendar", "v3", credentials=creds), email


def parse_datetime(dt_str: str, default_date: Optional[datetime] = None) -> datetime:
    """Parse datetime string in various formats."""
    dt_str = dt_str.strip()
    now = default_date or datetime.now(LOCAL_TZ)

    # Try various formats
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I:%M%p",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y",
        "%H:%M",
        "%I:%M %p",
        "%I:%M%p",
        "%I %p",
        "%I%p",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(dt_str, fmt)
            # If only time, use today's date
            if fmt in ["%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"]:
                parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=LOCAL_TZ)
            return parsed
        except ValueError:
            continue

    raise ValueError(f"Cannot parse datetime: {dt_str}")


def format_event(event: dict) -> dict:
    """Format event for output."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Handle all-day events
    if "date" in start:
        start_str = start["date"]
        end_str = end.get("date", "")
        all_day = True
    else:
        start_dt = datetime.fromisoformat(start.get("dateTime", "").replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.get("dateTime", "").replace("Z", "+00:00"))
        start_str = start_dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
        end_str = end_dt.astimezone(LOCAL_TZ).strftime("%H:%M")
        all_day = False

    attendees = event.get("attendees", [])
    attendee_list = [
        {"email": a.get("email"), "status": a.get("responseStatus", "needsAction")}
        for a in attendees
    ]

    return {
        "id": event.get("id"),
        "title": event.get("summary", "(No title)"),
        "start": start_str,
        "end": end_str,
        "all_day": all_day,
        "location": event.get("location"),
        "description": event.get("description"),
        "status": event.get("status"),
        "html_link": event.get("htmlLink"),
        "hangout_link": event.get("hangoutLink"),
        "attendees": attendee_list if attendee_list else None,
        "organizer": event.get("organizer", {}).get("email"),
        "calendar": event.get("calendarId"),
    }


def output(data):
    """Print JSON output."""
    print(json.dumps(data, indent=2, default=str))


# ============ Commands ============

def cmd_today(args):
    """Show today's events."""
    service, account = get_calendar_service(args.account)

    now = datetime.now(LOCAL_TZ)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])

    output({
        "account": account,
        "date": now.strftime("%Y-%m-%d"),
        "day": now.strftime("%A"),
        "events": [format_event(e) for e in events],
        "count": len(events),
    })


def cmd_week(args):
    """Show this week's events."""
    service, account = get_calendar_service(args.account)

    now = datetime.now(LOCAL_TZ)
    # Start from today
    start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=7)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_week.isoformat(),
        timeMax=end_of_week.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])

    # Group by date
    by_date = {}
    for event in events:
        start = event.get("start", {})
        if "date" in start:
            date_key = start["date"]
        else:
            dt = datetime.fromisoformat(start.get("dateTime", "").replace("Z", "+00:00"))
            date_key = dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")

        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(format_event(event))

    output({
        "account": account,
        "start": start_of_week.strftime("%Y-%m-%d"),
        "end": end_of_week.strftime("%Y-%m-%d"),
        "events_by_date": by_date,
        "total_events": len(events),
    })


def cmd_agenda(args):
    """Show agenda for N days."""
    service, account = get_calendar_service(args.account)
    days = args.days or 7

    now = datetime.now(LOCAL_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=100,
    ).execute()

    events = events_result.get("items", [])

    output({
        "account": account,
        "days": days,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "events": [format_event(e) for e in events],
        "count": len(events),
    })


def cmd_event(args):
    """Get details of a specific event."""
    service, account = get_calendar_service(args.account)

    try:
        event = service.events().get(
            calendarId="primary",
            eventId=args.event_id,
        ).execute()

        output({
            "account": account,
            "event": format_event(event),
        })
    except HttpError as e:
        output({"error": f"Event not found: {e}"})


def cmd_create(args):
    """Create a new event."""
    service, account = get_calendar_service(args.account)

    start_dt = parse_datetime(args.start)

    if args.end:
        end_dt = parse_datetime(args.end, start_dt)
    else:
        # Default 1 hour duration
        end_dt = start_dt + timedelta(hours=1)

    event_body = {
        "summary": args.title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": str(LOCAL_TZ)},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": str(LOCAL_TZ)},
    }

    if args.location:
        event_body["location"] = args.location
    if args.description:
        event_body["description"] = args.description
    if args.attendees:
        event_body["attendees"] = [{"email": e.strip()} for e in args.attendees.split(",")]

    event = service.events().insert(
        calendarId="primary",
        body=event_body,
        sendUpdates="all" if args.attendees else "none",
    ).execute()

    output({
        "success": True,
        "account": account,
        "event": format_event(event),
        "html_link": event.get("htmlLink"),
    })


def cmd_delete(args):
    """Delete an event."""
    service, account = get_calendar_service(args.account)

    try:
        service.events().delete(
            calendarId="primary",
            eventId=args.event_id,
            sendUpdates="all",
        ).execute()

        output({
            "success": True,
            "account": account,
            "deleted": args.event_id,
        })
    except HttpError as e:
        output({"error": f"Failed to delete: {e}"})


def cmd_calendars(args):
    """List available calendars."""
    service, account = get_calendar_service(args.account)

    calendars_result = service.calendarList().list().execute()
    calendars = calendars_result.get("items", [])

    output({
        "account": account,
        "calendars": [
            {
                "id": c.get("id"),
                "name": c.get("summary"),
                "primary": c.get("primary", False),
                "access_role": c.get("accessRole"),
                "background_color": c.get("backgroundColor"),
            }
            for c in calendars
        ],
        "count": len(calendars),
    })


def cmd_search(args):
    """Search events."""
    service, account = get_calendar_service(args.account)

    # Search in the next year by default
    now = datetime.now(LOCAL_TZ)
    end = now + timedelta(days=365)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        q=args.query,
        singleEvents=True,
        orderBy="startTime",
        maxResults=args.max_results or 20,
    ).execute()

    events = events_result.get("items", [])

    output({
        "account": account,
        "query": args.query,
        "events": [format_event(e) for e in events],
        "count": len(events),
    })


def cmd_accounts(args):
    """List authenticated accounts."""
    TOKENS_DIR.mkdir(exist_ok=True)
    accounts = [f.stem for f in TOKENS_DIR.glob("*.json")]

    output({
        "accounts": accounts,
        "count": len(accounts),
        "credentials_file": str(CREDENTIALS_FILE),
    })


def cmd_logout(args):
    """Remove an account."""
    if not args.account:
        output({"error": "Please specify --account EMAIL"})
        return

    token_file = TOKENS_DIR / f"{args.account}.json"
    if token_file.exists():
        token_file.unlink()
        output({"success": True, "removed": args.account})
    else:
        output({"error": f"Account not found: {args.account}"})


def main():
    parser = argparse.ArgumentParser(description="Google Calendar Skill")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # today
    p = subparsers.add_parser("today", help="Show today's events")
    p.add_argument("--account", "-a", help="Account email")

    # week
    p = subparsers.add_parser("week", help="Show this week's events")
    p.add_argument("--account", "-a", help="Account email")

    # agenda
    p = subparsers.add_parser("agenda", help="Show agenda for N days")
    p.add_argument("--days", "-d", type=int, default=7, help="Number of days")
    p.add_argument("--account", "-a", help="Account email")

    # event
    p = subparsers.add_parser("event", help="Get event details")
    p.add_argument("event_id", help="Event ID")
    p.add_argument("--account", "-a", help="Account email")

    # create
    p = subparsers.add_parser("create", help="Create event")
    p.add_argument("--title", "-t", required=True, help="Event title")
    p.add_argument("--start", "-s", required=True, help="Start time")
    p.add_argument("--end", "-e", help="End time (default: 1 hour after start)")
    p.add_argument("--location", "-l", help="Location")
    p.add_argument("--description", "-d", help="Description")
    p.add_argument("--attendees", help="Comma-separated attendee emails")
    p.add_argument("--account", "-a", help="Account email")

    # delete
    p = subparsers.add_parser("delete", help="Delete event")
    p.add_argument("event_id", help="Event ID")
    p.add_argument("--account", "-a", help="Account email")

    # calendars
    p = subparsers.add_parser("calendars", help="List calendars")
    p.add_argument("--account", "-a", help="Account email")

    # search
    p = subparsers.add_parser("search", help="Search events")
    p.add_argument("query", help="Search query")
    p.add_argument("--max-results", "-m", type=int, default=20, help="Max results")
    p.add_argument("--account", "-a", help="Account email")

    # accounts
    subparsers.add_parser("accounts", help="List authenticated accounts")

    # logout
    p = subparsers.add_parser("logout", help="Remove account")
    p.add_argument("--account", "-a", help="Account to remove")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "today": cmd_today,
        "week": cmd_week,
        "agenda": cmd_agenda,
        "event": cmd_event,
        "create": cmd_create,
        "delete": cmd_delete,
        "calendars": cmd_calendars,
        "search": cmd_search,
        "accounts": cmd_accounts,
        "logout": cmd_logout,
    }

    try:
        commands[args.command](args)
    except HttpError as e:
        output({"error": f"API error: {e}"})
        sys.exit(1)
    except Exception as e:
        output({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
