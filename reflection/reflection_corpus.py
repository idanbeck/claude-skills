#!/usr/bin/env python3
"""
reflection_corpus.py — assemble the evidence corpus for the `reflection` skill.

The Reflection Engine method treats the person's OWN words and choices as primary
evidence, and assistant-written summaries as pointers only. This script honours that:
it extracts user-authored turns from Claude Code transcripts, plus first-person
material from an Obsidian vault (daily notes, personal notes, writing), buckets it
by month so the analysis can sample across time, and emits a single Markdown digest.

Usage:
  python3 reflection_corpus.py --out /tmp/corpus.md
  python3 reflection_corpus.py --sources claude,vault --months 18 --budget 400000
  python3 reflection_corpus.py --inventory        # just report what's available

Python standard library only.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
DEFAULT_VAULT = (
    Path.home()
    / "Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck"
)

# Vault subtrees worth reading, in priority order. Daily notes first: they carry
# #log / #win / #improve / #gratitude and are the densest first-person record.
VAULT_DIRS = ["Daily", "Personal", "Writing", "Meetings", "Notes", "Projects"]

# Transcript noise: harness plumbing, not the person talking.
NOISE_PATTERNS = [
    r"<local-command-caveat>.*?</local-command-caveat>",
    r"<command-name>.*?</command-name>",
    r"<command-message>.*?</command-message>",
    r"<command-args>.*?</command-args>",
    r"<local-command-stdout>.*?</local-command-stdout>",
    r"<system-reminder>.*?</system-reminder>",
    r"<task-notification>.*?</task-notification>",
    r"\[SYSTEM NOTIFICATION[^\]]*\]",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.S | re.I)

# Vault scaffolding that is template, not authored content.
VAULT_STRIP = [
    r"^---\n.*?\n---\n",           # frontmatter
    r"```dataview.*?```",           # dynamic queries
    r"<!--.*?-->",                  # html comments
]
VAULT_STRIP_RE = [re.compile(p, re.S | re.M) for p in VAULT_STRIP]


def month_of(ts):
    if not ts:
        return "unknown"
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%Y-%m")
    except Exception:
        return "unknown"


def clean(text):
    text = NOISE_RE.sub(" ", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_to_text(content):
    """Claude message content is a str or a list of blocks; keep only real text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        # tool_result blocks are machine output, never the person's words
        if block.get("type") == "text":
            out.append(block.get("text", ""))
    return "\n".join(out)


def harvest_claude(min_chars, per_month_cap):
    """User-authored turns from Claude Code transcripts, bucketed by month."""
    buckets = defaultdict(list)
    if not CLAUDE_PROJECTS.exists():
        return buckets
    files = [
        p for p in CLAUDE_PROJECTS.rglob("*.jsonl")
        if "/subagents/" not in str(p)
    ]
    for path in files:
        project = path.parent.name
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    if '"type":"user"' not in line and '"type": "user"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("type") != "user" or obj.get("isMeta"):
                        continue
                    msg = obj.get("message") or {}
                    text = clean(content_to_text(msg.get("content")))
                    if len(text) < min_chars:
                        continue
                    buckets[month_of(obj.get("timestamp"))].append(
                        {"source": f"claude:{project}", "text": text}
                    )
        except Exception:
            continue
    for m in buckets:
        # Prefer longer turns: more signal per character.
        buckets[m].sort(key=lambda r: -len(r["text"]))
        buckets[m] = buckets[m][:per_month_cap]
    return buckets


def strip_vault(text):
    for rx in VAULT_STRIP_RE:
        text = rx.sub(" ", text)
    return clean(text)


def harvest_vault(vault, min_chars, per_month_cap):
    """First-person vault material, bucketed by file mtime month."""
    buckets = defaultdict(list)
    root = Path(vault)
    if not root.exists():
        return buckets
    for sub in VAULT_DIRS:
        d = root / sub
        if not d.exists():
            continue
        for path in d.rglob("*.md"):
            try:
                raw = path.read_text(errors="replace")
            except Exception:
                continue
            text = strip_vault(raw)
            if len(text) < min_chars:
                continue
            # Daily notes encode their date in the path; fall back to mtime.
            m = re.search(r"(20\d{2})/q\d/(\d{2})-", str(path))
            if m:
                month = f"{m.group(1)}-{m.group(2)}"
            else:
                month = month_of(path.stat().st_mtime)
            rel = path.relative_to(root)
            buckets[month].append({"source": f"vault:{rel}", "text": text})
    for m in buckets:
        buckets[m].sort(key=lambda r: -len(r["text"]))
        buckets[m] = buckets[m][:per_month_cap]
    return buckets


def harvest_memory():
    """Assistant-written memory. Pointers only — NOT primary evidence."""
    rows = []
    for mem in CLAUDE_PROJECTS.rglob("memory/*.md"):
        try:
            rows.append({"source": f"memory:{mem.name}", "text": mem.read_text(errors="replace").strip()})
        except Exception:
            continue
    return rows


def inventory(vault):
    print("CORPUS INVENTORY")
    files = [p for p in CLAUDE_PROJECTS.rglob("*.jsonl") if "/subagents/" not in str(p)] \
        if CLAUDE_PROJECTS.exists() else []
    print(f"  claude transcripts : {len(files)} files")
    c = harvest_claude(min_chars=80, per_month_cap=10**6)
    for m in sorted(k for k in c if k != "unknown"):
        chars = sum(len(r['text']) for r in c[m])
        print(f"      {m}: {len(c[m]):5d} user turns, {chars//1000:6d}k chars")
    v = harvest_vault(vault, min_chars=200, per_month_cap=10**6)
    print(f"  vault notes        : {sum(len(x) for x in v.values())} files")
    months = sorted(k for k in v if k != "unknown")
    if months:
        print(f"      span: {months[0]} .. {months[-1]} ({len(months)} months)")
    print(f"  memory files       : {len(harvest_memory())} (pointers only, not evidence)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/reflection-corpus.md")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--sources", default="claude,vault,memory")
    ap.add_argument("--budget", type=int, default=600000,
                    help="approx max characters in the digest")
    ap.add_argument("--per-month", type=int, default=40,
                    help="max items retained per month per source")
    ap.add_argument("--min-chars", type=int, default=120)
    ap.add_argument("--inventory", action="store_true")
    args = ap.parse_args()

    if args.inventory:
        inventory(args.vault)
        return

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    merged = defaultdict(list)

    if "claude" in sources:
        for m, rows in harvest_claude(args.min_chars, args.per_month).items():
            merged[m].extend(rows)
    if "vault" in sources:
        for m, rows in harvest_vault(args.vault, args.min_chars, args.per_month).items():
            merged[m].extend(rows)

    months = sorted(k for k in merged if k != "unknown")
    if not months:
        print("No corpus found.", file=sys.stderr)
        sys.exit(1)

    # Spread the budget evenly across months so recent material cannot dominate.
    per_month_budget = max(4000, args.budget // max(1, len(months)))

    parts = [
        "# Reflection Corpus Digest",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Months covered: {months[0]} .. {months[-1]} ({len(months)} months)",
        "",
        "PRIMARY EVIDENCE = the person's own words (`claude:` user turns, `vault:` notes "
        "they wrote). Memory files at the end are assistant-written summaries: use them to "
        "LOCATE evidence, never as proof on their own.",
        "",
    ]

    for m in months:
        rows = merged[m]
        parts.append(f"\n---\n\n## {m}  ({len(rows)} items)\n")
        used = 0
        for r in rows:
            if used >= per_month_budget:
                parts.append(f"\n_[{len(rows)} items this month; digest truncated at budget]_\n")
                break
            snippet = r["text"]
            room = per_month_budget - used
            if len(snippet) > room:
                snippet = snippet[:room] + " …[truncated]"
            parts.append(f"### {r['source']}\n\n{snippet}\n")
            used += len(snippet)

    if "memory" in sources:
        mem = harvest_memory()
        parts.append("\n---\n\n## Assistant memory (POINTERS ONLY — not primary evidence)\n")
        for r in mem:
            parts.append(f"### {r['source']}\n\n{r['text'][:1200]}\n")

    out = Path(args.out)
    out.write_text("\n".join(parts))
    size = out.stat().st_size
    print(f"wrote {out} ({size//1000}k chars, {len(months)} months, "
          f"{sum(len(v) for v in merged.values())} items)")


if __name__ == "__main__":
    main()
