#!/usr/bin/env python3
"""
Google Sheets Skill - Read and write Google Sheets.

Usage:
    python sheets_skill.py list [--limit N] [--account EMAIL]
    python sheets_skill.py get SPREADSHEET_ID [--range RANGE] [--account EMAIL]
    python sheets_skill.py read SPREADSHEET_ID RANGE [--account EMAIL]
    python sheets_skill.py write SPREADSHEET_ID RANGE --values '[[...]]' [--account EMAIL]
    python sheets_skill.py append SPREADSHEET_ID RANGE --values '[[...]]' [--account EMAIL]
    python sheets_skill.py clear SPREADSHEET_ID RANGE [--account EMAIL]
    python sheets_skill.py create --title "Name" [--account EMAIL]
    python sheets_skill.py add-sheet SPREADSHEET_ID --title "Sheet Name" [--account EMAIL]
    python sheets_skill.py delete-sheet SPREADSHEET_ID --sheet-id ID [--account EMAIL]
    python sheets_skill.py accounts
    python sheets_skill.py login [--account EMAIL]
    python sheets_skill.py logout [--account EMAIL]
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print("Error: Google API libraries not installed.")
    print("Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
TOKENS_DIR = SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

TOKENS_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials_file() -> Path:
    # Check skill dir first, then fall back to gmail-skill (shared Google creds)
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    gmail_creds = Path.home() / ".claude/skills/gmail-skill/credentials.json"
    if gmail_creds.exists():
        return gmail_creds

    print("\n" + "=" * 60)
    print("FIRST-TIME SETUP")
    print("=" * 60)
    print("\nYou need Google OAuth credentials.")
    print("If you have gmail-skill set up, those credentials will work.")
    print("\nOtherwise:")
    print("1. Go to: https://console.cloud.google.com/apis/credentials")
    print("2. Create OAuth client (Desktop app)")
    print("3. Download JSON and save as:")
    print(f"   {CREDENTIALS_FILE}")
    print("4. Enable Google Sheets API in your project")
    print("=" * 60 + "\n")
    sys.exit(1)


def get_token_path(account: str = None) -> Path:
    if account:
        safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in account)
        return TOKENS_DIR / f"token_{safe}.json"
    tokens = list(TOKENS_DIR.glob("token_*.json"))
    return tokens[0] if tokens else TOKENS_DIR / "token_default.json"


def get_credentials(account: str = None):
    creds_file = get_credentials_file()
    token_path = get_token_path(account)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=9995)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def get_service(account: str = None):
    creds = get_credentials(account)
    return build("sheets", "v4", credentials=creds)


def get_drive_service(account: str = None):
    creds = get_credentials(account)
    return build("drive", "v3", credentials=creds)


# Commands

def cmd_accounts(args):
    accounts = []
    for f in TOKENS_DIR.glob("token_*.json"):
        accounts.append({"name": f.stem.replace("token_", ""), "file": str(f)})
    print(json.dumps({"accounts": accounts}, indent=2))


def cmd_login(args):
    creds = get_credentials(args.account)
    print(json.dumps({"success": True, "account": args.account or "default"}, indent=2))


def cmd_logout(args):
    path = get_token_path(args.account)
    if path.exists():
        path.unlink()
        print(json.dumps({"success": True}))
    else:
        print(json.dumps({"error": "Account not found"}))


def cmd_list(args):
    drive = get_drive_service(args.account)
    results = drive.files().list(
        q="mimeType='application/vnd.google-apps.spreadsheet'",
        pageSize=args.limit,
        fields="files(id, name, modifiedTime, webViewLink)"
    ).execute()
    files = results.get("files", [])
    print(json.dumps({"spreadsheets": files, "count": len(files)}, indent=2))


def cmd_get(args):
    service = get_service(args.account)
    result = service.spreadsheets().get(
        spreadsheetId=args.spreadsheet_id,
        ranges=[args.range] if args.range else None
    ).execute()

    sheets = [{
        "sheetId": s["properties"]["sheetId"],
        "title": s["properties"]["title"],
        "index": s["properties"]["index"],
        "rowCount": s["properties"]["gridProperties"]["rowCount"],
        "columnCount": s["properties"]["gridProperties"]["columnCount"],
    } for s in result.get("sheets", [])]

    print(json.dumps({
        "spreadsheetId": result.get("spreadsheetId"),
        "title": result.get("properties", {}).get("title"),
        "url": result.get("spreadsheetUrl"),
        "sheets": sheets,
    }, indent=2))


def cmd_read(args):
    service = get_service(args.account)
    result = service.spreadsheets().values().get(
        spreadsheetId=args.spreadsheet_id,
        range=args.range
    ).execute()

    values = result.get("values", [])
    print(json.dumps({
        "range": result.get("range"),
        "values": values,
        "rows": len(values),
        "cols": max(len(r) for r in values) if values else 0,
    }, indent=2))


def cmd_write(args):
    service = get_service(args.account)
    values = json.loads(args.values)

    result = service.spreadsheets().values().update(
        spreadsheetId=args.spreadsheet_id,
        range=args.range,
        valueInputOption="USER_ENTERED",
        body={"values": values}
    ).execute()

    print(json.dumps({
        "success": True,
        "updatedRange": result.get("updatedRange"),
        "updatedRows": result.get("updatedRows"),
        "updatedColumns": result.get("updatedColumns"),
        "updatedCells": result.get("updatedCells"),
    }, indent=2))


def cmd_append(args):
    service = get_service(args.account)
    values = json.loads(args.values)

    result = service.spreadsheets().values().append(
        spreadsheetId=args.spreadsheet_id,
        range=args.range,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()

    updates = result.get("updates", {})
    print(json.dumps({
        "success": True,
        "updatedRange": updates.get("updatedRange"),
        "updatedRows": updates.get("updatedRows"),
        "updatedCells": updates.get("updatedCells"),
    }, indent=2))


def cmd_clear(args):
    service = get_service(args.account)
    result = service.spreadsheets().values().clear(
        spreadsheetId=args.spreadsheet_id,
        range=args.range
    ).execute()
    print(json.dumps({"success": True, "clearedRange": result.get("clearedRange")}, indent=2))


def cmd_create(args):
    service = get_service(args.account)
    result = service.spreadsheets().create(
        body={"properties": {"title": args.title}}
    ).execute()
    print(json.dumps({
        "success": True,
        "spreadsheetId": result.get("spreadsheetId"),
        "url": result.get("spreadsheetUrl"),
    }, indent=2))


def cmd_add_sheet(args):
    service = get_service(args.account)
    result = service.spreadsheets().batchUpdate(
        spreadsheetId=args.spreadsheet_id,
        body={
            "requests": [{
                "addSheet": {"properties": {"title": args.title}}
            }]
        }
    ).execute()

    reply = result.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
    print(json.dumps({
        "success": True,
        "sheetId": reply.get("sheetId"),
        "title": reply.get("title"),
    }, indent=2))


def cmd_delete_sheet(args):
    service = get_service(args.account)
    service.spreadsheets().batchUpdate(
        spreadsheetId=args.spreadsheet_id,
        body={
            "requests": [{
                "deleteSheet": {"sheetId": args.sheet_id}
            }]
        }
    ).execute()
    print(json.dumps({"success": True}, indent=2))


def add_account_arg(p):
    p.add_argument("--account", "-a", help="Account to use")


def main():
    parser = argparse.ArgumentParser(description="Google Sheets Skill")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("accounts").set_defaults(func=cmd_accounts)

    login = subs.add_parser("login")
    login.add_argument("--account", "-a")
    login.set_defaults(func=cmd_login)

    logout = subs.add_parser("logout")
    logout.add_argument("--account", "-a")
    logout.set_defaults(func=cmd_logout)

    ls = subs.add_parser("list")
    ls.add_argument("--limit", "-l", type=int, default=20)
    add_account_arg(ls)
    ls.set_defaults(func=cmd_list)

    get = subs.add_parser("get")
    get.add_argument("spreadsheet_id")
    get.add_argument("--range", "-r")
    add_account_arg(get)
    get.set_defaults(func=cmd_get)

    read = subs.add_parser("read")
    read.add_argument("spreadsheet_id")
    read.add_argument("range")
    add_account_arg(read)
    read.set_defaults(func=cmd_read)

    write = subs.add_parser("write")
    write.add_argument("spreadsheet_id")
    write.add_argument("range")
    write.add_argument("--values", "-v", required=True, help='JSON array: [["a","b"],["c","d"]]')
    add_account_arg(write)
    write.set_defaults(func=cmd_write)

    append = subs.add_parser("append")
    append.add_argument("spreadsheet_id")
    append.add_argument("range")
    append.add_argument("--values", "-v", required=True)
    add_account_arg(append)
    append.set_defaults(func=cmd_append)

    clear = subs.add_parser("clear")
    clear.add_argument("spreadsheet_id")
    clear.add_argument("range")
    add_account_arg(clear)
    clear.set_defaults(func=cmd_clear)

    create = subs.add_parser("create")
    create.add_argument("--title", "-t", required=True)
    add_account_arg(create)
    create.set_defaults(func=cmd_create)

    add_sheet = subs.add_parser("add-sheet")
    add_sheet.add_argument("spreadsheet_id")
    add_sheet.add_argument("--title", "-t", required=True)
    add_account_arg(add_sheet)
    add_sheet.set_defaults(func=cmd_add_sheet)

    del_sheet = subs.add_parser("delete-sheet")
    del_sheet.add_argument("spreadsheet_id")
    del_sheet.add_argument("--sheet-id", type=int, required=True)
    add_account_arg(del_sheet)
    del_sheet.set_defaults(func=cmd_delete_sheet)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
