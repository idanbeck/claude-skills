"""Ranked shortlist report (markdown or csv)."""
import csv
import io

from . import store


def _rows(conn, role_ref, tier, top):
    role_id = None
    if role_ref:
        r = store.role_by_ref(conn, role_ref)
        role_id = r["id"] if r else -1
    rows = store.list_candidates(conn, role_id=role_id, tier=tier,
                                 status=None, limit=top,
                                 order="overall_score DESC, id ASC")
    return [r for r in rows if r["overall_score"] is not None]


def build_report(conn, role_ref=None, fmt="md", out_path=None, tier=None, top=None):
    rows = _rows(conn, role_ref, tier, top)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["rank", "name", "tier", "overall", "headline", "location",
                    "link", "rationale", "status"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["display_name"] or r["full_name"], r["tier"],
                        r["overall_score"], r["headline"], r["location"],
                        r["profile_url"] or r["detail_url"], r["rationale"], r["status"]])
        text = buf.getvalue()
    else:
        lines = [f"# LinkedIn applicant shortlist ({len(rows)} ranked)\n",
                 "| # | Name | Tier | Score | Headline | Location | Why |",
                 "|---|------|------|------:|----------|----------|-----|"]
        for i, r in enumerate(rows, 1):
            name = (r["display_name"] or r["full_name"] or "?").replace("|", "/")
            hl = (r["headline"] or "").replace("|", "/")[:60]
            loc = (r["location"] or "").replace("|", "/")
            why = (r["rationale"] or "").replace("|", "/")[:90]
            lines.append(f"| {i} | {name} | {r['tier']} | {r['overall_score']} "
                         f"| {hl} | {loc} | {why} |")
        text = "\n".join(lines) + "\n"
    if out_path:
        open(out_path, "w").write(text)
        return out_path
    return text
