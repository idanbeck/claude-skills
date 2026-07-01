#!/usr/bin/env python3
"""docusign-skill — send/manage DocuSign envelopes from CLI.

Auth: JWT Grant (server-to-server). One-time browser consent per
integration-key+user, then any number of API calls authenticated by
JWT signed with your RSA private key.

Setup once: `docusign_skill.py setup`. Then commands like:
  send-pdf, status, list, download, bulk-send.

All output: JSON to stdout. Errors to stderr.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import jwt
import requests

# Optional imports — only required for some commands
try:
    from docusign_esign import (
        ApiClient,
        EnvelopesApi,
        EnvelopeDefinition,
        Document,
        Signer,
        SignHere,
        DateSigned,
        FullName,
        Text,
        Tabs,
        Recipients,
    )
    _SDK_OK = True
except ImportError:
    _SDK_OK = False

SKILL_DIR = Path.home() / ".claude" / "skills" / "docusign-skill"
CREDS_FILE = SKILL_DIR / "credentials.json"
TOKENS_DIR = SKILL_DIR / "tokens"
PRIVATE_KEY_FILE = SKILL_DIR / "private.key"

# DocuSign OAuth endpoints
DEMO_OAUTH = "https://account-d.docusign.com"
PROD_OAUTH = "https://account.docusign.com"

JWT_SCOPES = "signature impersonation"


# ───────────────────────── credentials & auth ─────────────────────────

def load_creds() -> dict:
    if not CREDS_FILE.exists():
        sys.stderr.write(
            f"error: no credentials at {CREDS_FILE}\n"
            f"run: docusign_skill.py setup\n"
        )
        sys.exit(2)
    with open(CREDS_FILE) as f:
        return json.load(f)


def save_creds(creds: dict) -> None:
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CREDS_FILE, 0o600)


def oauth_base(creds: dict) -> str:
    env = creds.get("env", "prod")
    return DEMO_OAUTH if env == "demo" else PROD_OAUTH


def token_path(creds: dict) -> Path:
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    user = creds.get("user_id", "default").replace("-", "_")
    return TOKENS_DIR / f"token_{user}.json"


def cached_token(creds: dict) -> str | None:
    p = token_path(creds)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        if data.get("expires_at", 0) > time.time() + 60:
            return data["access_token"]
    except Exception:
        return None
    return None


def cache_token(creds: dict, access_token: str, expires_in: int) -> None:
    p = token_path(creds)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump({
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }, f, indent=2)
    os.chmod(p, 0o600)


def get_access_token(creds: dict, force_refresh: bool = False) -> str:
    if not force_refresh:
        cached = cached_token(creds)
        if cached:
            return cached
    # Build & sign JWT
    if not PRIVATE_KEY_FILE.exists():
        sys.stderr.write(f"error: no private key at {PRIVATE_KEY_FILE}\n")
        sys.exit(2)
    with open(PRIVATE_KEY_FILE, "rb") as f:
        private_key = f.read()
    now = int(time.time())
    aud_host = oauth_base(creds).replace("https://", "")
    payload = {
        "iss": creds["integration_key"],
        "sub": creds["user_id"],
        "aud": aud_host,
        "iat": now,
        "exp": now + 3600,
        "scope": JWT_SCOPES,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    # Exchange JWT for access token
    r = requests.post(
        f"{oauth_base(creds)}/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": token,
        },
        timeout=30,
    )
    if r.status_code != 200:
        body = r.text
        if "consent_required" in body:
            sys.stderr.write(
                f"error: consent required. Run: docusign_skill.py consent\n"
                f"and follow the printed URL to grant access.\n"
            )
        else:
            sys.stderr.write(f"error: JWT exchange failed ({r.status_code}): {body}\n")
        sys.exit(3)
    data = r.json()
    cache_token(creds, data["access_token"], data.get("expires_in", 3600))
    return data["access_token"]


def get_user_info(creds: dict, access_token: str) -> dict:
    """Fetch user info incl. base_uri for the account."""
    r = requests.get(
        f"{oauth_base(creds)}/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_api_client(creds: dict) -> tuple["ApiClient", str, str]:
    """Return an authenticated ApiClient + account_id + base_uri."""
    if not _SDK_OK:
        sys.stderr.write("error: docusign-esign not installed\n")
        sys.exit(2)
    access_token = get_access_token(creds)
    info = get_user_info(creds, access_token)
    # Find the requested account
    target_acct = creds.get("account_id")
    chosen = None
    for acct in info.get("accounts", []):
        if acct["account_id"] == target_acct:
            chosen = acct
            break
    if not chosen and info.get("accounts"):
        chosen = info["accounts"][0]
    if not chosen:
        sys.stderr.write("error: no DocuSign accounts found for this user\n")
        sys.exit(3)
    base_uri = chosen["base_uri"] + "/restapi"
    client = ApiClient()
    client.host = base_uri
    client.set_default_header("Authorization", f"Bearer {access_token}")
    return client, chosen["account_id"], chosen["base_uri"]


# ───────────────────────── commands ─────────────────────────

def cmd_setup(args):
    """Interactive setup: writes credentials.json and reminds about key + consent."""
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"docusign-skill setup → {CREDS_FILE}")
    print()
    print("You'll need from DocuSign Admin → Apps and Keys:")
    print("  • Integration Key (a UUID)")
    print("  • API Account ID (UUID for the account you want to send from)")
    print("  • User ID — the User ID (UUID) of whoever JWT will impersonate")
    print("    (typically your own user; visible in Users → click your name)")
    print("  • An RSA keypair — generate in the same Apps-and-Keys page,")
    print("    download the private key and save to:")
    print(f"      {PRIVATE_KEY_FILE}")
    print()
    integration_key = args.integration_key or input("Integration Key: ").strip()
    user_id = args.user_id or input("User ID: ").strip()
    account_id = args.account_id or input("Account ID: ").strip()
    env = args.env or input("Env [prod/demo] (default prod): ").strip() or "prod"
    creds = {
        "integration_key": integration_key,
        "user_id": user_id,
        "account_id": account_id,
        "env": env,
    }
    save_creds(creds)
    print()
    print(json.dumps({
        "status": "credentials_saved",
        "path": str(CREDS_FILE),
        "env": env,
        "next_steps": [
            f"Place RSA private key at {PRIVATE_KEY_FILE} (chmod 600)",
            "Run: docusign_skill.py consent  (one-time per integration key + user)",
            "Then: docusign_skill.py whoami  (to confirm auth works)",
        ],
    }, indent=2))


def cmd_consent(args):
    """Print the consent URL the user visits once to grant JWT access."""
    creds = load_creds()
    params = {
        "response_type": "code",
        "scope": JWT_SCOPES.replace(" ", "%20"),
        "client_id": creds["integration_key"],
        "redirect_uri": args.redirect_uri or "https://www.docusign.com",
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{oauth_base(creds)}/oauth/auth?{qs}"
    print(json.dumps({
        "consent_url": url,
        "instructions": [
            "1. Open the URL in a browser logged in as the impersonation user",
            "2. Click 'Allow' to grant the integration the requested scopes",
            "3. You'll redirect to redirect_uri — that's expected, ignore any error",
            "4. After consent, any API call from this skill will work",
        ],
    }, indent=2))


def cmd_whoami(args):
    """Verify auth + print user/account info."""
    creds = load_creds()
    access_token = get_access_token(creds)
    info = get_user_info(creds, access_token)
    print(json.dumps(info, indent=2, default=str))


def cmd_send_pdf(args):
    """Send a PDF as a single-recipient envelope.

    Anchor tabs: signature/date/name fields auto-place wherever the listed
    anchor strings appear in the PDF. Default anchors:
      [Signature]    → signature tab (required)
      [Printed Name] → full-name auto-fill
      [Date]         → date-signed auto-fill

    Override with --anchor-tabs key1=type1,key2=type2 (types: signature,
    date, fullname, initial, text).
    """
    creds = load_creds()
    client, account_id, _ = get_api_client(creds)
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        sys.stderr.write(f"error: PDF not found: {pdf_path}\n")
        sys.exit(2)
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode()

    # Parse signer "Name <email>"
    signer_name, signer_email = _parse_recipient(args.signer)

    # Default anchors
    anchors = {
        "[Signature]": "signature",
        "[Printed Name]": "fullname",
        "[Date]": "date",
    }
    # Override
    if args.anchor_tabs:
        anchors = {}
        for pair in args.anchor_tabs.split(","):
            k, _, v = pair.partition("=")
            anchors[k.strip()] = v.strip().lower()

    # Build tab definitions
    sign_here_tabs = []
    date_tabs = []
    name_tabs = []
    text_tabs = []
    initial_tabs = []
    for anchor, kind in anchors.items():
        common = dict(anchor_string=anchor, anchor_units="pixels", anchor_y_offset="0", anchor_x_offset="0")
        if kind == "signature":
            sign_here_tabs.append(SignHere(**common))
        elif kind in ("date", "datesigned"):
            date_tabs.append(DateSigned(**common))
        elif kind in ("fullname", "name"):
            name_tabs.append(FullName(**common))
        elif kind == "initial":
            initial_tabs.append(SignHere(**common, optional=False))
        elif kind == "text":
            text_tabs.append(Text(**common))
    if not sign_here_tabs:
        sys.stderr.write(
            "warn: no signature anchor specified; envelope will be unsignable.\n"
            "use --anchor-tabs 'YOUR_ANCHOR=signature' to fix.\n"
        )

    tabs = Tabs(
        sign_here_tabs=sign_here_tabs or None,
        date_signed_tabs=date_tabs or None,
        full_name_tabs=name_tabs or None,
        text_tabs=text_tabs or None,
    )
    signer = Signer(
        email=signer_email,
        name=signer_name,
        recipient_id="1",
        routing_order="1",
        tabs=tabs,
    )

    document = Document(
        document_base64=pdf_b64,
        name=pdf_path.name,
        file_extension="pdf",
        document_id="1",
    )

    envelope_definition = EnvelopeDefinition(
        email_subject=args.subject or f"Please sign: {pdf_path.stem}",
        email_blurb=args.message or "Please review and sign at your convenience.",
        documents=[document],
        recipients=Recipients(signers=[signer]),
        status="sent" if not args.draft else "created",
    )

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "would_send": {
                "pdf": str(pdf_path),
                "signer": f"{signer_name} <{signer_email}>",
                "subject": envelope_definition.email_subject,
                "anchors": anchors,
                "status_target": envelope_definition.status,
            },
        }, indent=2))
        return

    envelopes_api = EnvelopesApi(client)
    result = envelopes_api.create_envelope(account_id, envelope_definition=envelope_definition)
    print(json.dumps({
        "status": "sent" if result.status == "sent" else result.status,
        "envelope_id": result.envelope_id,
        "uri": result.uri,
        "signer": f"{signer_name} <{signer_email}>",
    }, indent=2))


def cmd_status(args):
    """Get envelope status."""
    creds = load_creds()
    client, account_id, _ = get_api_client(creds)
    envelopes_api = EnvelopesApi(client)
    env = envelopes_api.get_envelope(account_id, envelope_id=args.envelope_id)
    recipients = envelopes_api.list_recipients(account_id, envelope_id=args.envelope_id)
    sig_states = []
    for s in (recipients.signers or []):
        sig_states.append({
            "name": s.name,
            "email": s.email,
            "status": s.status,
            "signed_date": str(s.signed_date_time) if s.signed_date_time else None,
        })
    print(json.dumps({
        "envelope_id": env.envelope_id,
        "status": env.status,
        "created": str(env.created_date_time),
        "sent": str(env.sent_date_time) if env.sent_date_time else None,
        "completed": str(env.completed_date_time) if env.completed_date_time else None,
        "subject": env.email_subject,
        "signers": sig_states,
    }, indent=2, default=str))


def cmd_list(args):
    """List recent envelopes (default: last 30 days, any status)."""
    creds = load_creds()
    client, account_id, _ = get_api_client(creds)
    envelopes_api = EnvelopesApi(client)
    from_date = (datetime.utcnow() - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kwargs = {"from_date": from_date}
    if args.status:
        kwargs["status"] = args.status
    result = envelopes_api.list_status_changes(account_id, **kwargs)
    envs = []
    for e in (result.envelopes or []):
        envs.append({
            "envelope_id": e.envelope_id,
            "status": e.status,
            "subject": e.email_subject,
            "sent": str(e.sent_date_time) if e.sent_date_time else None,
            "completed": str(e.completed_date_time) if e.completed_date_time else None,
        })
    print(json.dumps({"count": len(envs), "envelopes": envs}, indent=2, default=str))


def cmd_download(args):
    """Download an envelope's documents (combined PDF)."""
    creds = load_creds()
    client, account_id, _ = get_api_client(creds)
    envelopes_api = EnvelopesApi(client)
    out = Path(args.output or f"{args.envelope_id}.pdf").expanduser().resolve()
    # Download combined PDF (document_id="combined") OR specific docs
    doc_id = args.document_id or "combined"
    body = envelopes_api.get_document(account_id, doc_id, args.envelope_id)
    # SDK returns the local path of a tmp file
    if isinstance(body, str) and Path(body).exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        os.rename(body, out)
    else:
        with open(out, "wb") as f:
            f.write(body)
    print(json.dumps({"saved": str(out), "envelope_id": args.envelope_id}, indent=2))


def cmd_bulk_send(args):
    """Send multiple envelopes from a JSON spec file.

    Spec format:
      [
        {
          "pdf": "path/to/file.pdf",
          "signer": "Name <email@example.com>",
          "subject": "...",
          "message": "...",
          "anchor_tabs": "[Signature]=signature,[Printed Name]=fullname"
        },
        ...
      ]
    """
    creds = load_creds()
    with open(args.spec) as f:
        spec = json.load(f)
    if not isinstance(spec, list):
        sys.stderr.write("error: spec must be a JSON list\n")
        sys.exit(2)
    client, account_id, _ = get_api_client(creds)
    results = []
    for i, item in enumerate(spec):
        # Build a fake args object and call cmd_send_pdf inline
        class _A: pass
        a = _A()
        a.pdf = item["pdf"]
        a.signer = item["signer"]
        a.subject = item.get("subject")
        a.message = item.get("message")
        a.anchor_tabs = item.get("anchor_tabs")
        a.draft = item.get("draft", False)
        a.dry_run = args.dry_run
        try:
            # Capture stdout from cmd_send_pdf into result
            from io import StringIO
            buf = StringIO()
            saved = sys.stdout
            sys.stdout = buf
            try:
                cmd_send_pdf(a)
            finally:
                sys.stdout = saved
            results.append({"index": i, "ok": True, "result": json.loads(buf.getvalue())})
        except SystemExit as e:
            results.append({"index": i, "ok": False, "error": f"exit({e.code})"})
        except Exception as e:
            results.append({"index": i, "ok": False, "error": str(e)})
    print(json.dumps({"count": len(results), "results": results}, indent=2))


# ───────────────────────── helpers ─────────────────────────

def _parse_recipient(spec: str) -> tuple[str, str]:
    """Parse 'Name <email>' or 'email' into (name, email)."""
    spec = spec.strip()
    if "<" in spec and ">" in spec:
        name = spec.split("<")[0].strip()
        email = spec.split("<")[1].split(">")[0].strip()
        return name, email
    return spec, spec  # email-only


# ───────────────────────── CLI ─────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="docusign_skill.py", description="DocuSign envelope CLI")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("setup", help="Save integration-key / account / user IDs")
    p.add_argument("--integration-key")
    p.add_argument("--user-id")
    p.add_argument("--account-id")
    p.add_argument("--env", choices=["prod", "demo"])
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("consent", help="Print the one-time browser consent URL")
    p.add_argument("--redirect-uri", help="Override default redirect URI")
    p.set_defaults(func=cmd_consent)

    p = sub.add_parser("whoami", help="Verify auth + print user/account info")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("send-pdf", help="Send a single PDF for signature")
    p.add_argument("pdf", help="Path to PDF")
    p.add_argument("--signer", required=True, help='"Name <email>" or just email')
    p.add_argument("--subject", help="Email subject")
    p.add_argument("--message", help="Email message body")
    p.add_argument("--anchor-tabs", help="Comma-separated anchor=type pairs. Default: '[Signature]=signature,[Printed Name]=fullname,[Date]=date'")
    p.add_argument("--draft", action="store_true", help="Create as draft (status=created) instead of sending immediately")
    p.add_argument("--dry-run", action="store_true", help="Print what would be sent, don't send")
    p.set_defaults(func=cmd_send_pdf)

    p = sub.add_parser("status", help="Get envelope status")
    p.add_argument("envelope_id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("list", help="List recent envelopes")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--status", help="Filter by status (sent, delivered, signed, completed, declined, voided)")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("download", help="Download envelope document(s)")
    p.add_argument("envelope_id")
    p.add_argument("--output", help="Output PDF path (default: ENVELOPE_ID.pdf)")
    p.add_argument("--document-id", help="Specific document id (default: 'combined')")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("bulk-send", help="Send multiple envelopes from a JSON spec")
    p.add_argument("spec", help="Path to JSON spec file")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_bulk_send)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
