#!/usr/bin/env python3
"""
Google Drive Skill — folder + file CRUD for arbitrary Drive content.

Companion to google-docs-skill (which targets the Docs API specifically).
This skill is for moving bytes — bundles, archives, datasets, photo dumps —
into and out of Drive folders.

Usage:
    python drive_skill.py login [--account EMAIL]
    python drive_skill.py accounts
    python drive_skill.py logout [--account EMAIL]

    python drive_skill.py mkdir NAME [--parent FOLDER_ID] [--account EMAIL]
    python drive_skill.py upload SRC [--parent FOLDER_ID] [--name NAME] [--account EMAIL]
    python drive_skill.py upload-tree SRC_DIR --parent FOLDER_ID [--account EMAIL]
    python drive_skill.py list FOLDER_ID [--limit N] [--account EMAIL]
    python drive_skill.py info FILE_OR_FOLDER_ID [--account EMAIL]
    python drive_skill.py share FILE_OR_FOLDER_ID --email EMAIL [--role reader|writer|commenter] [--account EMAIL]
    python drive_skill.py rm FILE_OR_FOLDER_ID [--permanent] [--account EMAIL]
    python drive_skill.py download FILE_ID --output PATH [--account EMAIL]

Auth:
    Reuses the OAuth client + Drive scope from google-docs-skill. If a
    token already exists for the requested account at
    ~/.claude/skills/google-docs-skill/tokens/token_<account>.json,
    this skill picks it up automatically — no separate login.
    Otherwise it falls back to its own tokens directory.

Output: JSON to stdout for easy piping.
"""

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    import io
except ImportError:
    print("Error: Google API libraries not installed.", file=sys.stderr)
    print("Run: pip install google-auth google-auth-oauthlib google-api-python-client", file=sys.stderr)
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
DOCS_SKILL_DIR = SKILL_DIR.parent / "google-docs-skill"
TOKENS_DIR = SKILL_DIR / "tokens"
DOCS_TOKENS_DIR = DOCS_SKILL_DIR / "tokens"
CREDENTIALS_FILE = SKILL_DIR / "credentials.json"
DOCS_CREDENTIALS_FILE = DOCS_SKILL_DIR / "credentials.json"
OUTPUT_DIR = SKILL_DIR / "output"

TOKENS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

FOLDER_MIME = "application/vnd.google-apps.folder"


# ─── Auth ──────────────────────────────────────────────────────────────

def get_credentials_file() -> Path:
    """Find an OAuth client.json. Same fallback chain as docs-skill so
    a single shared client across the Google skills works."""
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    # Walk the other Google-skill dirs that ship a credentials.json.
    for skill in ["gmail-skill", "google-docs-skill", "google-sheets-skill", "google-slides-skill"]:
        shared = Path.home() / ".claude/skills" / skill / "credentials.json"
        if shared.exists():
            return shared
    return CREDENTIALS_FILE  # nonexistent — caller surfaces the error


def safe_account(email: str) -> str:
    return email.replace("@", "_").replace(".", "_") if email else "default"


def token_path(account: str = None) -> Path:
    """Find an existing token: prefer this skill's, fall back to docs-skill."""
    if account:
        safe = safe_account(account)
        local = TOKENS_DIR / f"token_{safe}.json"
        if local.exists():
            return local
        shared = DOCS_TOKENS_DIR / f"token_{safe}.json"
        if shared.exists():
            return shared
        return TOKENS_DIR / f"token_{safe}.json"  # fallback for new login
    # No account — pick the first available token across both dirs.
    for d in (TOKENS_DIR, DOCS_TOKENS_DIR):
        toks = sorted(d.glob("token_*.json"))
        if toks:
            return toks[0]
    return TOKENS_DIR / "token_default.json"


def get_credentials(account: str = None):
    tok = token_path(account)
    creds = None
    if tok.exists():
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tok.parent.mkdir(parents=True, exist_ok=True)
            with open(tok, "w") as f:
                f.write(creds.to_json())
        except Exception as e:
            print(f"warn: token refresh failed for {tok}: {e}", file=sys.stderr)
    if not creds or not creds.valid:
        creds_file = get_credentials_file()
        if not creds_file.exists():
            print(
                f"error: no OAuth credentials.json at {creds_file}.\n"
                "Reuse the docs-skill credentials or place a Desktop OAuth client "
                "JSON at one of the two locations.",
                file=sys.stderr,
            )
            sys.exit(1)
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
        creds = flow.run_local_server(port=0)
        # Save under THIS skill's token dir for future runs.
        save = TOKENS_DIR / f"token_{safe_account(account)}.json" if account else TOKENS_DIR / "token_default.json"
        save.parent.mkdir(parents=True, exist_ok=True)
        with open(save, "w") as f:
            f.write(creds.to_json())
        # Also rename to reflect the actual logged-in email if available.
        try:
            from googleapiclient.discovery import build as _b
            svc = _b("oauth2", "v2", credentials=creds)
            email = svc.userinfo().get().execute().get("email")
            if email and not account:
                final = TOKENS_DIR / f"token_{safe_account(email)}.json"
                if final != save:
                    save.rename(final)
        except Exception:
            pass
    return creds


def get_drive_service(account: str = None):
    creds = get_credentials(account)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_account_email(account: str = None) -> Optional[str]:
    """Best-effort: read the email out of the token file."""
    tok = token_path(account)
    if not tok.exists():
        return account
    try:
        with open(tok) as f:
            data = json.load(f)
        # Tokens don't always carry the email; fall back to the filename.
        name = tok.stem.replace("token_", "")
        return name.replace("_", "@", 1).replace("_", ".") if name != "default" else None
    except Exception:
        return account


def output_json(obj):
    print(json.dumps(obj, indent=2, default=str))


# ─── Commands ──────────────────────────────────────────────────────────

def cmd_login(args):
    creds = get_credentials(args.account)
    try:
        oa = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = oa.userinfo().get().execute()
        output_json({"ok": True, "email": info.get("email"), "scopes": SCOPES})
    except Exception as e:
        output_json({"ok": True, "email": args.account, "scopes": SCOPES, "warn": str(e)})


def cmd_accounts(args):
    out = {"local": [], "shared_from_docs": []}
    for f in sorted(TOKENS_DIR.glob("token_*.json")):
        out["local"].append(f.stem.replace("token_", ""))
    for f in sorted(DOCS_TOKENS_DIR.glob("token_*.json")):
        out["shared_from_docs"].append(f.stem.replace("token_", ""))
    output_json(out)


def cmd_logout(args):
    tok = TOKENS_DIR / (f"token_{safe_account(args.account)}.json" if args.account else "token_default.json")
    if tok.exists():
        tok.unlink()
        output_json({"ok": True, "removed": str(tok)})
    else:
        output_json({"ok": False, "error": f"no token at {tok}"})


def cmd_mkdir(args):
    drive = get_drive_service(args.account)
    metadata = {"name": args.name, "mimeType": FOLDER_MIME}
    if args.parent:
        metadata["parents"] = [args.parent]
    folder = drive.files().create(body=metadata, fields="id, name, parents, webViewLink").execute()
    output_json({
        "ok": True,
        "id": folder["id"],
        "name": folder["name"],
        "parents": folder.get("parents", []),
        "webViewLink": folder.get("webViewLink"),
    })


def cmd_upload(args):
    drive = get_drive_service(args.account)
    src = Path(args.src)
    if not src.exists():
        output_json({"ok": False, "error": f"source not found: {src}"})
        return
    if src.is_dir():
        output_json({"ok": False, "error": "src is a directory; use upload-tree"})
        return
    name = args.name or src.name
    mime = args.mime or mimetypes.guess_type(str(src))[0] or "application/octet-stream"
    metadata = {"name": name}
    if args.parent:
        metadata["parents"] = [args.parent]
    media = MediaFileUpload(str(src), mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
    request = drive.files().create(body=metadata, media_body=media, fields="id, name, parents, size, mimeType, webViewLink, webContentLink")
    response = None
    last_pct = -1
    while response is None:
        status, response = request.next_chunk()
        if status and not args.quiet:
            pct = int(status.progress() * 100)
            if pct != last_pct:
                print(f"  {name}: {pct}%", file=sys.stderr)
                last_pct = pct
    output_json({
        "ok": True,
        "id": response["id"],
        "name": response["name"],
        "size": response.get("size"),
        "mimeType": response.get("mimeType"),
        "parents": response.get("parents", []),
        "webViewLink": response.get("webViewLink"),
        "webContentLink": response.get("webContentLink"),
    })


def _ensure_folder(drive, name: str, parent_id: str, cache: dict) -> str:
    key = (parent_id, name)
    if key in cache:
        return cache[key]
    # Try to find an existing folder with that name under the parent.
    safe = name.replace("'", "\\'")
    q = f"'{parent_id}' in parents and name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    res = drive.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    files = res.get("files", [])
    if files:
        cache[key] = files[0]["id"]
        return cache[key]
    # Create.
    folder = drive.files().create(
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
        fields="id",
    ).execute()
    cache[key] = folder["id"]
    return folder["id"]


def cmd_upload_tree(args):
    drive = get_drive_service(args.account)
    src = Path(args.src).resolve()
    if not src.is_dir():
        output_json({"ok": False, "error": f"not a directory: {src}"})
        return
    folder_cache: dict = {}
    summary = {"folders_created_or_found": 0, "files_uploaded": 0, "bytes_uploaded": 0, "skipped": [], "errors": []}

    # Walk depth-first; build the Drive folder hierarchy as we go.
    for path in sorted(src.rglob("*")):
        # Skip .DS_Store and hidden cruft by default
        if path.name.startswith(".DS_Store") or path.name == ".DS_Store":
            summary["skipped"].append(str(path.relative_to(src)))
            continue
        rel = path.relative_to(src)
        parent_id = args.parent
        # Walk parent dirs and ensure each exists in Drive
        for part in rel.parts[:-1]:
            parent_id = _ensure_folder(drive, part, parent_id, folder_cache)
            summary["folders_created_or_found"] = len(folder_cache)
        if path.is_dir():
            # Ensure even the empty leaf dir
            _ensure_folder(drive, path.name, parent_id, folder_cache)
            summary["folders_created_or_found"] = len(folder_cache)
            continue
        if not path.is_file():
            continue
        try:
            mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            media = MediaFileUpload(str(path), mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
            req = drive.files().create(
                body={"name": path.name, "parents": [parent_id]},
                media_body=media,
                fields="id, size",
            )
            resp = None
            last_pct = -1
            while resp is None:
                status, resp = req.next_chunk()
                if status and not args.quiet:
                    pct = int(status.progress() * 100)
                    if pct != last_pct and pct % 25 == 0:
                        sys.stderr.write(f"    {rel}: {pct}%\n")
                        last_pct = pct
            summary["files_uploaded"] += 1
            summary["bytes_uploaded"] += int(resp.get("size") or 0)
            if not args.quiet:
                sys.stderr.write(f"  ✓ {rel} ({resp.get('size')} bytes)\n")
        except Exception as e:
            summary["errors"].append({"path": str(rel), "error": str(e)})
            sys.stderr.write(f"  ✗ {rel}: {e}\n")

    output_json({"ok": True, **summary})


def cmd_list(args):
    drive = get_drive_service(args.account)
    q = f"'{args.folder}' in parents and trashed = false"
    page_token = None
    items = []
    while True:
        res = drive.files().list(
            q=q,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        items.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token or (args.limit and len(items) >= args.limit):
            break
    if args.limit:
        items = items[: args.limit]
    output_json({"ok": True, "count": len(items), "files": items})


def cmd_info(args):
    drive = get_drive_service(args.account)
    f = drive.files().get(
        fileId=args.id,
        fields="id, name, mimeType, parents, size, modifiedTime, webViewLink, webContentLink, owners(emailAddress), permissions(emailAddress, role)",
    ).execute()
    output_json({"ok": True, "file": f})


def cmd_share(args):
    drive = get_drive_service(args.account)
    body = {"type": "user", "role": args.role, "emailAddress": args.email}
    perm = drive.permissions().create(
        fileId=args.id,
        body=body,
        sendNotificationEmail=not args.no_notify,
        fields="id, role, emailAddress",
    ).execute()
    output_json({"ok": True, "permission": perm})


def cmd_rm(args):
    drive = get_drive_service(args.account)
    if args.permanent:
        drive.files().delete(fileId=args.id).execute()
        output_json({"ok": True, "deleted": args.id, "permanent": True})
    else:
        drive.files().update(fileId=args.id, body={"trashed": True}).execute()
        output_json({"ok": True, "trashed": args.id, "permanent": False})


def cmd_download_tree(args):
    """Recursively download a folder's contents to a local directory."""
    drive = get_drive_service(args.account)
    root_id = args.folder
    out_root = Path(args.output).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    summary = {"folders": 0, "files": 0, "bytes": 0, "errors": []}

    def list_children(folder_id):
        items, token = [], None
        while True:
            res = drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=1000, pageToken=token,
            ).execute()
            items.extend(res.get("files", []))
            token = res.get("nextPageToken")
            if not token:
                break
        return items

    def walk(folder_id, local_dir):
        local_dir.mkdir(parents=True, exist_ok=True)
        for f in list_children(folder_id):
            target = local_dir / f["name"]
            if f["mimeType"] == FOLDER_MIME:
                summary["folders"] += 1
                walk(f["id"], target)
                continue
            try:
                req = drive.files().get_media(fileId=f["id"])
                with open(target, "wb") as fh:
                    dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
                    done = False
                    while not done:
                        _, done = dl.next_chunk()
                summary["files"] += 1
                summary["bytes"] += int(f.get("size") or 0)
                if not args.quiet:
                    rel = target.relative_to(out_root)
                    sys.stderr.write(f"  ✓ {rel}\n")
            except Exception as e:
                summary["errors"].append({"path": str(target.relative_to(out_root)), "error": str(e)})
                sys.stderr.write(f"  ✗ {target.name}: {e}\n")

    walk(root_id, out_root)
    output_json({"ok": True, **summary, "output_root": str(out_root)})


def cmd_mv(args):
    """Move a file/folder by changing its parent. One API call per item."""
    drive = get_drive_service(args.account)
    # Need the current parents to remove them.
    current = drive.files().get(fileId=args.id, fields="parents, name").execute()
    old_parents = ",".join(current.get("parents", []))
    moved = drive.files().update(
        fileId=args.id,
        addParents=args.to_parent,
        removeParents=old_parents,
        fields="id, name, parents",
    ).execute()
    output_json({"ok": True, "id": moved["id"], "name": moved["name"], "parents": moved["parents"]})


def cmd_download(args):
    drive = get_drive_service(args.account)
    request = drive.files().get_media(fileId=args.id)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status and not args.quiet:
                pct = int(status.progress() * 100)
                sys.stderr.write(f"  download: {pct}%\n")
    output_json({"ok": True, "downloaded_to": str(out), "bytes": out.stat().st_size})


# ─── Wiring ────────────────────────────────────────────────────────────


def add_account(p):
    p.add_argument("--account", help="OAuth account email (defaults to first available token)")


def main():
    parser = argparse.ArgumentParser(prog="drive_skill.py", description="Google Drive — file & folder CRUD")
    subs = parser.add_subparsers(dest="command")

    p = subs.add_parser("login", help="Run OAuth flow / refresh token")
    add_account(p)
    p.set_defaults(func=cmd_login)

    p = subs.add_parser("accounts", help="List known token files")
    p.set_defaults(func=cmd_accounts)

    p = subs.add_parser("logout", help="Remove a stored token")
    add_account(p)
    p.set_defaults(func=cmd_logout)

    p = subs.add_parser("mkdir", help="Create a folder")
    p.add_argument("name")
    p.add_argument("--parent", help="Parent folder ID (defaults to My Drive root)")
    add_account(p)
    p.set_defaults(func=cmd_mkdir)

    p = subs.add_parser("upload", help="Upload a single file")
    p.add_argument("src", help="Local path to a file")
    p.add_argument("--parent", help="Drive folder ID")
    p.add_argument("--name", help="Override Drive filename")
    p.add_argument("--mime", help="Force MIME type")
    p.add_argument("--quiet", action="store_true")
    add_account(p)
    p.set_defaults(func=cmd_upload)

    p = subs.add_parser("upload-tree", help="Recursively upload a directory tree")
    p.add_argument("src", help="Local directory")
    p.add_argument("--parent", required=True, help="Drive folder ID to upload under")
    p.add_argument("--quiet", action="store_true")
    add_account(p)
    p.set_defaults(func=cmd_upload_tree)

    p = subs.add_parser("list", help="List children of a folder")
    p.add_argument("folder")
    p.add_argument("--limit", type=int)
    add_account(p)
    p.set_defaults(func=cmd_list)

    p = subs.add_parser("info", help="Get file/folder metadata")
    p.add_argument("id")
    add_account(p)
    p.set_defaults(func=cmd_info)

    p = subs.add_parser("share", help="Add a permission")
    p.add_argument("id")
    p.add_argument("--email", required=True)
    p.add_argument("--role", default="reader", choices=["reader", "writer", "commenter"])
    p.add_argument("--no-notify", action="store_true", help="Don't email the recipient")
    add_account(p)
    p.set_defaults(func=cmd_share)

    p = subs.add_parser("download-tree", help="Recursively download a folder")
    p.add_argument("folder", help="Drive folder ID")
    p.add_argument("--output", required=True, help="Local output directory")
    p.add_argument("--quiet", action="store_true")
    add_account(p)
    p.set_defaults(func=cmd_download_tree)

    p = subs.add_parser("mv", help="Move a file/folder to a new parent folder")
    p.add_argument("id")
    p.add_argument("--to-parent", required=True, help="New parent folder ID")
    add_account(p)
    p.set_defaults(func=cmd_mv)

    p = subs.add_parser("rm", help="Trash (default) or permanently delete a file/folder")
    p.add_argument("id")
    p.add_argument("--permanent", action="store_true")
    add_account(p)
    p.set_defaults(func=cmd_rm)

    p = subs.add_parser("download", help="Download a single file")
    p.add_argument("id")
    p.add_argument("--output", required=True)
    p.add_argument("--quiet", action="store_true")
    add_account(p)
    p.set_defaults(func=cmd_download)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
