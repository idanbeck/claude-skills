"""Vault ↔ zergscholar linkage helpers.

The single source of truth for whether a local note is linked to a
remote paper is the `zergscholar_id` field in the note's frontmatter.
This module scans the vault to build a fast bidirectional index and
fuzzy-matches PDFs to paper titles.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .obsidian import read_note, slugify_title


@dataclass
class LinkedNote:
    path: str
    zergscholar_id: str
    title: str


def vault_research_dir(vault_path: str) -> str:
    return os.path.join(vault_path, "Reading", "Research")


def vault_pdfs_dir(vault_path: str) -> str:
    return os.path.join(vault_path, "Reading", "pdfs")


def vault_writing_dir(vault_path: str) -> str:
    return os.path.join(vault_path, "Writing")


def iter_notes(directory: str):
    """Walk a vault subdir and yield every .md path."""
    if not os.path.isdir(directory):
        return
    for root, _, files in os.walk(directory):
        for name in files:
            if name.endswith(".md"):
                yield os.path.join(root, name)


def index_linked(vault_path: str) -> dict[str, LinkedNote]:
    """Return {zergscholar_id: LinkedNote} for every paper note in the
    vault that has a `zergscholar_id` frontmatter field.
    """
    out: dict[str, LinkedNote] = {}
    for path in iter_notes(vault_research_dir(vault_path)):
        try:
            note = read_note(path)
        except Exception:
            continue
        zid = note.frontmatter.get("zergscholar_id")
        if zid:
            out[str(zid)] = LinkedNote(path=path, zergscholar_id=str(zid), title=note.title)
    return out


def find_pdf_for(vault_path: str, title: str) -> str | None:
    """Look for a PDF in Reading/pdfs/ whose name matches the paper title.

    Returns the first plausible match — exact-slug, then case-insensitive
    substring. Returns None if nothing's close enough.
    """
    pdfs_dir = vault_pdfs_dir(vault_path)
    if not os.path.isdir(pdfs_dir):
        return None

    target_slug = slugify_title(title)
    target_lc = target_slug.lower()

    candidates = []
    for name in os.listdir(pdfs_dir):
        if not name.lower().endswith(".pdf"):
            continue
        stem = name[:-4]
        stem_slug = slugify_title(stem)
        if stem_slug.lower() == target_lc:
            return os.path.join(pdfs_dir, name)
        candidates.append((stem_slug.lower(), os.path.join(pdfs_dir, name)))

    # Substring fallback — title contained in filename (or vice versa).
    for stem_lc, path in candidates:
        if target_lc in stem_lc or stem_lc in target_lc:
            return path
    return None


def find_note_by_title(vault_path: str, title: str) -> str | None:
    target = slugify_title(title).lower()
    for path in iter_notes(vault_research_dir(vault_path)):
        stem = os.path.splitext(os.path.basename(path))[0]
        if slugify_title(stem).lower() == target:
            return path
    return None


def title_to_filename(title: str) -> str:
    """Match the existing Obsidian convention — filename is the title
    with filesystem-hostile chars stripped, plus a .md extension.
    """
    return slugify_title(title) + ".md"
