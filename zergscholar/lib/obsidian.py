"""Minimal Obsidian vault helpers for paper notes.

Frontmatter parsing is hand-rolled (no PyYAML dep) — the dialect is
small and predictable: scalar values, comma-lists for tags, ISO dates.
H2 sections are extracted as a {heading: body} dict so callers can
pull "Technical Synopsis", "My Thoughts", etc. into knowledge entries.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


# Sections the user typically leaves stubbed-out before reviewing a
# paper. We treat these placeholders as empty when extracting.
PLACEHOLDER_PATTERNS = [
    r"^\*To be filled.*\*$",
    r"^\*Pending.*\*$",
    r"^\*Collaborative exploration space\*$",
    r"^TODO\s*$",
    r"^_To be filled.*_$",
]


@dataclass
class Note:
    path: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    h2_sections: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        # Title is the first H1 if present; falls back to the filename.
        m = re.search(r"^#\s+(.+)$", self.body, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return os.path.splitext(os.path.basename(self.path))[0]


def _parse_frontmatter(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([\w-]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        # Strip optional surrounding quotes.
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        # JSON-style list: `["a", "b"]` (Notion exports use this shape
        # for `authors:` and the like).
        if val.startswith("[") and val.endswith("]"):
            try:
                import json as _json
                parsed = _json.loads(val)
                if isinstance(parsed, list):
                    out[key] = [str(x).strip() for x in parsed if str(x).strip()]
                    continue
            except Exception:
                pass
        # Comma-list heuristic for `tags` and similar.
        if "," in val and key in {"tags", "authors", "aliases"}:
            out[key] = [s.strip() for s in val.split(",") if s.strip()]
        elif val.lower() in {"true", "false"}:
            out[key] = val.lower() == "true"
        elif re.fullmatch(r"\d+", val):
            out[key] = int(val)
        else:
            out[key] = val
    return out


def _serialize_frontmatter(fm: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}: {', '.join(str(x) for x in v)}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif v is None:
            continue
        else:
            sv = str(v)
            # Quote anything containing a colon to keep the YAML valid.
            if ":" in sv or sv.startswith(" ") or sv.endswith(" "):
                sv = f'"{sv}"'
            lines.append(f"{k}: {sv}")
    lines.append("---")
    return "\n".join(lines)


def _extract_h2_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    # Drop placeholder sections.
    cleaned: dict[str, str] = {}
    for k, v in sections.items():
        if not v:
            continue
        is_placeholder = any(re.match(p, line.strip()) for p in PLACEHOLDER_PATTERNS for line in v.splitlines() if line.strip())
        if is_placeholder and len(v.splitlines()) <= 2:
            continue
        cleaned[k] = v
    return cleaned


def read_note(path: str) -> Note:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    fm: dict[str, Any] = {}
    body = text

    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            fm = _parse_frontmatter(text[4:end])
            body = text[end + 5:].lstrip()

    return Note(
        path=path,
        frontmatter=fm,
        body=body,
        h2_sections=_extract_h2_sections(body),
    )


def write_note(path: str, frontmatter: dict[str, Any], body: str) -> None:
    text = _serialize_frontmatter(frontmatter) + "\n\n" + body.lstrip() + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def update_note_frontmatter(path: str, patch: dict[str, Any]) -> None:
    """Merge `patch` into the note's existing frontmatter and write back.
    Preserves untouched body content verbatim.
    """
    note = read_note(path)
    note.frontmatter.update(patch)
    write_note(path, note.frontmatter, note.body)


# Lifted from the Obsidian convention — paper notes are titled the
# same as the file. Keep punctuation; strip filesystem-hostile chars.
def slugify_title(title: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]", " ", title)
    s = re.sub(r"\s+", " ", s).strip()
    return s
