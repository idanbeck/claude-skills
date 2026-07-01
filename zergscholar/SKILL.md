---
name: zergscholar
description: Bridge between a local Obsidian vault and the zergscholar web app (papers, drafts, knowledge). Use when the user asks to push a local paper note to zergscholar, pull a paper down into the vault, list workspace contents, or check linkage status across the vault.
allowed-tools: Bash, Read, Write
---

# ZergScholar — Local ↔ Web Bridge

Sync papers between an Obsidian vault and the
[zergscholar](https://zergscholar.fly.dev) web app via a Bearer-
token-authenticated REST surface. The vault stays the source of
truth for notes / drafts; zergscholar holds collaborator state and
canonical paper metadata. Linkage is tracked via a `zergscholar_id`
field on each linked note's frontmatter.

## First-Time Setup (~2 minutes)

1. Sign in to your zergscholar deployment (default
   `https://zergscholar.fly.dev`) and go to **Settings → API Tokens**.
2. Mint a token with **`write` scope** for the workspace you want to
   sync against (the personal library is the typical default). Copy
   the `zsk_...` value — it's shown once.
3. Run setup:

   ```bash
   python3 ~/.claude/skills/zergscholar/zergscholar_skill.py setup
   ```

   The walkthrough prompts for base URL, the token you just minted,
   the default workspace, and the Obsidian vault path. Writes
   `~/.claude/skills/zergscholar/config.json`.

The default vault path is
`/Users/idanbeck/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck`
to match the layout documented in that vault's `AGENTS.md` (`Reading/
Research/`, `Reading/pdfs/`, `Writing/`, `Research/`).

## Multi-Account Convention

`config.json` mirrors `notion-skill`:

```json
{
  "default_account": "personal",
  "vault_path": "/Users/.../idanbeck",
  "accounts": {
    "personal": { "base_url": "...", "token": "zsk_...", "default_organization_id": "uuid" },
    "epoch":    { "base_url": "...", "token": "zsk_...", "default_organization_id": "uuid" }
  }
}
```

Every command takes `-a ACCOUNT` to override the default. Mint one
token per account (workspace) you want to bridge.

## Commands

All commands print **JSON to stdout** and exit with non-zero on
error. Run with `python3 ~/.claude/skills/zergscholar/zergscholar_skill.py <subcommand>`.

### `whoami [-a ACCOUNT]`

Token info + accessible workspaces. Useful as a connectivity check.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py whoami
```

### `list-papers [-a] [--workspace ID] [--linked|--unlinked]`

Paper list for a workspace, joined with the vault. Each row tells
you whether a local note exists and where.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py list-papers
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py list-papers --unlinked
```

Output rows include: `id`, `title`, `year`, `doi`, `arxiv_id`,
`status`, `linked_local`, `local_path`.

### `push-paper FILE.md [-a] [--workspace ID] [--force] [--pdf PATH]`

Push a vault note to zergscholar. Reads the note's frontmatter
(`year`, `arxiv` / `arxiv_id`, `doi`, `authors` if present), parses
the H1 as the title, and uses the `## Abstract` or `## Technical
Synopsis` section as the abstract. If a PDF named after the title
sits in `Reading/pdfs/`, it's uploaded automatically; pass `--pdf
PATH` to override the discovery (useful when the H1 expands what
the filename abbreviated — e.g. "Large Language Model" vs "LLM").

The skill marks the note as linked (writes `zergscholar_id` and
`zergscholar_pushed_at` to frontmatter) **only when there's nothing
left to retry**. If a local PDF was found but the upload failed, the
note stays un-linked so the next push re-enters the dedup path and
retries the upload instead of short-circuiting on `already_linked`.

The response includes a `linked: bool` field that reflects this:
`true` means the frontmatter was updated; `false` means metadata
was created server-side but the note wasn't linked (typically due
to a PDF upload failure that should be retried).

Re-running an already-linked push skips with `already_linked` unless
you pass `--force`. With the post-2026-05 skill, **`--force` never
creates a duplicate row**: when there's an arXiv/DOI dedup hit, the
skill re-uses the existing paper and re-runs enrichment + PDF upload
against it. If you previously had a "linked but no PDF on server"
state, just `push-paper --force` and the PDF gets attached without
spawning a new paper id.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py push-paper \
  "$VAULT/Reading/Research/A Comprehensive Survey on Graph Neural Networks.md"

# Explicit PDF path when the filename diverges from the H1:
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py push-paper \
  "$VAULT/Reading/Research/<note>.md" \
  --pdf "$VAULT/Reading/pdfs/<abbreviated-filename>.pdf"
```

### `pull-paper ID_OR_TITLE [-a] [-o PATH] [--no-knowledge]`

Fetch a paper from zergscholar and write a vault note. Accepts
either the paper's UUID or a title (fuzzy match within the default
workspace). Writes to `Reading/Research/<title>.md` matching the
existing template (frontmatter + H1 + standard H2 sections).

**Pulls knowledge entries by default** — workspace-side AI summaries
/ key findings / methodology / insights produced via the in-app
research assistant or by collaborators are woven into the matching
H2 sections. Pass `--no-knowledge` to skip (faster).

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py pull-paper \
  "Attention Is All You Need"
```

### `status [-a]`

Vault scan + remote count summary. Reports total notes, linked vs
unlinked, plus the remote paper count for the default workspace.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py status
```

### `setup`

Interactive — see "First-Time Setup" above.

## Workflows

### "Publish this paper to my workspace"

```bash
# I just finished reading and noting this one — push it
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py push-paper \
  "$VAULT/Reading/Research/<title>.md"
# → paper appears in /app/library; PDF auto-attached if found
```

### "Bring this paper from the team library into my vault to read"

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py pull-paper \
  "<title or uuid>" -a epoch
# → new note in Reading/Research/, ready for "My Thoughts" + notes
```

### "What hasn't been pushed yet?"

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py list-papers --unlinked
# → JSON list of remote papers without local notes; conversely,
#   walk Reading/Research/ for notes without zergscholar_id
```

## Output Format

All commands emit JSON to stdout. `push-paper` response shape:

```json
{
  "ok": true,
  "paper_id": "uuid",
  "title": "...",
  "workspace_id": "uuid",
  "pdf_uploaded": true,
  "pdf_path": "/Users/.../Reading/pdfs/<filename>.pdf",
  "pdf_result": {
    "paperId": "uuid",
    "filename": "<filename>.pdf",
    "bytes": 716869,
    "has_pdf": true,
    "extractedTextChars": 0,
    "pageCount": null
  },
  "linked": true,
  "local_path": "/Users/.../<note>.md"
}
```

Field notes:

- `linked` — whether `zergscholar_id` was written to the note's frontmatter. `false` means metadata was created/found server-side but a retry-worthy step failed (typically PDF upload). Re-running `push-paper` will pick up where it left off via arXiv-id dedup.
- `pdf_result.has_pdf` — server-confirmed boolean that the paper now has a PDF attached.
- `pdf_result.extractedTextChars` / `pageCount` — populated asynchronously by the server-side text-extraction pass. `0` / `null` on a fresh upload means extraction is queued; re-fetch the paper later or trigger explicitly with `extract-text`.

Errors are also JSON:

```json
{
  "error": "api_error",
  "message": "Token requires 'write' token scope; your token has [read].",
  "status": 403
}
```

Exit code `0` for success, `1` for general errors, `2` for setup /
configuration problems.

## Frontmatter Conventions

The skill reads these fields when **pushing** a paper:

| Field | Use |
|---|---|
| `# H1` | paper title (required) |
| `year` | publication year |
| `arxiv` / `arxiv_id` | arXiv ID |
| `doi` | DOI |
| `authors` | comma-separated list, `["A", "B"]` style accepted |
| `## Abstract` or `## Technical Synopsis` | paper abstract |

The skill writes these fields back after a successful push:

| Field | Meaning |
|---|---|
| `zergscholar_id` | UUID of the remote paper |
| `zergscholar_pushed_at` | ISO timestamp of last push |

## Security Notes

- `config.json` contains a token that's equivalent to a workspace-
  scoped session. Treat it like a credential — keep it on disk,
  don't commit it.
- Tokens are workspace-scoped: a `write` token for workspace A can't
  read or write workspace B. Mint separate tokens per account in
  config.
- Revoke / regenerate tokens at `<base_url>/app/settings` → API
  Tokens at any time. The skill will get a clear `401` and you can
  re-run `setup`.

### `push-knowledge FILE.md [-a] [--paper-id ID]`

Extract H2 sections of an already-linked paper note and POST them as
typed knowledge entries. Mapping:

| Heading | `entry_type` |
|---|---|
| Technical Synopsis / Summary / Abstract | `summary` |
| Key Findings / Findings | `key_finding` |
| Methodology / Methods | `methodology` |
| My Thoughts / Thoughts / Insights | `insight` |
| Connections / Related Work | `connection` |
| Definitions / Glossary | `definition` |

Skips empty / placeholder sections (`*To be filled during review*`).
Client-side dedup against existing entries on the paper — re-running
won't double-post.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py push-knowledge \
  "$VAULT/Reading/Research/<title>.md"
```

### `push-draft FILE.md [-a] [--force]`

Push a `Writing/` note as a zergscholar `documents` row. Reads the H1
as title, body becomes the doc content, `format` from frontmatter
(defaults to `markdown`; `latex` / `typst` honored). If the note
already has `zergscholar_id`, update-in-place; pass `--force` to
create a brand-new doc instead.

### `pull-draft DOC_ID [-a] [-o PATH]`

Fetch a remote document into `Writing/<title>.md` with frontmatter
linking and `format` preserved.

### `pull-all [-a] [--workspace ID] [--force]`

Bulk-pull every paper from the workspace into `Reading/Research/`.
Skips already-linked papers unless `--force`. Useful for
bootstrapping a fresh vault from an existing workspace.

### `push-folder DIR [-a] [--workspace ID] [--dry-run] [--force]`

Recursively walk a vault folder, push every `.md` paper note that
isn't already linked. `--dry-run` reports the candidate set without
touching the server. Idempotent — re-runs pick up only new notes.
DOI/arXiv pre-flight on every push so duplicates don't sneak in.

```bash
# What would happen?
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py push-folder \
  "$VAULT/Reading/Research" --dry-run
# Do it
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py push-folder \
  "$VAULT/Reading/Research"
```

### `push-annotation FILE.md "..." [--page N] [--highlight TEXT]`

Post an annotation against a linked paper. The note's
`zergscholar_id` provides the paper id; pass `--paper-id` to
override.

## Dedup behaviour (push-paper)

`push-paper` finds an existing paper to attach to in priority order:

1. **arXiv-id / DOI lookup** via `/api/external/find-paper` when the
   note's frontmatter has `arxiv:` or `doi:`. This is the primary
   path and catches most workspace-side duplicates.
2. **Existing `zergscholar_id` on the note** — used as a recovery
   fallback when a previous push linked the note but the dedup
   key isn't (or no longer is) on file with the server. The skill
   calls `get_paper(id)` and re-attaches if the paper still exists.

If both probes return nothing, a new paper row is created.

**`--force` does NOT create duplicate rows.** It only skips the
`already_linked` short-circuit so the post-dedup work (enrichment +
PDF upload) re-runs against the existing row. This is the recovery
tool for any "linked, but the upload didn't finish" state.

## Bulk maintenance commands

These walk the workspace server-side and reconcile gaps. All take
`--workspace ID` (override default), `--limit N` (stop after N
papers), and `--dry-run` (report candidates without writing).

### `enrich-all [-a]`

Walk every vault note with `zergscholar_id` and re-push tags, body
content, and authors to the existing remote paper. Useful for
backfilling fields that an earlier `push-paper` version didn't
carry (early bulk-pushes only sent title + year + arxiv id).

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py enrich-all
```

### `enrich-metadata [-a] [--workspace ID] [--limit N] [--dry-run]`

For every paper in the workspace that has an `arxiv_id` but is
missing authors or abstract, fetch from the arXiv ATOM API
(batched 100 per request, 3s between batches) and call
`enrich-paper` server-side. Polite to arXiv; safe to re-run.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py enrich-metadata --dry-run
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py enrich-metadata --limit 50
```

### `backfill-pdfs [-a] [--workspace ID] [--limit N] [--dry-run]`

For every paper that has an `arxiv_id` but no PDF attached, fetch
`https://arxiv.org/pdf/<arxiv_id>.pdf` and upload it via the
existing upload-pdf endpoint. Polite at 3.5s between fetches per
arXiv's unauthenticated-bulk guidance. The natural way to recover
from "metadata pushed but PDF never made it" state across many
papers without manually re-pushing each note.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py backfill-pdfs --dry-run
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py backfill-pdfs --limit 20
```

### `extract-text [-a] [--workspace ID] [--limit N] [--dry-run]`

For every paper with a PDF and no extracted text, hit the server's
per-paper extract-text endpoint. The server runs the extraction
asynchronously after `upload-pdf`, but if it stalls or you've
backfilled PDFs in bulk, this kicks the queue.

```bash
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py extract-text --dry-run
python3 ~/.claude/skills/zergscholar/zergscholar_skill.py extract-text --limit 100
```

### `pull-drafts [-a] [--workspace ID] [--force]`

Bulk-pull every document from the workspace into `Writing/`.
Mirrors `pull-all` for documents instead of papers. Skips
already-linked drafts unless `--force`.
