#!/usr/bin/env python3
"""ZergScholar bridge — sync papers/drafts between a local Obsidian
vault and the zergscholar web app.

Six commands, JSON to stdout:
  setup                         interactive: write config.json
  whoami [-a ACCOUNT]           token info + accessible workspaces
  list-papers [-a] [--workspace] [--linked|--unlinked]
                                paper list, joined against vault
  push-paper FILE.md [-a] [--workspace ID]
                                push a vault note to zergscholar,
                                attach paired PDF if found, write
                                zergscholar_id back to frontmatter
  pull-paper ID_OR_TITLE [-a] [-o PATH]
                                fetch a remote paper, write a vault
                                note matching the existing template
  status [-a]                   vault scan: linked/unlinked counts

Auth lives in `config.json` next to this file (multi-account, mirrors
notion-skill). Mint tokens at <base_url>/app/settings → API Tokens.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

from lib.api import ZergScholarApi, Account, ApiError
from lib import obsidian, linker


CONFIG_PATH = SKILL_DIR / "config.json"


# ── config ────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        emit_error(
            "config_missing",
            f"No config.json at {CONFIG_PATH}. Run `setup` first.",
            exit_code=2
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_account(cfg: dict, account_name: str | None) -> tuple[str, Account]:
    name = account_name or cfg.get("default_account")
    if not name:
        emit_error("no_account", "No account selected and no default_account in config.")
    accounts = cfg.get("accounts", {})
    if name not in accounts:
        emit_error("unknown_account", f"Account '{name}' not in config.")
    a = accounts[name]
    return name, Account(
        base_url=a["base_url"],
        token=a["token"],
        default_organization_id=a.get("default_organization_id"),
    )


def vault_path(cfg: dict) -> str:
    p = cfg.get("vault_path")
    if not p:
        emit_error("no_vault", "config.vault_path not set.")
    if not os.path.isdir(p):
        emit_error("vault_missing", f"vault_path does not exist: {p}")
    return p


# ── note → push payload extractors ───────────────────────────────

# Frontmatter keys to skip when copying tags (these are bookkeeping
# tags from the Notion import, not actual subject classifications).
_TAG_BLACKLIST = {"reading", "research", "notion-import", "zergscholar-import"}


def _extract_tags(note) -> list[str]:
    raw = note.frontmatter.get("tags")
    if isinstance(raw, list):
        candidates = [str(t).strip() for t in raw if str(t).strip()]
    elif isinstance(raw, str):
        candidates = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        candidates = []
    return [t for t in candidates if t.lower() not in _TAG_BLACKLIST]


_UUID_RE = __import__("re").compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    __import__("re").IGNORECASE,
)


def _clean_author_names(names: list[str]) -> list[str]:
    """Drop UUID-shaped names (Notion-export garbage where the page's
    relation field exported as the linked page's UUID instead of a
    resolved person name) and obvious junk."""
    out: list[str] = []
    for n in names:
        s = (n or "").strip()
        if not s:
            continue
        if _UUID_RE.match(s):
            continue
        # Bare bracket/quote stragglers from un-parsed frontmatter
        s = s.strip("[]'\"")
        if not s or _UUID_RE.match(s):
            continue
        out.append(s)
    return out


def _extract_authors(note) -> list[str] | None:
    """Authors live in frontmatter (`authors:`) on a few notes, but
    most have them in the body as `**Authors:** A, B, C`. Try both.
    """
    raw = note.frontmatter.get("authors")
    if isinstance(raw, list):
        out = _clean_author_names([str(a) for a in raw])
        if out:
            return out
    elif isinstance(raw, str) and raw.strip():
        out = _clean_author_names([a for a in raw.split(",")])
        if out:
            return out

    # Body scan — look for a line like `**Authors:** A, B, C` or
    # `**Author:** A` near the top of the note.
    import re as _re
    m = _re.search(r"^\*\*Authors?\s*:\s*\*\*\s*(.+)$", note.body, _re.MULTILINE)
    if m:
        line = m.group(1).strip()
        # Strip nested markdown link syntax: [Name](url) → Name
        line = _re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        parts = _re.split(r",| and ", line)
        cleaned = _clean_author_names(parts)
        if cleaned:
            return cleaned
    return None


_PLACEHOLDER_PATTERNS = (
    "to be filled during review",
    "collaborative exploration space",
    "fill during review",
    "to be filled",
    "tbd",
)


def _section_is_placeholder(text: str) -> bool:
    """A section body is treated as 'empty placeholder' when, after
    stripping italics/asterisks, it contains only one of the standard
    template lines."""
    s = text.strip().strip("*_ ").strip().lower()
    if not s or len(s) < 4:
        return True
    return any(p in s for p in _PLACEHOLDER_PATTERNS)


def _extract_body_content(note) -> str | None:
    """Build the body to push as a `summary` knowledge entry. Strips:
      - the H1 (title is its own field)
      - structured `**Field:** ...` metadata lines
      - empty H2 sections whose body is only the templated placeholder
        text from the Notion import (`*To be filled during review*`,
        `*Collaborative exploration space*`)
    Returns None when nothing meaningful remains.
    """
    import re as _re
    body = note.body
    body = _re.sub(r"^#\s+.+$\n?", "", body, count=1, flags=_re.MULTILINE)
    body = _re.sub(
        r"^\*\*(Source|Notion|arXiv|DOI|Year|Authors?)\s*:\s*\*\*[^\n]*\n?",
        "", body, flags=_re.MULTILINE,
    )

    # Walk H2 boundaries; drop sections whose body is placeholder-only.
    parts = _re.split(r"(^##\s+.+$)", body, flags=_re.MULTILINE)
    out_parts: list[str] = [parts[0].strip()] if parts else []
    for i in range(1, len(parts), 2):
        heading = parts[i]
        section_body = parts[i + 1] if i + 1 < len(parts) else ""
        if _section_is_placeholder(section_body):
            continue
        out_parts.append(heading.strip())
        out_parts.append(section_body.strip())

    rebuilt = "\n\n".join(p for p in out_parts if p)
    rebuilt = _re.sub(r"\n{3,}", "\n\n", rebuilt).strip()
    if len(rebuilt) < 16:
        return None
    return rebuilt


# ── output helpers ────────────────────────────────────────────────

def emit(payload: dict, *, exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, default=str))
    sys.exit(exit_code)


def emit_error(code: str, message: str, *, exit_code: int = 1, **extra) -> None:
    print(json.dumps({"error": code, "message": message, **extra}, indent=2, default=str))
    sys.exit(exit_code)


def with_api(args) -> tuple[ZergScholarApi, dict, str, Account]:
    cfg = load_config()
    name, acct = get_account(cfg, getattr(args, "account", None))
    return ZergScholarApi(acct), cfg, name, acct


# ── commands ──────────────────────────────────────────────────────

def cmd_setup(_args):
    print("ZergScholar skill — first-time setup", file=sys.stderr)
    print("", file=sys.stderr)
    base = input("base URL [https://zergscholar.fly.dev]: ").strip() or "https://zergscholar.fly.dev"
    print(f"\nMint a token: {base}/app/settings → API Tokens", file=sys.stderr)
    print("Pick scope = `write` for full bridge functionality.", file=sys.stderr)
    token = input("\nPaste the token (zsk_...): ").strip()
    if not token.startswith("zsk_"):
        emit_error("bad_token", "Token should start with `zsk_`.")
    account_name = input("\nAccount name (e.g. personal, epoch) [personal]: ").strip() or "personal"

    # Probe the token to find the workspaces it can reach.
    api = ZergScholarApi(Account(base_url=base, token=token))
    try:
        info = api.whoami()
    except ApiError as e:
        emit_error("token_invalid", f"Token check failed: {e.message}", status=e.status)

    print("\nAccessible workspaces:", file=sys.stderr)
    orgs = info["organizations"]
    if not orgs:
        emit_error("no_workspaces", "Token has no workspace access.")
    for i, org in enumerate(orgs):
        kind = org.get("kind", "shared")
        print(f"  [{i}] {org['name']}  ({kind})  id={org['id']}", file=sys.stderr)
    pick = input(f"\nDefault workspace [0-{len(orgs)-1}, default 0]: ").strip()
    idx = int(pick) if pick.isdigit() else 0
    default_org_id = orgs[idx]["id"]

    vault_default = "/Users/idanbeck/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck"
    vault_in = input(f"\nObsidian vault path [{vault_default}]: ").strip() or vault_default

    cfg: dict = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    cfg.setdefault("accounts", {})
    cfg["accounts"][account_name] = {
        "base_url": base,
        "token": token,
        "default_organization_id": default_org_id,
    }
    cfg.setdefault("default_account", account_name)
    cfg["vault_path"] = vault_in
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

    emit({
        "ok": True,
        "config_path": str(CONFIG_PATH),
        "account": account_name,
        "default_workspace": orgs[idx]["name"],
        "vault_path": vault_in,
    })


def cmd_whoami(args):
    api, _, name, acct = with_api(args)
    try:
        info = api.whoami()
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)
    # /api/auth/me returns {user: {...}}; flatten to a single user object.
    raw_user = info["user"]
    user = raw_user.get("user", raw_user) if isinstance(raw_user, dict) else raw_user
    emit({
        "account": name,
        "base_url": acct.base_url,
        "user": user,
        "default_workspace_id": acct.default_organization_id,
        "workspaces": [
            {"id": o["id"], "name": o["name"], "kind": o.get("kind")}
            for o in info["organizations"]
        ],
    })


def cmd_list_papers(args):
    api, cfg, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace or set default_organization_id.")
    try:
        papers = api.list_papers(org_id)
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    linked = linker.index_linked(vault_path(cfg))
    rows = []
    for p in papers:
        zid = p["id"]
        local = linked.get(zid)
        if args.linked and not local:
            continue
        if args.unlinked and local:
            continue
        rows.append({
            "id": zid,
            "title": p.get("title"),
            "year": p.get("year"),
            "doi": p.get("doi"),
            "arxiv_id": p.get("arxiv_id"),
            "status": p.get("status"),
            "reading_status": p.get("reading_status"),
            "linked_local": bool(local),
            "local_path": local.path if local else None,
        })
    emit({"workspace_id": org_id, "count": len(rows), "papers": rows})


def cmd_push_paper(args):
    api, cfg, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace or set default_organization_id.")
    src = os.path.expanduser(args.file)
    if not os.path.isfile(src):
        emit_error("not_found", f"No such file: {src}")

    note = obsidian.read_note(src)
    fm = note.frontmatter

    if fm.get("zergscholar_id") and not args.force:
        emit({
            "skipped": True,
            "reason": "already_linked",
            "zergscholar_id": str(fm["zergscholar_id"]),
            "local_path": src,
        })

    title = note.title
    year = fm.get("year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    arxiv_id = fm.get("arxiv") or fm.get("arxiv_id")
    doi = fm.get("doi")
    abstract = note.h2_sections.get("Abstract") or note.h2_sections.get("Technical Synopsis", "")
    authors = _extract_authors(note)
    tags = _extract_tags(note)
    body_content = _extract_body_content(note)

    # Find an existing paper to attach to, in priority order:
    #   1. arXiv-id / DOI dedup against the workspace.
    #   2. Frontmatter zergscholar_id (recovery path when retry came
    #      after a previous push with a paperless or partially-failed
    #      state).
    # --force never creates a duplicate row — it just means "re-run
    # the post-link work (enrich + PDF) against whatever existing row
    # we find." Creating a brand-new row when an arxiv-id match exists
    # is essentially never what the caller wants.
    existing = None
    if doi or arxiv_id:
        try:
            existing = api.find_paper(
                doi=str(doi) if doi else None,
                arxiv_id=str(arxiv_id) if arxiv_id else None,
            )
        except ApiError:
            existing = None

    if not existing and fm.get("zergscholar_id"):
        try:
            candidate = api.get_paper(str(fm["zergscholar_id"]))
            if candidate and candidate.get("id"):
                existing = candidate
        except ApiError:
            existing = None

    if existing:
        paper = existing
    else:
        try:
            paper = api.add_paper(
                title=title,
                authors=authors,
                year=year if isinstance(year, int) else None,
                abstract=abstract or None,
                doi=str(doi) if doi else None,
                arxiv_id=str(arxiv_id) if arxiv_id else None,
                tags=tags or None,
                body_content=body_content or None,
            )
        except ApiError as e:
            emit_error("api_error", e.message, status=e.status)

    paper_id = paper["id"]
    # When dedup hit an existing paper, the existing row may not have
    # the tags / body we're carrying — enrich-in-place. Idempotent.
    if existing:
        try:
            api.enrich_paper(
                paper_id=paper_id,
                tags=tags or None,
                body_content=body_content or None,
                authors=authors or None,
                abstract=abstract or None,
            )
        except ApiError:
            pass

    # PDF discovery: explicit --pdf flag wins; otherwise fall back to
    # title-based lookup in Reading/pdfs/. The override exists because
    # the title-based heuristic is brittle when the H1 expands what
    # the filename abbreviated (e.g. "Large Language Model" vs "LLM").
    pdf_path = None
    if getattr(args, "pdf", None):
        candidate = os.path.expanduser(args.pdf)
        if not os.path.isfile(candidate):
            emit_error("not_found", f"PDF not found: {candidate}")
        pdf_path = candidate
    else:
        pdf_path = linker.find_pdf_for(vault_path(cfg), title)

    pdf_result = None
    if pdf_path:
        try:
            pdf_result = api.upload_pdf(paper_id, pdf_path)
        except ApiError as e:
            pdf_result = {"error": e.message, "status": e.status}

    pdf_attempted_and_failed = bool(pdf_path) and (
        isinstance(pdf_result, dict) and pdf_result.get("error")
    )

    # Only mark the note as linked when there's nothing left to retry.
    # If a local PDF was found but the upload failed, leave the note
    # un-linked so the next push will re-enter the dedup path and try
    # the upload again instead of short-circuiting on `already_linked`.
    if not pdf_attempted_and_failed:
        obsidian.update_note_frontmatter(src, {
            "zergscholar_id": paper_id,
            "zergscholar_pushed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    emit({
        "ok": True,
        "paper_id": paper_id,
        "title": paper.get("title"),
        "workspace_id": org_id,
        "pdf_uploaded": bool(pdf_path) and not pdf_attempted_and_failed,
        "pdf_path": pdf_path,
        "pdf_result": pdf_result,
        "linked": not pdf_attempted_and_failed,
        "local_path": src,
    })


# Inverse of H2_TO_ENTRY_TYPE for grouping pulled knowledge entries
# back under their canonical heading. Multiple entry_types can share
# a heading; we pick the most common Obsidian-side label per type.
ENTRY_TYPE_TO_H2 = {
    "summary": "Technical Synopsis",
    "key_finding": "Key Findings",
    "methodology": "Methodology",
    "insight": "My Thoughts",
    "connection": "Connections",
    "definition": "Definitions",
}


def _render_paper_note(paper: dict, base_url: str,
                       knowledge: list[dict] | None = None) -> tuple[dict, str]:
    """Render the {frontmatter, body} for a pulled paper, matching the
    user's existing vault template.

    When `knowledge` is supplied (entries the workspace's AI / collabs
    have built up against this paper), they're woven into the right
    H2 sections. Sections with no entries get placeholder stubs so
    the user can still fill them in locally.
    """
    fm: dict = {
        "tags": ["reading", "research", "zergscholar-import"],
        "type": "reading-analysis",
        "status": paper.get("reading_status") or "unread",
        "source": "zergscholar-import",
        "zergscholar_id": paper["id"],
        "zergscholar_pulled_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if paper.get("year"):
        fm["year"] = paper["year"]
    if paper.get("arxiv_id"):
        fm["arxiv"] = paper["arxiv_id"]
    if paper.get("doi"):
        fm["doi"] = paper["doi"]
    if paper.get("journal"):
        fm["journal"] = paper["journal"]

    title = paper.get("title") or "Untitled paper"
    body_lines = [f"# {title}", ""]

    if paper.get("authors"):
        names = ", ".join(a.get("name", "") for a in paper["authors"])
        body_lines += [f"**Authors:** {names}", ""]

    body_lines += [
        f"**ZergScholar:** [{base_url}/app/papers/{paper['id']}]({base_url}/app/papers/{paper['id']})",
    ]
    if paper.get("arxiv_id"):
        body_lines += [
            f"**arXiv:** [{paper['arxiv_id']}](https://arxiv.org/abs/{paper['arxiv_id']})"
        ]
    if paper.get("doi"):
        body_lines += [f"**DOI:** [{paper['doi']}](https://doi.org/{paper['doi']})"]

    # Group knowledge entries by their canonical Obsidian heading so
    # multiple entries of the same type land in the same section.
    grouped: dict[str, list[str]] = {}
    for e in (knowledge or []):
        et = e.get("entry_type")
        heading = ENTRY_TYPE_TO_H2.get(et)
        if not heading:
            continue
        content = (e.get("content") or "").strip()
        if not content:
            continue
        grouped.setdefault(heading, []).append(content)

    def section(heading: str, fallback: str) -> list[str]:
        items = grouped.get(heading)
        if items:
            body = "\n\n".join(items)
        else:
            body = fallback
        return ["", f"## {heading}", "", body]

    body_lines += ["", "## Abstract", ""]
    body_lines += [paper.get("abstract") or "*No abstract on the server yet.*"]

    body_lines += section("Technical Synopsis", "*Pending full analysis*")
    body_lines += section("Key Findings", "*No key findings extracted yet*")
    body_lines += section("Methodology", "*Methodology TBD*")
    body_lines += section("Connections", "*No connections logged yet*")
    body_lines += section("Definitions", "*No definitions captured yet*")
    body_lines += section("My Thoughts", "*To be filled during review*")

    body_lines += ["", "## Exploration Notes", "", "*Collaborative exploration space*"]

    return fm, "\n".join(body_lines)


def cmd_pull_paper(args):
    api, cfg, _, acct = with_api(args)
    needle = args.id_or_title

    try:
        paper = api.get_paper(needle) if _looks_like_uuid(needle) else _find_by_title(api, acct, needle)
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    if not paper:
        emit_error("not_found", f"No paper matching '{needle}'.")

    # Pull knowledge entries down too unless the caller opts out —
    # this is what makes the bidirectional flow feel real (workspace
    # AI summaries / collaborator findings show up in the local note).
    knowledge: list[dict] = []
    if not args.no_knowledge:
        org_id = paper.get("organization_id") or acct.default_organization_id
        if org_id:
            try:
                knowledge = api.list_knowledge(org_id, paper_id=paper["id"])
            except ApiError:
                knowledge = []

    fm, body = _render_paper_note(paper, acct.base_url, knowledge=knowledge)
    out_path = args.out
    if not out_path:
        filename = linker.title_to_filename(paper.get("title") or paper["id"])
        out_path = os.path.join(linker.vault_research_dir(vault_path(cfg)), filename)
    obsidian.write_note(out_path, fm, body)

    emit({
        "ok": True,
        "paper_id": paper["id"],
        "title": paper.get("title"),
        "local_path": out_path,
        "knowledge_entries_pulled": len(knowledge),
    })


def _looks_like_uuid(s: str) -> bool:
    return len(s) == 36 and s.count("-") == 4


def _find_by_title(api: ZergScholarApi, acct: Account, title: str) -> dict | None:
    org_id = acct.default_organization_id
    if not org_id:
        return None
    matches = api.list_papers(org_id, search=title)
    if not matches:
        return None
    # Prefer exact title match if present.
    target = title.strip().lower()
    for p in matches:
        if (p.get("title") or "").strip().lower() == target:
            return api.get_paper(p["id"])
    return api.get_paper(matches[0]["id"])


# ── Phase 2 / 3 commands ─────────────────────────────────────────

# Map vault H2 section headings to knowledge_entries.entry_type values.
# Anything not in this map is skipped on push-knowledge.
H2_TO_ENTRY_TYPE = {
    "Technical Synopsis": "summary",
    "Summary":            "summary",
    "Abstract":           "summary",
    "Key Findings":       "key_finding",
    "Findings":           "key_finding",
    "Methodology":        "methodology",
    "Methods":            "methodology",
    "My Thoughts":        "insight",
    "Thoughts":           "insight",
    "Insights":           "insight",
    "Connections":        "connection",
    "Related Work":       "connection",
    "Definitions":        "definition",
    "Glossary":           "definition",
}


def cmd_push_knowledge(args):
    api, cfg, _, acct = with_api(args)
    src = os.path.expanduser(args.file)
    if not os.path.isfile(src):
        emit_error("not_found", f"No such file: {src}")

    note = obsidian.read_note(src)
    paper_id = args.paper_id or note.frontmatter.get("zergscholar_id")
    if not paper_id:
        emit_error(
            "no_paper",
            "Note has no zergscholar_id; pass --paper-id, or push the paper first."
        )

    # Pull existing entries on this paper for client-side dedup.
    existing_contents: set[str] = set()
    org_id = acct.default_organization_id
    if org_id:
        try:
            for e in api.list_knowledge(org_id, paper_id=str(paper_id)):
                existing_contents.add((e.get("content") or "").strip())
        except ApiError:
            pass  # non-fatal — just means we may double-post

    pushed: list[dict] = []
    skipped: list[dict] = []
    for heading, body in note.h2_sections.items():
        entry_type = H2_TO_ENTRY_TYPE.get(heading)
        if not entry_type:
            continue
        body = body.strip()
        if not body:
            continue
        if body in existing_contents:
            skipped.append({"section": heading, "reason": "duplicate"})
            continue
        try:
            entry = api.add_knowledge(
                paper_id=str(paper_id),
                entry_type=entry_type,
                content=body,
            )
            pushed.append({
                "section": heading,
                "entry_type": entry_type,
                "entry_id": entry.get("id"),
            })
        except ApiError as e:
            skipped.append({"section": heading, "reason": "api_error", "message": e.message})

    emit({
        "ok": True,
        "paper_id": str(paper_id),
        "pushed_count": len(pushed),
        "skipped_count": len(skipped),
        "pushed": pushed,
        "skipped": skipped,
        "local_path": src,
    })


def cmd_push_draft(args):
    api, cfg, _, acct = with_api(args)
    org_id = acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "No default workspace.")
    src = os.path.expanduser(args.file)
    if not os.path.isfile(src):
        emit_error("not_found", f"No such file: {src}")

    note = obsidian.read_note(src)
    title = note.title
    fm = note.frontmatter
    fmt = (fm.get("format") or "markdown").lower()
    if fmt not in {"markdown", "latex", "typst"}:
        fmt = "markdown"

    # Strip the H1 from the body — server stores the title separately.
    content = re.sub(r"^#\s+.+$\n?", "", note.body, count=1, flags=re.MULTILINE).lstrip()

    existing_id = fm.get("zergscholar_id")

    try:
        if existing_id and not args.force:
            doc = api.update_document(
                str(existing_id),
                title=title,
                content=content,
            )
            mode = "updated"
        else:
            doc = api.create_document(
                org_id=org_id,
                title=title,
                format=fmt,
                content=content,
            )
            mode = "created"
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    obsidian.update_note_frontmatter(src, {
        "zergscholar_id": doc["id"],
        "zergscholar_pushed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "format": fmt,
    })

    emit({
        "ok": True,
        "mode": mode,
        "document_id": doc["id"],
        "title": doc.get("title"),
        "format": doc.get("format"),
        "local_path": src,
    })


def cmd_pull_draft(args):
    api, cfg, _, acct = with_api(args)
    try:
        doc = api.get_document(args.id)
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    title = doc.get("title") or "Untitled draft"
    fmt = doc.get("format") or "markdown"
    content = doc.get("content") or ""

    fm = {
        "tags": ["writing", "zergscholar-import"],
        "format": fmt,
        "status": doc.get("status") or "draft",
        "zergscholar_id": doc["id"],
        "zergscholar_pulled_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    body = f"# {title}\n\n{content.lstrip()}".rstrip() + "\n"

    out_path = args.out
    if not out_path:
        filename = linker.title_to_filename(title)
        out_path = os.path.join(linker.vault_writing_dir(vault_path(cfg)), filename)
    obsidian.write_note(out_path, fm, body)

    emit({
        "ok": True,
        "document_id": doc["id"],
        "title": title,
        "local_path": out_path,
    })


def cmd_pull_all(args):
    api, cfg, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace or set default_organization_id.")

    linked = linker.index_linked(vault_path(cfg))
    try:
        papers = api.list_papers(org_id)
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    pulled: list[dict] = []
    skipped: list[dict] = []
    for p in papers:
        if p["id"] in linked and not args.force:
            skipped.append({"id": p["id"], "title": p.get("title"), "reason": "already_linked"})
            continue
        try:
            full = api.get_paper(p["id"])
            knowledge: list[dict] = []
            if args.with_knowledge:
                try:
                    knowledge = api.list_knowledge(org_id, paper_id=p["id"])
                except ApiError:
                    knowledge = []
            fm, body = _render_paper_note(full, acct.base_url, knowledge=knowledge)
            filename = linker.title_to_filename(full.get("title") or full["id"])
            out_path = os.path.join(linker.vault_research_dir(vault_path(cfg)), filename)
            obsidian.write_note(out_path, fm, body)
            pulled.append({
                "id": p["id"],
                "title": p.get("title"),
                "local_path": out_path,
                "knowledge_entries": len(knowledge),
            })
        except ApiError as e:
            skipped.append({"id": p["id"], "title": p.get("title"), "reason": "api_error", "message": e.message})

    emit({
        "ok": True,
        "workspace_id": org_id,
        "pulled_count": len(pulled),
        "skipped_count": len(skipped),
        "pulled": pulled,
        "skipped": skipped,
    })


def cmd_pull_drafts(args):
    api, cfg, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace or set default_organization_id.")

    try:
        docs = api.list_documents(org_id)
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    pulled: list[dict] = []
    skipped: list[dict] = []
    for summary in docs:
        try:
            doc = api.get_document(summary["id"])
        except ApiError as e:
            skipped.append({"id": summary["id"], "reason": "api_error", "message": e.message})
            continue
        title = doc.get("title") or "Untitled draft"
        fmt = doc.get("format") or "markdown"
        content = doc.get("content") or ""
        fm = {
            "tags": ["writing", "zergscholar-import"],
            "format": fmt,
            "status": doc.get("status") or "draft",
            "zergscholar_id": doc["id"],
            "zergscholar_pulled_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        body = f"# {title}\n\n{content.lstrip()}".rstrip() + "\n"
        filename = linker.title_to_filename(title)
        out_path = os.path.join(linker.vault_writing_dir(vault_path(cfg)), filename)

        # Skip silently if a vault note with this zergscholar_id already
        # exists somewhere — caller can pass --force to overwrite by path.
        existing_linked = linker.index_linked(vault_path(cfg))
        if doc["id"] in existing_linked and not args.force:
            skipped.append({"id": doc["id"], "title": title, "reason": "already_linked",
                            "local_path": existing_linked[doc["id"]].path})
            continue

        obsidian.write_note(out_path, fm, body)
        pulled.append({"id": doc["id"], "title": title, "local_path": out_path})

    emit({
        "ok": True,
        "workspace_id": org_id,
        "pulled_count": len(pulled),
        "skipped_count": len(skipped),
        "pulled": pulled,
        "skipped": skipped,
    })


def cmd_push_folder(args):
    api, cfg, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace or set default_organization_id.")

    folder = os.path.expanduser(args.folder)
    if not os.path.isdir(folder):
        emit_error("not_found", f"No such directory: {folder}")

    notes = list(linker.iter_notes(folder))

    candidates: list[dict] = []
    for path in notes:
        try:
            note = obsidian.read_note(path)
        except Exception as e:
            continue
        already_linked = bool(note.frontmatter.get("zergscholar_id"))
        if already_linked and not args.force:
            continue
        candidates.append({"path": path, "title": note.title, "already_linked": already_linked})

    if args.dry_run:
        emit({
            "dry_run": True,
            "folder": folder,
            "candidates_count": len(candidates),
            "candidates": candidates[:50],
            "truncated": len(candidates) > 50,
            "total_notes_in_folder": len(notes),
        })

    pushed: list[dict] = []
    failed: list[dict] = []
    for c in candidates:
        try:
            # Inline mini-push to avoid nested argparse.
            note = obsidian.read_note(c["path"])
            fm = note.frontmatter
            arxiv_id = fm.get("arxiv") or fm.get("arxiv_id")
            doi = fm.get("doi")
            year = fm.get("year")
            if isinstance(year, str) and year.isdigit():
                year = int(year)
            authors = _extract_authors(note)
            tags = _extract_tags(note)
            body_content = _extract_body_content(note)

            existing = None
            if doi or arxiv_id:
                try:
                    existing = api.find_paper(
                        doi=str(doi) if doi else None,
                        arxiv_id=str(arxiv_id) if arxiv_id else None,
                    )
                except ApiError:
                    existing = None

            if existing:
                paper = existing
                # Even on a dedup hit, push tags + body so the existing
                # row gets enriched with what the local note carries.
                try:
                    api.enrich_paper(
                        paper_id=paper["id"],
                        tags=tags or None,
                        body_content=body_content or None,
                        authors=authors or None,
                    )
                except ApiError:
                    pass
            else:
                paper = api.add_paper(
                    title=note.title, authors=authors,
                    year=year if isinstance(year, int) else None,
                    abstract=note.h2_sections.get("Abstract") or note.h2_sections.get("Technical Synopsis", "") or None,
                    doi=str(doi) if doi else None,
                    arxiv_id=str(arxiv_id) if arxiv_id else None,
                    tags=tags or None,
                    body_content=body_content or None,
                )

            obsidian.update_note_frontmatter(c["path"], {
                "zergscholar_id": paper["id"],
                "zergscholar_pushed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            pushed.append({"path": c["path"], "paper_id": paper["id"], "title": paper.get("title")})
        except ApiError as e:
            failed.append({"path": c["path"], "title": c["title"], "message": e.message, "status": e.status})
        except Exception as e:
            failed.append({"path": c["path"], "title": c["title"], "message": str(e)})

    emit({
        "ok": True,
        "folder": folder,
        "pushed_count": len(pushed),
        "failed_count": len(failed),
        "pushed": pushed[:50],
        "failed": failed[:50],
    })


def cmd_enrich_all(args):
    """Walk every linked vault note and re-push tags + body + authors
    to its already-existing remote paper. Used to backfill data the
    original `push-paper` didn't carry (early bulk-push only sent
    title + year + arxiv).
    """
    api, cfg, _, _ = with_api(args)
    vp = vault_path(cfg)

    notes = list(linker.iter_notes(linker.vault_research_dir(vp)))
    enriched: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for path in notes:
        try:
            note = obsidian.read_note(path)
        except Exception as e:
            failed.append({"path": path, "message": f"read failed: {e}"})
            continue

        zid = note.frontmatter.get("zergscholar_id")
        if not zid:
            skipped.append({"path": path, "reason": "not_linked"})
            continue

        tags = _extract_tags(note)
        body_content = _extract_body_content(note)
        authors = _extract_authors(note)

        if not tags and not body_content and not authors:
            skipped.append({"path": path, "reason": "nothing_to_enrich"})
            continue

        try:
            result = api.enrich_paper(
                paper_id=str(zid),
                tags=tags or None,
                body_content=body_content or None,
                authors=authors or None,
            )
            enriched.append({
                "path": os.path.basename(path),
                "paper_id": str(zid),
                "tags_added": result.get("tagsAdded", 0),
                "authors_added": result.get("authorsAdded", 0),
                "body_inserted": result.get("bodyInserted", False),
            })
        except ApiError as e:
            failed.append({"path": path, "message": e.message, "status": e.status})

    emit({
        "ok": True,
        "scanned": len(notes),
        "enriched_count": len(enriched),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "enriched_sample": enriched[:5],
        "failed_sample": failed[:5],
    })


def _arxiv_fetch_batch(arxiv_ids: list[str]) -> dict[str, dict]:
    """Hit the arXiv ATOM-feed API for up to 100 IDs and return a dict
    keyed by arxiv_id with {title, abstract, authors[], categories[],
    published_year}. Tolerates missing entries."""
    import urllib.request as _urlreq
    import urllib.parse as _urlparse
    import xml.etree.ElementTree as _ET

    if not arxiv_ids:
        return {}
    qs = _urlparse.urlencode({
        "id_list": ",".join(arxiv_ids),
        "max_results": str(len(arxiv_ids)),
    })
    url = f"http://export.arxiv.org/api/query?{qs}"
    req = _urlreq.Request(url, headers={"User-Agent": "zergscholar-skill/0.1 (idan@epochml.com)"})
    with _urlreq.urlopen(req, timeout=60) as resp:
        xml = resp.read()

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = _ET.fromstring(xml)
    out: dict[str, dict] = {}
    for entry in root.findall("atom:entry", ns):
        eid = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        # eid looks like http://arxiv.org/abs/2103.05606v1 — strip prefix + version
        ax = eid.rsplit("/", 1)[-1]
        ax_base = ax.split("v")[0]
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        year = None
        if published[:4].isdigit():
            year = int(published[:4])
        authors = [a.findtext("atom:name", default="", namespaces=ns).strip()
                   for a in entry.findall("atom:author", ns)]
        authors = [a for a in authors if a]
        categories = [c.attrib.get("term", "")
                      for c in entry.findall("{http://arxiv.org/schemas/atom}primary_category")
                      + entry.findall("{http://arxiv.org/schemas/atom}category")]
        categories = list(dict.fromkeys(c for c in categories if c))
        # Title comes wrapped in whitespace + linebreaks; collapse.
        title = " ".join(title.split())
        summary = " ".join(summary.split())
        if ax_base:
            out[ax_base] = {
                "title": title,
                "abstract": summary,
                "authors": authors,
                "categories": categories,
                "year": year,
            }
    return out


def cmd_extract_text(args):
    """Walk every workspace paper that has a PDF but no extracted_text
    and POST to /api/papers/<id>/extract-text. Per-paper API call so
    we sidestep the SSH-session timeout that the bulk Node script ran
    into."""
    api, _, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace ID or set default_organization_id")

    papers: list[dict] = []
    offset = 0
    while True:
        page = api.list_papers(org_id, limit=200, offset=offset)
        if not page:
            break
        papers.extend(page)
        if len(page) < 200:
            break
        offset += 200

    candidates = [p for p in papers
                  if (p.get("pdf_filename") or "").strip()
                  and not (p.get("extracted_text") or "").strip()]

    # The list_papers endpoint may not return extracted_text. Probe the
    # first paper to see — fallback to per-paper get if absent.
    if candidates and "extracted_text" not in candidates[0]:
        candidates = [p for p in papers if (p.get("pdf_filename") or "").strip()]
        # filter via per-paper fetch
        actual: list[dict] = []
        for c in candidates[:1500]:
            full = api.get_paper(c["id"])
            if not (full.get("extracted_text") or "").strip():
                actual.append(c)
        candidates = actual

    if args.dry_run:
        emit({"ok": True, "candidates": len(candidates),
              "would_run": min(len(candidates), args.limit or len(candidates))})

    max_run = args.limit if args.limit else len(candidates)
    ok = 0
    failed: list[dict] = []
    for i, p in enumerate(candidates[:max_run]):
        try:
            r = api.extract_paper_text(p["id"])
            if r.get("ok"):
                ok += 1
        except ApiError as e:
            failed.append({"id": p["id"], "title": (p.get("title") or "")[:80],
                           "reason": e.message[:200]})

    emit({
        "ok": True,
        "candidates": len(candidates),
        "attempted": min(len(candidates), max_run),
        "saved": ok,
        "failed_count": len(failed),
        "failed_sample": failed[:5],
    })


def cmd_enrich_metadata(args):
    """For every workspace paper with an arxiv_id but missing authors
    or abstract, fetch from arXiv API and call enrich-paper. Batched
    100 IDs per request, polite at 3s between batches."""
    import time as _time
    api, _, _, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace ID or set default_organization_id")

    papers: list[dict] = []
    offset = 0
    while True:
        page = api.list_papers(org_id, limit=200, offset=offset)
        if not page:
            break
        papers.extend(page)
        if len(page) < 200:
            break
        offset += 200

    candidates = [p for p in papers
                  if (p.get("arxiv_id") or "").strip()
                  and (not p.get("authors") or len(p["authors"]) == 0
                       or not (p.get("abstract") or "").strip())]

    if args.dry_run:
        emit({
            "ok": True,
            "candidates": len(candidates),
            "would_run": len(candidates) if not args.limit else min(len(candidates), args.limit),
            "sample": [{"title": c.get("title","")[:80], "arxiv_id": c.get("arxiv_id"),
                        "current_authors": len(c.get("authors") or []),
                        "has_abstract": bool((c.get("abstract") or "").strip())}
                       for c in candidates[:5]],
        })

    max_run = args.limit if args.limit else len(candidates)
    candidates = candidates[:max_run]

    enriched = 0
    skipped = 0
    failed: list[dict] = []
    by_id = {(p.get("arxiv_id") or "").strip(): p for p in candidates}

    BATCH = 100
    for i in range(0, len(candidates), BATCH):
        batch = candidates[i:i + BATCH]
        ids = [p.get("arxiv_id") for p in batch if p.get("arxiv_id")]
        try:
            meta = _arxiv_fetch_batch(ids)
        except Exception as e:
            for p in batch:
                failed.append({"id": p["id"], "arxiv_id": p.get("arxiv_id"), "reason": f"fetch failed: {e}"[:200]})
            _time.sleep(3.0)
            continue
        for p in batch:
            ax = (p.get("arxiv_id") or "").strip()
            m = meta.get(ax) or meta.get(ax.split("v")[0])
            if not m:
                skipped += 1
                continue
            payload: dict = {}
            existing_authors = p.get("authors") or []
            if m["authors"] and len(existing_authors) == 0:
                payload["authors"] = m["authors"]
            if m["abstract"] and not (p.get("abstract") or "").strip():
                payload["abstract"] = m["abstract"]
            if not payload:
                skipped += 1
                continue
            try:
                api.enrich_paper(paper_id=p["id"], **payload)
                enriched += 1
            except ApiError as e:
                failed.append({"id": p["id"], "arxiv_id": ax, "reason": e.message[:200]})
        _time.sleep(3.0)

    emit({
        "ok": True,
        "scanned_papers": len(papers),
        "candidates": len(by_id),
        "enriched": enriched,
        "skipped": skipped,
        "failed_count": len(failed),
        "failed_sample": failed[:5],
    })


def cmd_backfill_pdfs(args):
    """For every paper in the workspace that has an arXiv id but no
    PDF attached, fetch from arxiv.org/pdf/<id>.pdf and upload via the
    skill's upload-pdf endpoint.

    Polite: 3.5s between fetches per arXiv guidance for unauthenticated
    bulk traffic.
    """
    import time as _time
    from urllib import request as _urlreq

    api, _cfg, _name, acct = with_api(args)
    org_id = args.workspace or acct.default_organization_id
    if not org_id:
        emit_error("no_workspace", "Pass --workspace ID or set default_organization_id")

    # Page through all papers (server caps at ~200 per request).
    papers: list[dict] = []
    offset = 0
    while True:
        page = api.list_papers(org_id, limit=200, offset=offset)
        if not page:
            break
        papers.extend(page)
        if len(page) < 200:
            break
        offset += 200

    candidates = [p for p in papers
                  if (p.get("arxiv_id") or "").strip()
                  and not (p.get("pdf_filename") or "").strip()]

    max_run = args.limit if args.limit else len(candidates)

    if args.dry_run:
        emit({
            "ok": True,
            "candidates": len(candidates),
            "would_run": min(len(candidates), max_run),
            "sample": [{"id": c["id"], "title": c.get("title", "")[:80], "arxiv_id": c.get("arxiv_id")}
                       for c in candidates[:5]]
        })

    saved: list[dict] = []
    failed: list[dict] = []
    for i, p in enumerate(candidates):
        if i >= max_run:
            break
        arxiv_id = (p.get("arxiv_id") or "").strip()
        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        try:
            req = _urlreq.Request(url, headers={"User-Agent": "zergscholar-skill/0.1 (idan@epochml.com)"})
            with _urlreq.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) < 1024:
                failed.append({"id": p["id"], "arxiv_id": arxiv_id, "reason": "tiny_response", "bytes": len(data)})
            else:
                fname = "".join(c if c.isalnum() or c in ".-_" else "_" for c in arxiv_id) + ".pdf"
                api.upload_pdf_bytes(p["id"], fname, data)
                saved.append({"id": p["id"], "arxiv_id": arxiv_id, "bytes": len(data)})
        except Exception as e:
            failed.append({"id": p["id"], "arxiv_id": arxiv_id, "reason": str(e)[:200]})

        _time.sleep(3.5)

    emit({
        "ok": True,
        "scanned_papers": len(papers),
        "candidates": len(candidates),
        "attempted": min(len(candidates), max_run),
        "saved_count": len(saved),
        "failed_count": len(failed),
        "saved_sample": saved[:5],
        "failed_sample": failed[:5],
    })


def cmd_push_annotation(args):
    api, _, _, _ = with_api(args)
    src = os.path.expanduser(args.file)
    if not os.path.isfile(src):
        emit_error("not_found", f"No such file: {src}")

    note = obsidian.read_note(src)
    paper_id = args.paper_id or note.frontmatter.get("zergscholar_id")
    if not paper_id:
        emit_error("no_paper", "Note has no zergscholar_id; pass --paper-id, or push the paper first.")

    try:
        ann = api.add_annotation(
            paper_id=str(paper_id),
            content=args.content,
            page_number=args.page,
            highlight_text=args.highlight,
        )
    except ApiError as e:
        emit_error("api_error", e.message, status=e.status)

    emit({"ok": True, "paper_id": str(paper_id), "annotation_id": ann.get("id")})


def cmd_status(args):
    api, cfg, name, acct = with_api(args)
    org_id = acct.default_organization_id
    vp = vault_path(cfg)

    # Walk every research note once and split linked vs unlinked.
    # Notes that share a zergscholar_id (because DOI/arxiv dedup
    # pointed both at the same remote paper) all count as "linked";
    # `unique_remote_papers_linked` reflects the dedupped count.
    linked_notes = 0
    unlinked_notes = 0
    unique_paper_ids: set[str] = set()
    research_total = 0
    for path in linker.iter_notes(linker.vault_research_dir(vp)):
        research_total += 1
        try:
            note = obsidian.read_note(path)
        except Exception:
            unlinked_notes += 1
            continue
        zid = note.frontmatter.get("zergscholar_id")
        if zid:
            linked_notes += 1
            unique_paper_ids.add(str(zid))
        else:
            unlinked_notes += 1

    writing_total = sum(1 for _ in linker.iter_notes(linker.vault_writing_dir(vp)))

    remote_count = 0
    if org_id:
        try:
            remote_count = api.count_papers(org_id)
        except ApiError:
            remote_count = -1  # signal: unreachable

    emit({
        "account": name,
        "vault_path": vp,
        "research_notes": research_total,
        "linked_notes": linked_notes,
        "unique_remote_papers_linked": len(unique_paper_ids),
        "unlinked_notes": unlinked_notes,
        "writing_notes": writing_total,
        "remote_papers": remote_count,
        "default_workspace_id": org_id,
    })


# ── argparse ──────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(prog="zergscholar", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="interactive: write config.json")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("whoami", help="token info + accessible workspaces")
    s.add_argument("-a", "--account")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("list-papers", help="list workspace papers, joined with vault")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="org UUID; defaults to account's default")
    s.add_argument("--linked", action="store_true", help="only papers with a local note")
    s.add_argument("--unlinked", action="store_true", help="only papers without a local note")
    s.set_defaults(func=cmd_list_papers)

    s = sub.add_parser("push-paper", help="push a vault note to zergscholar")
    s.add_argument("file", help="path to the .md note in the vault")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="override default workspace")
    s.add_argument("--force", action="store_true", help="re-push even if already linked (re-enriches + retries PDF against the existing arxiv-id-matched row; never creates a duplicate)")
    s.add_argument("--pdf", help="explicit path to the PDF to upload (overrides title-based discovery in Reading/pdfs/)")
    s.set_defaults(func=cmd_push_paper)

    s = sub.add_parser("pull-paper", help="fetch a remote paper into the vault")
    s.add_argument("id_or_title", help="paper UUID or fuzzy title")
    s.add_argument("-a", "--account")
    s.add_argument("-o", "--out", help="override output path")
    s.add_argument("--no-knowledge", action="store_true", help="skip pulling knowledge entries (faster)")
    s.set_defaults(func=cmd_pull_paper)

    s = sub.add_parser("status", help="vault linkage summary")
    s.add_argument("-a", "--account")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("push-knowledge", help="extract H2 sections of a paper note as knowledge entries")
    s.add_argument("file", help="path to the .md note in the vault")
    s.add_argument("-a", "--account")
    s.add_argument("--paper-id", help="override paper UUID (defaults to note's zergscholar_id)")
    s.set_defaults(func=cmd_push_knowledge)

    s = sub.add_parser("push-draft", help="push a Writing/ note as a zergscholar document")
    s.add_argument("file", help="path to the .md draft in the vault")
    s.add_argument("-a", "--account")
    s.add_argument("--force", action="store_true", help="create a new doc even if zergscholar_id is set")
    s.set_defaults(func=cmd_push_draft)

    s = sub.add_parser("pull-draft", help="fetch a remote document into Writing/")
    s.add_argument("id", help="document UUID")
    s.add_argument("-a", "--account")
    s.add_argument("-o", "--out", help="override output path")
    s.set_defaults(func=cmd_pull_draft)

    s = sub.add_parser("pull-all", help="bulk pull every paper from the workspace into the vault")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="override default workspace")
    s.add_argument("--force", action="store_true", help="overwrite already-linked notes")
    s.add_argument("--with-knowledge", action="store_true", help="also pull knowledge entries (slower; one extra API call per paper)")
    s.set_defaults(func=cmd_pull_all)

    s = sub.add_parser("pull-drafts", help="bulk pull every document into Writing/")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="override default workspace")
    s.add_argument("--force", action="store_true", help="overwrite already-linked drafts")
    s.set_defaults(func=cmd_pull_drafts)

    s = sub.add_parser("push-folder", help="bulk-push every unlinked paper note in a folder")
    s.add_argument("folder", help="vault folder to scan recursively")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="override default workspace")
    s.add_argument("--dry-run", action="store_true", help="report what would be pushed; do not write")
    s.add_argument("--force", action="store_true", help="re-push already-linked notes too")
    s.set_defaults(func=cmd_push_folder)

    s = sub.add_parser("enrich-all", help="walk every linked vault note and re-push tags + body + authors")
    s.add_argument("-a", "--account")
    s.set_defaults(func=cmd_enrich_all)

    s = sub.add_parser("extract-text", help="run server-side PDF text extraction over every paper with a PDF and no extracted_text")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="organization id (defaults to account default)")
    s.add_argument("--limit", type=int, help="stop after N papers")
    s.add_argument("--dry-run", action="store_true", help="report candidates without running")
    s.set_defaults(func=cmd_extract_text)

    s = sub.add_parser("enrich-metadata", help="hit the arXiv ATOM API to fill in authors + abstracts for papers with arxiv_id")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="organization id (defaults to account default)")
    s.add_argument("--limit", type=int, help="stop after N papers")
    s.add_argument("--dry-run", action="store_true", help="report candidates without fetching")
    s.set_defaults(func=cmd_enrich_metadata)

    s = sub.add_parser("backfill-pdfs", help="fetch missing PDFs from arXiv for every paper that has an arxiv_id")
    s.add_argument("-a", "--account")
    s.add_argument("--workspace", help="organization id (defaults to account default)")
    s.add_argument("--limit", type=int, help="stop after N PDFs")
    s.add_argument("--dry-run", action="store_true", help="report candidates without fetching")
    s.set_defaults(func=cmd_backfill_pdfs)

    s = sub.add_parser("push-annotation", help="post an annotation against a paper")
    s.add_argument("file", help="path to the linked paper note (provides zergscholar_id)")
    s.add_argument("content", help="annotation body")
    s.add_argument("-a", "--account")
    s.add_argument("--paper-id", help="override paper UUID")
    s.add_argument("--page", type=int, help="page number")
    s.add_argument("--highlight", help="highlighted source text")
    s.set_defaults(func=cmd_push_annotation)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
