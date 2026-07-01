"""Instantiate the Interview Candidate template into People/Recruiting/[Name].md.

Frontmatter + Candidate Overview are filled once; an auto, sentinel-bounded
'AI Screen' block is (re)written idempotently so human interview notes survive.
"""
import re
import shutil
from datetime import date

from . import config, store

AS, AE = config.AUTO_START, config.AUTO_END
AXES = ["technical_skills", "problem_solving", "communication",
        "cultural_fit", "growth_potential"]
TIER_REC = {"reach-out": "More Interviews Needed (strong inbound — reach out)",
            "maybe": "More Interviews Needed", "pass": "No Hire"}


def _safe_name(name):
    n = re.sub(r'[\\/:*?"<>|]', "", (name or "Unknown").strip())
    return n or "Unknown"


def _set_fm(fm_text, key, value):
    """Set a `key:` line inside frontmatter text (only if the key line exists)."""
    pat = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    if pat.search(fm_text):
        return pat.sub(f"{key}: {value}", fm_text, count=1)
    return fm_text


def _split_fm(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        return m.group(1), m.group(2)
    return None, text


def _auto_block(cand):
    sj = store.jload(cand["score_json"], {}) or {}
    axes = sj.get("axes", {})
    flags = sj.get("red_flags", []) or []
    link = cand["profile_url"] or cand["detail_url"] or ""
    rows = "\n".join(
        f"| {a.replace('_',' ').title()} | {axes.get(a) if axes.get(a) is not None else ''} | |"
        for a in AXES)
    out = [
        AS,
        "## AI Screen (LinkedIn triage)",
        f"**Tier:** {cand['tier']}  **Overall:** {cand['overall_score']}  "
        f"**Source:** LinkedIn applicant",
        f"**Profile:** {link}" if link else "**Profile:** (from email preview; full URL pending burner pull)",
        "",
        "### Screen Scorecard (AI, 1-5)",
        "| Criteria | Score | Notes |",
        "|----------|-------|-------|",
        rows,
        f"| **Overall** | {cand['overall_score']} | |",
        "",
        "### Rationale",
        cand["rationale"] or "",
    ]
    if flags:
        out += ["", "### Red Flags / Watch", *[f"- {f}" for f in flags]]
    draft = (cand["outreach_draft"] or "").strip()
    out += ["", "### Outreach Draft",
            (draft if draft else "_No draft (pass tier)._"),
            "",
            "- [ ] drafted" + (" ✅" if draft else ""),
            "- [ ] sent",
            "- [ ] responded",
            AE]
    return "\n".join(out)


def _render_new(cand, role_title):
    tmpl = config.TEMPLATE_PATH.read_text()
    name = cand["full_name"] or cand["display_name"] or "Unknown"
    today = date.today().isoformat()
    text = tmpl.replace("{{title}}", name).replace("{{date}}", today)
    fm, body = _split_fm(text)
    if fm is not None:
        fm = _set_fm(fm, "location", f'"{cand["location"] or ""}"')
        fm = _set_fm(fm, "linkedin", cand["profile_url"] or cand["detail_url"] or "")
        fm = _set_fm(fm, "role_applied", f'"{role_title or ""}"')
        fm = _set_fm(fm, "source", "linkedin")
        text = f"---\n{fm}\n---\n{body}"
    # Candidate Overview fills
    text = text.replace("**Applied For:**", f"**Applied For:** {role_title or ''}", 1)
    text = text.replace("**Current Role:**",
                        f"**Current Role:** {cand['headline'] or ''}", 1)
    text = text.replace("**Location:**", f"**Location:** {cand['location'] or ''}", 1)
    text = text.replace("**Source:**", "**Source:** LinkedIn applicant", 1)
    return text.rstrip() + "\n\n" + _auto_block(cand) + "\n"


def _upsert_auto(existing, cand):
    block = _auto_block(cand)
    if AS in existing and AE in existing:
        return re.sub(re.escape(AS) + r".*?" + re.escape(AE), block, existing, flags=re.S)
    return existing.rstrip() + "\n\n" + block + "\n"


def _target_path(cand):
    name = _safe_name(cand["full_name"] or cand["display_name"])
    base = config.RECRUITING_DIR / f"{name}.md"
    if not base.exists():
        return base
    # collision: same linkedin -> update in place; else suffix by city
    try:
        existing = base.read_text()
    except OSError:
        return base
    link = cand["profile_url"] or cand["detail_url"] or ""
    if link and link in existing:
        return base
    if cand["filed_path"] and str(base) == cand["filed_path"]:
        return base
    city = (cand["location"] or "").split(",")[0].strip()
    suffix = f" ({city})" if city else f" ({cand['id']})"
    return config.RECRUITING_DIR / f"{name}{suffix}.md"


def file_candidates(conn, role_ref=None, tier="reach-out", min_score=None,
                    force=False, limit=None, dry_run=False):
    role_row = store.role_by_ref(conn, role_ref) if role_ref else None
    role_id = role_row["id"] if role_row else None
    q = "SELECT * FROM candidates WHERE status IN ('triaged','filed')"
    args = []
    if role_id is not None:
        q += " AND role_id=?"; args.append(role_id)
    if min_score is not None:
        q += " AND overall_score>=?"; args.append(min_score)
    elif tier:
        q += " AND tier=?"; args.append(tier)
    q += " ORDER BY overall_score DESC, id ASC"
    if limit:
        q += " LIMIT ?"; args.append(limit)
    rows = conn.execute(q, args).fetchall()

    role_title_cache = {}
    counts = {"selected": len(rows), "created": 0, "updated": 0, "skipped": 0}
    config.RECRUITING_DIR.mkdir(parents=True, exist_ok=True)
    for c in rows:
        if c["status"] == "filed" and not force:
            counts["skipped"] += 1
            continue
        rt = role_title_cache.get(c["role_id"])
        if rt is None:
            rr = conn.execute("SELECT title FROM roles WHERE id=?", (c["role_id"],)).fetchone()
            rt = rr["title"] if rr else ""
            role_title_cache[c["role_id"]] = rt
        path = _target_path(c)
        if dry_run:
            action = "update" if path.exists() else "create"
            print(f"[dry] {action}: {path.name}  ({c['tier']} {c['overall_score']})")
            continue
        if path.exists():
            new_text = _upsert_auto(path.read_text(), c)
            path.write_text(new_text)
            counts["updated"] += 1
        else:
            path.write_text(_render_new(c, rt))
            counts["created"] += 1
        # resume copy
        if c["resume_path"]:
            try:
                dest = config.RECRUITING_DIR / f"{_safe_name(c['full_name'] or c['display_name'])}Resume.pdf"
                shutil.copy2(c["resume_path"], dest)
            except OSError:
                pass
        store.mark_filed(conn, c["id"], path)
    conn.commit()
    return counts
