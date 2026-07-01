"""Account-free ingest: parse LinkedIn job-applicant digest emails -> roles + previews."""
import re
import sys

from . import config, store
from .shell import run_json

PY = sys.executable or "python3"

DETAIL_RE = re.compile(r"/applicants/(\d+)/detail/")
JOBID_RE = re.compile(r"/hiring/jobs/(\d+)/")
COUNT_RE = re.compile(r"(\d+)\s+(?:new\s+)?applicants?", re.I)
TITLE_SUBJ_RE = re.compile(r"for your job:\s*(.+?)\s*$", re.I)
CLOSED_RE = re.compile(r"\b(closed|paused|expired)\b", re.I)
BOILER_RE = re.compile(
    r"^(your job|view all applicants?|see all|view in|unsubscribe|this email|"
    r"linkedin (corp|is)|get the|©|sent to|you are receiving|help center|manage your|"
    r"new applicants?\b)", re.I)


def parse_previews(body: str):
    """Each preview is name/headline/location followed by a /applicants/{id}/detail/ URL."""
    out, buf = [], []
    for raw in body.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.lower().startswith("http"):
            m = DETAIL_RE.search(s)
            if m and buf:
                blk = buf[-3:]
                out.append({
                    "applicant_id": m.group(1),
                    "name": blk[0],
                    "headline": blk[1] if len(blk) > 1 else None,
                    "location": blk[2] if len(blk) > 2 else None,
                    "detail_url": s.split("?", 1)[0],
                })
            buf = []
            continue
        if BOILER_RE.match(s):
            buf = []
            continue
        buf.append(s)
    seen, uniq = set(), []
    for a in out:
        if a["applicant_id"] in seen:
            continue
        seen.add(a["applicant_id"])
        uniq.append(a)
    return uniq


def _extract_meta(subject, body):
    job_ids = JOBID_RE.findall(body) or JOBID_RE.findall(subject)
    job_id = job_ids[0] if job_ids else None
    tm = TITLE_SUBJ_RE.search(subject)
    title = tm.group(1) if tm else None
    if not title:
        bm = re.search(r"^(.*?)\s+at\s+Zerg AI", body, re.M)
        title = bm.group(1).strip() if bm else None
    cm = COUNT_RE.search(subject) or COUNT_RE.search(body)
    count = int(cm.group(1)) if cm else None
    status = "closed" if CLOSED_RE.search(subject) else "open"
    return job_id, title, count, status


def ingest(conn, account=None, since=None, max_results=100, query=None, dry_run=False):
    account = account or config.DEFAULT_GMAIL_ACCOUNT
    q = query or config.DIGEST_QUERY
    if since:
        q += f" after:{since}"
    run_id = None if dry_run else store.start_run(conn, "email")
    counts = {"emails": 0, "roles": 0, "new": 0, "updated": 0, "skipped_seen": 0, "no_jobid": 0}
    roles_touched = set()

    res = run_json([PY, config.GMAIL_SKILL, "search", q, "--account", account,
                    "--max-results", max_results])
    results = (res or {}).get("results", [])
    for r in results:
        eid, subj = r.get("id"), r.get("subject", "")
        if not dry_run and store.email_seen(conn, eid):
            counts["skipped_seen"] += 1
            continue
        full = run_json([PY, config.GMAIL_SKILL, "read", eid, "--account", account,
                         "--format", "full"])
        body = (full or {}).get("body", "") or ""
        job_id, title, count, status = _extract_meta(subj, body)
        if not job_id:
            counts["no_jobid"] += 1
            if not dry_run:
                store.mark_email_seen(conn, eid, "no-jobid")
            continue
        previews = parse_previews(body)
        if dry_run:
            print(f"[dry] {subj[:55]!r} -> job={job_id} title={title!r} "
                  f"count={count} status={status} previews={len(previews)}", file=sys.stderr)
            for a in previews[:4]:
                print(f"        - {a['name']} | {a['headline']} | {a['location']} "
                      f"| aid={a['applicant_id']}", file=sys.stderr)
            counts["emails"] += 1
            continue

        role_id = store.upsert_role(conn, job_id, title=title,
                                    applicant_count=count, status=status)
        roles_touched.add(role_id)
        for a in previews:
            res2 = store.upsert_candidate(
                conn, role_id, applicant_id=a["applicant_id"], detail_url=a["detail_url"],
                display_name=a["name"], headline=a["headline"], location=a["location"],
                source="email_preview")
            counts["new" if res2 == "new" else "updated"] += 1
        store.mark_email_seen(conn, eid, f"job={job_id}")
        counts["emails"] += 1
        conn.commit()

    counts["roles"] = len(roles_touched)
    if run_id is not None:
        store.finish_run(conn, run_id, "ok", counts)
    return counts
