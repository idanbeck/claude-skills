#!/usr/bin/env python3
"""
Google Docs Skill - Create, read, write, and export Google Docs.

Usage:
    python docs_skill.py list [--limit N] [--account EMAIL]
    python docs_skill.py create --title "Name" [--content "Text"] [--account EMAIL]
    python docs_skill.py get DOC_ID [--account EMAIL]
    python docs_skill.py read DOC_ID [--account EMAIL]
    python docs_skill.py append DOC_ID --text "Content" [--account EMAIL]
    python docs_skill.py insert DOC_ID --text "Content" --index N [--account EMAIL]
    python docs_skill.py replace DOC_ID --find "old" --replace "new" [--account EMAIL]
    python docs_skill.py export DOC_ID --format FORMAT [--output PATH] [--account EMAIL]
    python docs_skill.py from-markdown FILE [--title "Name"] [--account EMAIL]
    python docs_skill.py accounts
    python docs_skill.py login [--account EMAIL]
    python docs_skill.py logout [--account EMAIL]

Export formats: pdf, docx, txt, html, md
"""

import argparse
import json
import os
import re
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
    print("Error: Google API libraries not installed.")
    print("Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
TOKENS_DIR = SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"
OUTPUT_DIR = SKILL_DIR / "output"

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

EXPORT_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "html": "text/html",
    "md": "text/plain",  # We'll convert from text
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
}

TOKENS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials_file() -> Path:
    """Get credentials file, falling back to gmail-skill shared creds."""
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE

    # Check other Google skills for shared credentials
    for skill in ["gmail-skill", "google-sheets-skill", "google-slides-skill"]:
        shared = Path.home() / ".claude/skills" / skill / "credentials.json"
        if shared.exists():
            return shared

    print("\n" + "=" * 60)
    print("FIRST-TIME SETUP")
    print("=" * 60)
    print("\nYou need Google OAuth credentials.")
    print("If you have gmail-skill or other Google skills set up, those credentials will work.")
    print("\nOtherwise:")
    print("1. Go to: https://console.cloud.google.com/apis/credentials")
    print("2. Create OAuth client (Desktop app)")
    print("3. Download JSON and save as:")
    print(f"   {CREDENTIALS_FILE}")
    print("4. Enable Google Docs API and Google Drive API in your project")
    print("=" * 60 + "\n")
    sys.exit(1)


def get_token_path(account: str = None) -> Path:
    """Get token file path for account."""
    if account:
        safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in account)
        return TOKENS_DIR / f"token_{safe}.json"
    tokens = list(TOKENS_DIR.glob("token_*.json"))
    return tokens[0] if tokens else TOKENS_DIR / "token_default.json"


def get_credentials(account: str = None):
    """Get or refresh credentials."""
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
            creds = flow.run_local_server(port=9996)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def get_docs_service(account: str = None):
    """Get Google Docs API service."""
    creds = get_credentials(account)
    return build("docs", "v1", credentials=creds)


def get_drive_service(account: str = None):
    """Get Google Drive API service."""
    creds = get_credentials(account)
    return build("drive", "v3", credentials=creds)


def output_json(data):
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


def extract_text_from_doc(doc):
    """Extract plain text from document content."""
    text = []
    content = doc.get("body", {}).get("content", [])

    for element in content:
        if "paragraph" in element:
            for elem in element["paragraph"].get("elements", []):
                if "textRun" in elem:
                    text.append(elem["textRun"].get("content", ""))

    return "".join(text)


def markdown_to_requests(markdown_text):
    """Convert markdown to Google Docs insert requests.

    This is a simplified converter that handles basic markdown.
    """
    requests = []
    current_index = 1  # Google Docs uses 1-based indexing

    lines = markdown_text.split("\n")

    for line in lines:
        text = line
        style_requests = []

        # Handle headers
        if line.startswith("# "):
            text = line[2:] + "\n"
            style_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": current_index, "endIndex": current_index + len(text)},
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "fields": "namedStyleType"
                }
            })
        elif line.startswith("## "):
            text = line[3:] + "\n"
            style_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": current_index, "endIndex": current_index + len(text)},
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    "fields": "namedStyleType"
                }
            })
        elif line.startswith("### "):
            text = line[4:] + "\n"
            style_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": current_index, "endIndex": current_index + len(text)},
                    "paragraphStyle": {"namedStyleType": "HEADING_3"},
                    "fields": "namedStyleType"
                }
            })
        elif line.startswith("---"):
            # Horizontal rule - insert a line break
            text = "\n"
        else:
            text = line + "\n"

        # Insert text
        if text:
            requests.append({
                "insertText": {
                    "location": {"index": current_index},
                    "text": text
                }
            })
            current_index += len(text)
            requests.extend(style_requests)

    return requests


# Commands

def cmd_accounts(args):
    """List authenticated accounts."""
    accounts = []
    for f in TOKENS_DIR.glob("token_*.json"):
        accounts.append({"name": f.stem.replace("token_", ""), "file": str(f)})
    output_json({"accounts": accounts})


def cmd_login(args):
    """Authenticate with Google."""
    creds = get_credentials(args.account)
    output_json({"success": True, "account": args.account or "default"})


def cmd_logout(args):
    """Remove authentication for account."""
    path = get_token_path(args.account)
    if path.exists():
        path.unlink()
        output_json({"success": True})
    else:
        output_json({"error": "Account not found"})


def cmd_list(args):
    """List Google Docs."""
    drive = get_drive_service(args.account)
    results = drive.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        pageSize=args.limit,
        fields="files(id, name, modifiedTime, webViewLink)"
    ).execute()
    files = results.get("files", [])
    output_json({"documents": files, "count": len(files)})


def cmd_create(args):
    """Create a new Google Doc."""
    docs = get_docs_service(args.account)

    body = {"title": args.title}
    doc = docs.documents().create(body=body).execute()
    doc_id = doc.get("documentId")

    # If content provided, insert it
    if args.content:
        requests = [{
            "insertText": {
                "location": {"index": 1},
                "text": args.content
            }
        }]
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    output_json({
        "success": True,
        "documentId": doc_id,
        "title": args.title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit"
    })


def cmd_get(args):
    """Get document metadata."""
    docs = get_docs_service(args.account)
    doc = docs.documents().get(documentId=args.doc_id).execute()

    output_json({
        "documentId": doc.get("documentId"),
        "title": doc.get("title"),
        "url": f"https://docs.google.com/document/d/{doc.get('documentId')}/edit",
        "revisionId": doc.get("revisionId"),
    })


def cmd_read(args):
    """Read document content as plain text."""
    docs = get_docs_service(args.account)
    doc = docs.documents().get(documentId=args.doc_id).execute()

    text = extract_text_from_doc(doc)

    output_json({
        "documentId": doc.get("documentId"),
        "title": doc.get("title"),
        "content": text,
        "length": len(text),
    })


def cmd_append(args):
    """Append text to end of document."""
    docs = get_docs_service(args.account)

    # Get current document to find end index
    doc = docs.documents().get(documentId=args.doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    # Find the end index (last element's endIndex - 1)
    end_index = 1
    if content:
        end_index = content[-1].get("endIndex", 1) - 1

    requests = [{
        "insertText": {
            "location": {"index": end_index},
            "text": args.text
        }
    }]

    result = docs.documents().batchUpdate(
        documentId=args.doc_id,
        body={"requests": requests}
    ).execute()

    output_json({
        "success": True,
        "documentId": args.doc_id,
        "appendedText": args.text[:100] + "..." if len(args.text) > 100 else args.text,
    })


def cmd_insert(args):
    """Insert text at specific index."""
    docs = get_docs_service(args.account)

    requests = [{
        "insertText": {
            "location": {"index": args.index},
            "text": args.text
        }
    }]

    result = docs.documents().batchUpdate(
        documentId=args.doc_id,
        body={"requests": requests}
    ).execute()

    output_json({
        "success": True,
        "documentId": args.doc_id,
        "insertedAt": args.index,
    })


def cmd_replace(args):
    """Find and replace text in document."""
    docs = get_docs_service(args.account)

    requests = [{
        "replaceAllText": {
            "containsText": {
                "text": args.find,
                "matchCase": True
            },
            "replaceText": args.replace
        }
    }]

    result = docs.documents().batchUpdate(
        documentId=args.doc_id,
        body={"requests": requests}
    ).execute()

    # Get replacement count from response
    replies = result.get("replies", [{}])
    occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)

    output_json({
        "success": True,
        "documentId": args.doc_id,
        "replacements": occurrences,
        "find": args.find,
        "replace": args.replace,
    })


def cmd_export(args):
    """Export document to various formats."""
    drive = get_drive_service(args.account)
    docs = get_docs_service(args.account)

    fmt = args.format.lower()
    if fmt not in EXPORT_FORMATS:
        output_json({"error": f"Unknown format: {fmt}", "available": list(EXPORT_FORMATS.keys())})
        return

    mime_type = EXPORT_FORMATS[fmt]

    # Get document title for filename
    doc = docs.documents().get(documentId=args.doc_id).execute()
    title = doc.get("title", "document")
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()

    # Export file
    request = drive.files().export_media(fileId=args.doc_id, mimeType=mime_type)

    file_data = io.BytesIO()
    downloader = MediaIoBaseDownload(file_data, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    # Determine output path
    ext = fmt if fmt != "md" else "txt"
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = OUTPUT_DIR / f"{safe_title}.{ext}"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(file_data.getvalue())

    output_json({
        "success": True,
        "documentId": args.doc_id,
        "title": title,
        "format": fmt,
        "file": str(output_path),
        "size": output_path.stat().st_size,
    })


def cmd_from_markdown(args):
    """Create a Google Doc from a markdown file."""
    docs = get_docs_service(args.account)

    # Read markdown file
    md_path = Path(args.file)
    if not md_path.exists():
        output_json({"error": f"File not found: {args.file}"})
        return

    with open(md_path, "r") as f:
        markdown_content = f.read()

    # Use filename as title if not provided
    title = args.title or md_path.stem

    # Create empty document
    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")

    # Convert markdown to requests and apply
    requests = markdown_to_requests(markdown_content)

    if requests:
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()

    output_json({
        "success": True,
        "documentId": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        "sourceFile": str(md_path),
    })


def add_account_arg(parser):
    """Add account argument to parser."""
    parser.add_argument("--account", "-a", help="Account to use")


def main():
    parser = argparse.ArgumentParser(description="Google Docs Skill")
    subs = parser.add_subparsers(dest="command")

    # accounts
    subs.add_parser("accounts").set_defaults(func=cmd_accounts)

    # login
    login = subs.add_parser("login")
    login.add_argument("--account", "-a")
    login.set_defaults(func=cmd_login)

    # logout
    logout = subs.add_parser("logout")
    logout.add_argument("--account", "-a")
    logout.set_defaults(func=cmd_logout)

    # list
    ls = subs.add_parser("list")
    ls.add_argument("--limit", "-l", type=int, default=20)
    add_account_arg(ls)
    ls.set_defaults(func=cmd_list)

    # create
    create = subs.add_parser("create")
    create.add_argument("--title", "-t", required=True, help="Document title")
    create.add_argument("--content", "-c", help="Initial content")
    add_account_arg(create)
    create.set_defaults(func=cmd_create)

    # get
    get = subs.add_parser("get")
    get.add_argument("doc_id", help="Document ID")
    add_account_arg(get)
    get.set_defaults(func=cmd_get)

    # read
    read = subs.add_parser("read")
    read.add_argument("doc_id", help="Document ID")
    add_account_arg(read)
    read.set_defaults(func=cmd_read)

    # append
    append = subs.add_parser("append")
    append.add_argument("doc_id", help="Document ID")
    append.add_argument("--text", "-t", required=True, help="Text to append")
    add_account_arg(append)
    append.set_defaults(func=cmd_append)

    # insert
    insert = subs.add_parser("insert")
    insert.add_argument("doc_id", help="Document ID")
    insert.add_argument("--text", "-t", required=True, help="Text to insert")
    insert.add_argument("--index", "-i", type=int, required=True, help="Index to insert at")
    add_account_arg(insert)
    insert.set_defaults(func=cmd_insert)

    # replace
    replace = subs.add_parser("replace")
    replace.add_argument("doc_id", help="Document ID")
    replace.add_argument("--find", "-f", required=True, help="Text to find")
    replace.add_argument("--replace", "-r", required=True, help="Replacement text")
    add_account_arg(replace)
    replace.set_defaults(func=cmd_replace)

    # export
    export = subs.add_parser("export")
    export.add_argument("doc_id", help="Document ID")
    export.add_argument("--format", "-f", required=True, help="Export format: pdf, docx, txt, html, md")
    export.add_argument("--output", "-o", help="Output file path")
    add_account_arg(export)
    export.set_defaults(func=cmd_export)

    # from-markdown
    from_md = subs.add_parser("from-markdown")
    from_md.add_argument("file", help="Markdown file path")
    from_md.add_argument("--title", "-t", help="Document title (defaults to filename)")
    add_account_arg(from_md)
    from_md.set_defaults(func=cmd_from_markdown)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
