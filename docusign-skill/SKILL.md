---
name: docusign-skill
description: Send / track / download DocuSign envelopes from the CLI. Anchor-string-based field auto-placement (no manual tab dragging). JWT Grant auth — one-time browser consent, then any number of programmatic sends. Use when the user wants to send a PDF for signature, check envelope status, list recent envelopes, or bulk-send to multiple recipients.
allowed-tools: Bash, Read
---

# DocuSign Skill

Programmatic DocuSign — send a PDF, anchor-place signature fields, get status, download completed copies. JWT Grant auth so the skill is server-to-server (no browser handoff per call).

## First-time setup (~10 minutes)

You only do this once per DocuSign account.

### 1. Get an Integration Key + RSA keypair

DocuSign Admin → **Apps and Keys**:
1. Click "Add App and Integration Key"
2. Name it something like "Claude Skill — server"
3. Copy the **Integration Key (Client ID)** — UUID format
4. Under "Service Integration", add an **RSA Keypair**:
   - Click "Generate RSA"
   - **Download the private key** immediately (you can't retrieve it later)
   - Save it as `~/.claude/skills/docusign-skill/private.key` (`chmod 600`)
5. Under "URI for Redirect", add: `https://www.docusign.com` (placeholder; only used during one-time consent)

### 2. Find your User ID + Account ID

Still in DocuSign Admin:
- **User ID**: Users → click your name → URL contains the user UUID. Or in My Preferences → API and Keys → User ID.
- **API Account ID**: Apps and Keys page top-right shows the API Account ID (a UUID; different from the short Account #).

### 3. Save credentials

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py setup
```

Interactive prompts. Defaults to production; pass `--env demo` for sandbox.

This writes `~/.claude/skills/docusign-skill/credentials.json`.

### 4. One-time consent

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py consent
```

Prints a URL. Open it in a browser logged in as the impersonation user. Click "Allow". Done. You'll be redirected somewhere harmless — ignore any error on the redirect page.

### 5. Verify

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py whoami
```

Should print user + accounts JSON.

## Commands

All output is JSON to stdout. Errors to stderr.

### Send a PDF for signature

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py send-pdf \
  path/to/agreement.pdf \
  --signer "Rohit Gupta <guptro@gmail.com>" \
  --subject "Epoch AI — Advisor Agreement" \
  --message "Hey Rohit, sending over the advisor agreement we discussed. Sign at your convenience."
```

**Default anchor tabs** (auto-placed if these strings appear anywhere in the PDF):
- `[Signature]` → signature field
- `[Printed Name]` → auto-filled full name
- `[Date]` → date signed

**Override with `--anchor-tabs`:**

```bash
--anchor-tabs '\sig1\=signature,\date1\=date,\name1\=fullname'
```

Types: `signature`, `date`, `fullname`, `initial`, `text`.

**Other flags:**
- `--draft` — create as draft (status `created`) instead of immediate send
- `--dry-run` — print what would be sent

### Get envelope status

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py status ENVELOPE_ID
```

Returns status (sent / delivered / signed / completed / declined / voided) + per-signer state with signed timestamps.

### List recent envelopes

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py list --days 30
python3 ~/.claude/skills/docusign-skill/docusign_skill.py list --status completed
```

### Download a completed envelope

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py download ENVELOPE_ID --output ./signed.pdf
```

Default downloads the combined PDF (all docs + certificate of completion).

### Bulk-send from JSON spec

```bash
python3 ~/.claude/skills/docusign-skill/docusign_skill.py bulk-send envelopes.json
```

Spec format:

```json
[
  {
    "pdf": "/path/to/Rohit-Advisor-Agreement.pdf",
    "signer": "Rohit Gupta <guptro@gmail.com>",
    "subject": "Epoch AI — Advisor Agreement",
    "message": "Hey Rohit, ..."
  },
  {
    "pdf": "/path/to/Farzam-Advisor-Agreement.pdf",
    "signer": "Farzam Kamel <farzam@nyxl.com>",
    "subject": "Epoch AI — Advisor Agreement",
    "message": "Hey Farzam, ..."
  }
]
```

Per-item optional: `anchor_tabs`, `draft`.

## Anchor-tab workflow

DocuSign's anchor-string field placement is the killer feature for this skill:

1. Embed unique placeholder strings in your PDF where fields should go (e.g. `[Signature]`, `[Printed Name]`, `[Date]`)
2. Send via this skill — fields auto-place wherever those strings appear
3. Strings are rendered as text in the PDF but DocuSign overlays the interactive field on top

**Best practice**: use bracket-style placeholders that are unlikely to appear elsewhere in the doc. The defaults (`[Signature]`, `[Printed Name]`, `[Date]`) match Epoch's existing advisor-agreement template.

If you're using a different template style, override per-send:

```bash
--anchor-tabs '\sig\=signature,\date\=date'
```

## Multi-account / accounts other than the JWT-impersonated user

V1 supports a single configured impersonation user. If the user has multiple DocuSign accounts (e.g. multiple companies), the active one is set via `account_id` in `credentials.json` — edit to switch. Future: `--account` flag for inline switching.

## Auth model

- **JWT Grant** — server-to-server. RSA-signed JWT exchanges for an access token good for 1 hour.
- Skill caches the access token in `~/.claude/skills/docusign-skill/tokens/`.
- One-time per integration-key + user: a browser-based consent grant via the `consent` command.
- No interactive OAuth dance after the initial consent.

## Files / where credentials live

- `credentials.json` — integration key, user ID, account ID, env (`prod`/`demo`)
- `private.key` — your RSA private key (chmod 600, gitignored)
- `tokens/token_<user>.json` — short-lived access token cache

## Security

- Private key is never sent — JWT is signed locally with it.
- Access tokens cache locally (file mode 600).
- All sensitive files are gitignored.
- Revoke access anytime in DocuSign Admin → Apps and Keys → revoke the key.

## Requirements

```bash
pip install docusign-esign cryptography PyJWT requests
```
