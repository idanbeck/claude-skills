#!/usr/bin/env python3
"""
Google Slides Skill - Create and manage presentations.

Usage:
    python slides_skill.py list [--limit N] [--account EMAIL]
    python slides_skill.py get PRESENTATION_ID [--account EMAIL]
    python slides_skill.py create --title "Name" [--account EMAIL]
    python slides_skill.py add-slide PRESENTATION_ID [--layout LAYOUT] [--account EMAIL]
    python slides_skill.py delete-slide PRESENTATION_ID --slide-id ID [--account EMAIL]
    python slides_skill.py add-text PRESENTATION_ID --slide-id ID --text "..." [--x X] [--y Y] [--w W] [--h H]
    python slides_skill.py add-image PRESENTATION_ID --slide-id ID --url URL [--x X] [--y Y] [--w W] [--h H]
    python slides_skill.py replace-text PRESENTATION_ID --find "old" --replace "new"
    python slides_skill.py export PRESENTATION_ID [--format pdf|pptx] [--output FILE]
    python slides_skill.py accounts
    python slides_skill.py login [--account EMAIL]
    python slides_skill.py logout [--account EMAIL]
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
    from googleapiclient.http import MediaIoBaseDownload
    import io
except ImportError:
    print("Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
TOKENS_DIR = SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
]

TOKENS_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials_file() -> Path:
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    for alt in ["gmail-skill", "google-sheets-skill"]:
        p = Path.home() / f".claude/skills/{alt}/credentials.json"
        if p.exists():
            return p
    print("No credentials.json found. Set up gmail-skill or add credentials here.")
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
            creds = flow.run_local_server(port=9994)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def get_slides_service(account: str = None):
    return build("slides", "v1", credentials=get_credentials(account))


def get_drive_service(account: str = None):
    return build("drive", "v3", credentials=get_credentials(account))


def emu(inches: float) -> int:
    """Convert inches to EMU (English Metric Units)."""
    return int(inches * 914400)


# Commands

def cmd_accounts(args):
    accounts = [{"name": f.stem.replace("token_", "")} for f in TOKENS_DIR.glob("token_*.json")]
    print(json.dumps({"accounts": accounts}, indent=2))


def cmd_login(args):
    get_credentials(args.account)
    print(json.dumps({"success": True}, indent=2))


def cmd_logout(args):
    path = get_token_path(args.account)
    if path.exists():
        path.unlink()
    print(json.dumps({"success": True}, indent=2))


def cmd_list(args):
    drive = get_drive_service(args.account)
    results = drive.files().list(
        q="mimeType='application/vnd.google-apps.presentation'",
        pageSize=args.limit,
        fields="files(id, name, modifiedTime, webViewLink)"
    ).execute()
    print(json.dumps({"presentations": results.get("files", [])}, indent=2))


def cmd_get(args):
    service = get_slides_service(args.account)
    pres = service.presentations().get(presentationId=args.presentation_id).execute()

    slides = [{
        "objectId": s["objectId"],
        "pageElements": len(s.get("pageElements", [])),
    } for s in pres.get("slides", [])]

    print(json.dumps({
        "presentationId": pres.get("presentationId"),
        "title": pres.get("title"),
        "slides": slides,
        "slideCount": len(slides),
    }, indent=2))


def cmd_create(args):
    service = get_slides_service(args.account)
    pres = service.presentations().create(body={"title": args.title}).execute()
    print(json.dumps({
        "success": True,
        "presentationId": pres.get("presentationId"),
        "title": pres.get("title"),
    }, indent=2))


def cmd_add_slide(args):
    service = get_slides_service(args.account)

    layout_map = {
        "blank": "BLANK",
        "title": "TITLE",
        "title_body": "TITLE_AND_BODY",
        "title_two_columns": "TITLE_AND_TWO_COLUMNS",
        "title_only": "TITLE_ONLY",
        "section": "SECTION_HEADER",
        "big_number": "BIG_NUMBER",
    }
    layout = layout_map.get(args.layout, "BLANK")

    requests = [{
        "createSlide": {
            "slideLayoutReference": {"predefinedLayout": layout}
        }
    }]

    result = service.presentations().batchUpdate(
        presentationId=args.presentation_id,
        body={"requests": requests}
    ).execute()

    slide_id = result.get("replies", [{}])[0].get("createSlide", {}).get("objectId")
    print(json.dumps({"success": True, "slideId": slide_id}, indent=2))


def cmd_delete_slide(args):
    service = get_slides_service(args.account)
    requests = [{"deleteObject": {"objectId": args.slide_id}}]
    service.presentations().batchUpdate(
        presentationId=args.presentation_id,
        body={"requests": requests}
    ).execute()
    print(json.dumps({"success": True}, indent=2))


def cmd_add_text(args):
    service = get_slides_service(args.account)

    element_id = f"text_{args.slide_id}_{hash(args.text) % 10000}"

    requests = [
        {
            "createShape": {
                "objectId": element_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": args.slide_id,
                    "size": {
                        "width": {"magnitude": emu(args.w), "unit": "EMU"},
                        "height": {"magnitude": emu(args.h), "unit": "EMU"},
                    },
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": emu(args.x), "translateY": emu(args.y),
                        "unit": "EMU",
                    },
                },
            }
        },
        {
            "insertText": {
                "objectId": element_id,
                "text": args.text,
                "insertionIndex": 0,
            }
        }
    ]

    service.presentations().batchUpdate(
        presentationId=args.presentation_id,
        body={"requests": requests}
    ).execute()
    print(json.dumps({"success": True, "elementId": element_id}, indent=2))


def cmd_add_image(args):
    service = get_slides_service(args.account)

    element_id = f"img_{args.slide_id}_{hash(args.url) % 10000}"

    requests = [{
        "createImage": {
            "objectId": element_id,
            "url": args.url,
            "elementProperties": {
                "pageObjectId": args.slide_id,
                "size": {
                    "width": {"magnitude": emu(args.w), "unit": "EMU"},
                    "height": {"magnitude": emu(args.h), "unit": "EMU"},
                },
                "transform": {
                    "scaleX": 1, "scaleY": 1,
                    "translateX": emu(args.x), "translateY": emu(args.y),
                    "unit": "EMU",
                },
            },
        }
    }]

    service.presentations().batchUpdate(
        presentationId=args.presentation_id,
        body={"requests": requests}
    ).execute()
    print(json.dumps({"success": True, "elementId": element_id}, indent=2))


def cmd_replace_text(args):
    service = get_slides_service(args.account)

    requests = [{
        "replaceAllText": {
            "containsText": {"text": args.find, "matchCase": True},
            "replaceText": args.replace,
        }
    }]

    result = service.presentations().batchUpdate(
        presentationId=args.presentation_id,
        body={"requests": requests}
    ).execute()

    occurrences = result.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    print(json.dumps({"success": True, "replacements": occurrences}, indent=2))


def cmd_export(args):
    drive = get_drive_service(args.account)

    mime_map = {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    mime = mime_map.get(args.format, "application/pdf")
    ext = args.format or "pdf"

    request = drive.files().export_media(fileId=args.presentation_id, mimeType=mime)
    output = args.output or f"presentation.{ext}"

    with open(output, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    print(json.dumps({"success": True, "file": output}, indent=2))


def add_account_arg(p):
    p.add_argument("--account", "-a")


def main():
    parser = argparse.ArgumentParser(description="Google Slides Skill")
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
    get.add_argument("presentation_id")
    add_account_arg(get)
    get.set_defaults(func=cmd_get)

    create = subs.add_parser("create")
    create.add_argument("--title", "-t", required=True)
    add_account_arg(create)
    create.set_defaults(func=cmd_create)

    add_slide = subs.add_parser("add-slide")
    add_slide.add_argument("presentation_id")
    add_slide.add_argument("--layout", choices=["blank", "title", "title_body", "title_two_columns", "title_only", "section", "big_number"], default="blank")
    add_account_arg(add_slide)
    add_slide.set_defaults(func=cmd_add_slide)

    del_slide = subs.add_parser("delete-slide")
    del_slide.add_argument("presentation_id")
    del_slide.add_argument("--slide-id", required=True)
    add_account_arg(del_slide)
    del_slide.set_defaults(func=cmd_delete_slide)

    add_text = subs.add_parser("add-text")
    add_text.add_argument("presentation_id")
    add_text.add_argument("--slide-id", required=True)
    add_text.add_argument("--text", "-t", required=True)
    add_text.add_argument("--x", type=float, default=1)
    add_text.add_argument("--y", type=float, default=1)
    add_text.add_argument("--w", type=float, default=8)
    add_text.add_argument("--h", type=float, default=1)
    add_account_arg(add_text)
    add_text.set_defaults(func=cmd_add_text)

    add_img = subs.add_parser("add-image")
    add_img.add_argument("presentation_id")
    add_img.add_argument("--slide-id", required=True)
    add_img.add_argument("--url", required=True)
    add_img.add_argument("--x", type=float, default=1)
    add_img.add_argument("--y", type=float, default=1)
    add_img.add_argument("--w", type=float, default=4)
    add_img.add_argument("--h", type=float, default=3)
    add_account_arg(add_img)
    add_img.set_defaults(func=cmd_add_image)

    replace = subs.add_parser("replace-text")
    replace.add_argument("presentation_id")
    replace.add_argument("--find", "-f", required=True)
    replace.add_argument("--replace", "-r", required=True)
    add_account_arg(replace)
    replace.set_defaults(func=cmd_replace_text)

    export = subs.add_parser("export")
    export.add_argument("presentation_id")
    export.add_argument("--format", choices=["pdf", "pptx"], default="pdf")
    export.add_argument("--output", "-o")
    add_account_arg(export)
    export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
