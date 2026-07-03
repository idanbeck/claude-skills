---
name: substack-skill
description: Create, edit, publish, schedule, and manage Substack posts. Use when the user asks to draft or publish a Substack post, list/edit their Substack drafts, schedule a post, or upload images to Substack. Supports multiple accounts/publications.
allowed-tools: Bash, Read
---

# Substack Skill - Create, Edit, Publish, and Manage Posts

Manage Substack publications from the CLI via Substack's internal JSON API using
your browser session cookie. Write posts in plain **markdown** — the skill
converts to Substack's ProseMirror editor format (and back when fetching drafts).

## CRITICAL: Publishing Confirmation Required

**Before running `publish` or `schedule`, Claude MUST get explicit user confirmation:**

1. Show the user the draft title + a summary of the body.
2. State clearly whether it will **email all subscribers** (`--send-email`) or
   publish to web only (`--no-email`). The email blast cannot be unsent.
3. Wait for an explicit yes.

Always confirm first. No exceptions. `create-draft` / `update-draft` are safe
(drafts are private) and do not require confirmation.

## First-Time Setup (One-Time)

1. Log in to Substack in your browser.
2. Open DevTools → Application → Cookies → `https://substack.com` and copy the
   value of the **`substack.sid`** cookie (long string starting with `s%3A`).
3. Run setup:

```bash
python3 ~/.claude/skills/substack-skill/substack_skill.py setup
```

It prompts for an account label, your publication URL (e.g.
`https://yourname.substack.com` or your custom domain), and the cookie, then
verifies auth and saves `config.json`. Sessions last ~3 months; when calls start
returning `auth_failed`, grab a fresh cookie and re-run setup with the same label.

## Multi-Account Convention

`config.json` (gitignored) mirrors notion-skill/zergscholar:

```json
{
  "default_account": "personal",
  "accounts": {
    "personal": {
      "publication_url": "https://yourname.substack.com",
      "cookie": "substack.sid=s%3A...",
      "user_id": 123456,
      "user_name": "Your Name"
    },
    "company": { "publication_url": "https://blog.company.com", "cookie": "..." }
  }
}
```

Every command takes `-a ACCOUNT` to override the default.

## Commands

### Account

```bash
# Verify auth; show user, publications, subscriber count
python3 ~/.claude/skills/substack-skill/substack_skill.py whoami [-a ACCOUNT]

# List sections (for --section-id)
python3 ~/.claude/skills/substack-skill/substack_skill.py sections [-a ACCOUNT]
```

### Reading

```bash
# List posts: --status published (default) | draft | scheduled
python3 ~/.claude/skills/substack-skill/substack_skill.py list-posts --status draft --limit 15

# Fetch a draft with its body converted back to markdown (--raw for full JSON)
python3 ~/.claude/skills/substack-skill/substack_skill.py get-draft DRAFT_ID

# Fetch a published post by slug
python3 ~/.claude/skills/substack-skill/substack_skill.py get-post my-post-slug
```

### Writing

```bash
# Create a draft from a markdown file (local images auto-upload to Substack CDN)
python3 ~/.claude/skills/substack-skill/substack_skill.py create-draft \
  --title "Post Title" --subtitle "Optional subtitle" \
  --body-md ~/path/to/post.md [--audience everyone|only_paid|only_free|founding] [--section-id N]

# Or with inline markdown
python3 ~/.claude/skills/substack-skill/substack_skill.py create-draft \
  --title "Quick note" --body-text "Some **markdown** here."

# Update a draft (any subset of fields; body replace is full-overwrite)
python3 ~/.claude/skills/substack-skill/substack_skill.py update-draft DRAFT_ID \
  [--title ...] [--subtitle ...] [--body-md file.md] [--audience ...]

# Upload an image by itself, get the CDN URL
python3 ~/.claude/skills/substack-skill/substack_skill.py upload-image ~/pic.png
```

### Publishing (confirm with user first)

```bash
# Publish AND email every subscriber (irreversible email blast)
python3 ~/.claude/skills/substack-skill/substack_skill.py publish DRAFT_ID --send-email [--share]

# Publish to web only, no email
python3 ~/.claude/skills/substack-skill/substack_skill.py publish DRAFT_ID --no-email

# Schedule / unschedule
python3 ~/.claude/skills/substack-skill/substack_skill.py schedule DRAFT_ID --at "2026-07-08T09:00:00-07:00"
python3 ~/.claude/skills/substack-skill/substack_skill.py unschedule DRAFT_ID

# Delete a draft (requires --force)
python3 ~/.claude/skills/substack-skill/substack_skill.py delete-draft DRAFT_ID --force
```

## Examples

```bash
# Draft a post from a vault thought piece, review it, then publish with email
python3 ~/.claude/skills/substack-skill/substack_skill.py create-draft \
  --title "Nobody Reads Code Anymore" --body-md "$VAULT/Writing/nobody-reads-code.md"
python3 ~/.claude/skills/substack-skill/substack_skill.py get-draft 161803398
# ...user confirms...
python3 ~/.claude/skills/substack-skill/substack_skill.py publish 161803398 --send-email
```

## Markdown Support

Headings, paragraphs, **bold**, *italic*, `code`, ~~strike~~, links,
bullet/ordered lists (one nesting level), blockquotes, fenced code blocks
(with language), horizontal rules, and images. Standalone-line images become
Substack image blocks (local file paths are uploaded automatically); inline
images degrade to links. Not supported by Substack's format: tables, LaTeX —
multi-paragraph list items are not supported by this converter.

## Output

All commands print JSON to stdout and exit non-zero on error
(`{"error": code, "message": ...}`; exit 2 = missing config).

## Requirements

- Python 3.9+ (stdlib only — no pip installs)

## API Limitations

- **Unofficial API.** Substack has no official post-management API; this uses the
  same internal endpoints as their web editor (as does the `python-substack`
  ecosystem). Endpoints can change without notice; the official "Developer API"
  is profile-lookup only and not a substitute.
- Session cookies last ~3 months, then re-run `setup`.
- `update-draft --body-md` replaces the whole body: editor-only widgets
  (buttons, polls, paywalls) in the existing draft are destroyed.
- No documented rate limits; the skill retries 429/5xx with backoff. Keep bulk
  operations gentle.

## Security Notes

- **Publishing confirmation required** — Claude must always confirm with the user
  before `publish` or `schedule` (the `--send-email` blast is irreversible).
- The session cookie in `config.json` is equivalent to your logged-in browser
  session. It is stored locally and gitignored (blanket `**/config.json` rule).
- Revoke by logging out of that browser session or changing your password.
