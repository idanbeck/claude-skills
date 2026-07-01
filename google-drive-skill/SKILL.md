---
name: google-drive-skill
description: Move arbitrary bytes (bundles, archives, datasets, photo dumps) into and out of Google Drive folders. Folder + file CRUD; complements google-docs-skill which targets the Docs API specifically.
allowed-tools: Bash
---

# Google Drive Skill

For when the user asks to upload/download files to Google Drive, create or share folders, list folder contents, or move binary artifacts (zips, tarballs, source bundles, photo dumps) into a Drive workspace.

This is a **separate concern from `google-docs-skill`** — that one is Docs-API-specific (create/read/update Google Docs, export to PDF/DOCX). Use `google-drive-skill` for raw bytes; use `google-docs-skill` for Docs-flavored content.

## Setup

Reuses the OAuth client from `google-docs-skill` (Drive scope is already enabled there). If you've already logged into the Docs skill with the account you need, this skill picks up the token automatically — no separate login.

If a fresh login is needed:

```bash
python3 ~/.claude/skills/google-drive-skill/drive_skill.py login --account user@example.com
```

That triggers the standard browser-based OAuth flow.

## Commands

All output is JSON to stdout for easy piping.

### Account management

```bash
python3 ~/.claude/skills/google-drive-skill/drive_skill.py accounts
python3 ~/.claude/skills/google-drive-skill/drive_skill.py login [--account EMAIL]
python3 ~/.claude/skills/google-drive-skill/drive_skill.py logout [--account EMAIL]
```

### Folder + file CRUD

```bash
# Create a folder (in My Drive root by default; pass --parent for nested)
python3 ~/.claude/skills/google-drive-skill/drive_skill.py mkdir "Bundle 2026-05-01" --account user@example.com

# Upload a single file
python3 ~/.claude/skills/google-drive-skill/drive_skill.py upload ./big.tar.gz --parent FOLDER_ID --account user@example.com

# Recursively upload an entire directory tree (preserves structure, skips .DS_Store)
python3 ~/.claude/skills/google-drive-skill/drive_skill.py upload-tree ./original_data --parent FOLDER_ID --account user@example.com

# List a folder's children
python3 ~/.claude/skills/google-drive-skill/drive_skill.py list FOLDER_ID --account user@example.com

# Inspect a single file/folder
python3 ~/.claude/skills/google-drive-skill/drive_skill.py info FILE_OR_FOLDER_ID --account user@example.com

# Share with someone (default role: reader; --no-notify to skip the email)
python3 ~/.claude/skills/google-drive-skill/drive_skill.py share FILE_OR_FOLDER_ID --email someone@example.com --role reader --account user@example.com

# Trash (default) or permanently delete
python3 ~/.claude/skills/google-drive-skill/drive_skill.py rm FILE_OR_FOLDER_ID --account user@example.com
python3 ~/.claude/skills/google-drive-skill/drive_skill.py rm FILE_OR_FOLDER_ID --permanent --account user@example.com

# Download a single file
python3 ~/.claude/skills/google-drive-skill/drive_skill.py download FILE_ID --output ./local.tar.gz --account user@example.com
```

### Resumable uploads

`upload` and `upload-tree` use Drive's resumable upload protocol with 8 MiB chunks. Multi-GB transfers survive transient network blips. Progress prints to stderr (use `--quiet` to silence).

`upload-tree` is the right tool for "ship this whole directory to a Drive folder" — it walks recursively, creates each subfolder once (cached), and uploads files with their MIME type detected from the extension.

## Implementation notes

- Stores tokens at `~/.claude/skills/google-drive-skill/tokens/token_<email>.json`. Falls back to reading the docs-skill's tokens dir for accounts that have already logged in there. New logins from this skill land here.
- Reuses `~/.claude/skills/google-docs-skill/credentials.json` (the OAuth client). If you ever need to bring your own client JSON, drop one at `~/.claude/skills/google-drive-skill/credentials.json`.
- Drive scope: `https://www.googleapis.com/auth/drive` (full read/write). The docs-skill already requested this scope, so existing tokens have it.

## Where this fits

- **`google-docs-skill`** — Docs-API operations (create/read/update Docs, export, comments).
- **`google-drive-skill`** — bytes (this one).
- **`gmail-skill`** — Gmail OAuth + send/read.

The three share an OAuth client; tokens are interchangeable across skills as long as the account logged in at least once via any of them.
