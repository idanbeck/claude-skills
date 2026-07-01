"""SQLite store: schema, dedup/normalization, idempotent upserts, reconcile."""
import json
import re
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY,
  job_id TEXT UNIQUE,
  title TEXT,
  source TEXT,                 -- email | manual
  applicant_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open',  -- open | closed
  first_seen TEXT, last_seen TEXT,
  raw_meta TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY,
  role_id INTEGER REFERENCES roles(id),
  dedup_key TEXT UNIQUE,
  applicant_id TEXT,           -- LinkedIn job-applicant id (from detail URL) when known
  detail_url TEXT,
  channel TEXT DEFAULT 'inbound',   -- 'outbound' reserved for future sourcing
  campaign_id TEXT,
  profile_url TEXT, profile_url_norm TEXT,
  full_name TEXT, display_name TEXT,
  headline TEXT, location TEXT,
  source TEXT,                 -- email_preview | applicants_ui
  provisional INTEGER DEFAULT 0,
  answers TEXT,                -- JSON [{question,answer}]
  contact TEXT,                -- JSON {email,phone} (null unless shared)
  resume_path TEXT, resume_downloaded INTEGER DEFAULT 0, resume_text TEXT,
  enrichment TEXT,             -- JSON {github,website,notes}
  score_json TEXT,             -- JSON full scorecard incl. profile_hash
  overall_score REAL, tier TEXT,
  rationale TEXT, outreach_draft TEXT,
  status TEXT DEFAULT 'new',   -- new|enriched|triaged|filed|skipped|blocked
  evidence_html TEXT, evidence_png TEXT,
  filed_path TEXT,
  triaged_at TEXT, extracted_at TEXT, first_seen TEXT, last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_cand_role ON candidates(role_id);
CREATE INDEX IF NOT EXISTS idx_cand_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_cand_aid ON candidates(applicant_id);

CREATE TABLE IF NOT EXISTS ingest_runs (
  id INTEGER PRIMARY KEY,
  kind TEXT, role_id INTEGER,
  started_at TEXT, finished_at TEXT,
  status TEXT, counts TEXT, notes TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  candidate_id INTEGER, email_id TEXT,
  ts TEXT, kind TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_email ON events(email_id);
"""


def iso():
    return datetime.now(timezone.utc).isoformat()


def jdump(v):
    return json.dumps(v) if v is not None else None


def jload(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


def get_conn(db_path=None):
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---- normalization / dedup --------------------------------------------------
def slugify(s):
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s.strip("-")


def normalize_url(url):
    """Canonical LinkedIn profile -> linkedin.com/in/{slug} (lowercased, no query)."""
    if not url:
        return None
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    m = re.search(r"linkedin\.com/in/([^/]+)", u)
    if m:
        return f"linkedin.com/in/{m.group(1)}"
    return u or None


def dedup_key_for(applicant_id, profile_url_norm, name, headline):
    if applicant_id:
        return f"aid:{applicant_id}"
    if profile_url_norm:
        slug = profile_url_norm.rsplit("/in/", 1)[-1]
        return f"url:{slug}"
    return f"prov:{slugify(name)}|{slugify((headline or '')[:40])}"


# ---- roles ------------------------------------------------------------------
def upsert_role(conn, job_id, title=None, applicant_count=None, source="email",
                status="open", raw_meta=None):
    now = iso()
    row = conn.execute("SELECT * FROM roles WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO roles (job_id,title,source,applicant_count,status,
                                  first_seen,last_seen,raw_meta)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, title, source, applicant_count or 0, status, now, now,
             jdump(raw_meta)))
        return conn.execute("SELECT id FROM roles WHERE job_id=?", (job_id,)).fetchone()["id"]
    # merge: keep max count, fill title if empty, bump last_seen
    new_count = max(row["applicant_count"] or 0, applicant_count or 0)
    new_title = row["title"] or title
    conn.execute(
        "UPDATE roles SET title=?, applicant_count=?, last_seen=? WHERE id=?",
        (new_title, new_count, now, row["id"]))
    return row["id"]


# ---- candidates -------------------------------------------------------------
_UPGRADEABLE = ("full_name", "display_name", "headline", "location",
                "profile_url", "profile_url_norm", "detail_url", "applicant_id")


def upsert_candidate(conn, role_id, *, applicant_id=None, detail_url=None,
                     profile_url=None, full_name=None, display_name=None,
                     headline=None, location=None, source="email_preview",
                     answers=None, contact=None, resume_path=None,
                     resume_downloaded=None, resume_text=None):
    """Insert or merge a candidate. Never downgrades a richer record with thinner data.
    Returns 'new' | 'updated'."""
    now = iso()
    purl_norm = normalize_url(profile_url)
    key = dedup_key_for(applicant_id, purl_norm, display_name or full_name, headline)
    provisional = 0 if (applicant_id or purl_norm) else 1
    is_ui = source == "applicants_ui"

    row = conn.execute("SELECT * FROM candidates WHERE dedup_key=?", (key,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO candidates
               (role_id,dedup_key,applicant_id,detail_url,profile_url,profile_url_norm,
                full_name,display_name,headline,location,source,provisional,
                answers,contact,resume_path,resume_downloaded,resume_text,
                status,first_seen,last_seen,extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'new', ?, ?, ?)""",
            (role_id, key, applicant_id, detail_url, profile_url, purl_norm,
             full_name, display_name, headline, location, source, provisional,
             jdump(answers), jdump(contact), resume_path,
             1 if resume_downloaded else 0, resume_text,
             now, now, now if is_ui else None))
        return "new"

    incoming = dict(applicant_id=applicant_id, detail_url=detail_url,
                    profile_url=profile_url, profile_url_norm=purl_norm,
                    full_name=full_name, display_name=display_name,
                    headline=headline, location=location)
    sets, vals = [], []
    for f in _UPGRADEABLE:
        new_v = incoming.get(f)
        if new_v in (None, ""):
            continue
        cur_v = row[f]
        # fill if empty; UI source may overwrite thin email-preview values
        if cur_v in (None, "") or is_ui:
            sets.append(f"{f}=?")
            vals.append(new_v)
    # richer JSON / resume fields only ever arrive from UI
    if answers:
        sets.append("answers=?"); vals.append(jdump(answers))
    if contact:
        sets.append("contact=?"); vals.append(jdump(contact))
    if resume_path:
        sets.append("resume_path=?"); vals.append(resume_path)
        sets.append("resume_downloaded=?"); vals.append(1 if resume_downloaded else 0)
    if resume_text:
        sets.append("resume_text=?"); vals.append(resume_text)
    if is_ui:
        sets.append("source=?"); vals.append("applicants_ui")
        sets.append("provisional=?"); vals.append(0)
        sets.append("extracted_at=?"); vals.append(now)
    sets.append("last_seen=?"); vals.append(now)
    vals.append(row["id"])
    conn.execute(f"UPDATE candidates SET {', '.join(sets)} WHERE id=?", vals)
    return "updated"


def reconcile(conn):
    """Merge provisional (name|headline) rows into identified rows of the same role
    when a confident match exists. Identified rows win. Returns merge count."""
    merged = 0
    provs = conn.execute(
        "SELECT * FROM candidates WHERE provisional=1").fetchall()
    for p in provs:
        if not p["full_name"] and not p["display_name"]:
            continue
        nm = slugify(p["display_name"] or p["full_name"])
        hd = slugify((p["headline"] or "")[:40])
        cand = conn.execute(
            """SELECT * FROM candidates WHERE provisional=0 AND role_id=?
               AND id!=? AND (
                 lower(display_name) LIKE ? OR lower(full_name) LIKE ?
               )""",
            (p["role_id"], p["id"], f"{nm.split('-')[0]}%", f"{nm.split('-')[0]}%")
        ).fetchall()
        match = None
        for c in cand:
            if slugify((c["headline"] or "")[:40]) == hd and hd:
                match = c
                break
        if not match:
            continue
        # fold any non-null prov fields into match where match is empty, then delete prov
        for f in ("answers", "contact", "resume_path", "resume_text"):
            if (match[f] in (None, "")) and p[f]:
                conn.execute(f"UPDATE candidates SET {f}=? WHERE id=?", (p[f], match["id"]))
        conn.execute("INSERT INTO events (candidate_id,ts,kind,detail) VALUES (?,?,?,?)",
                     (match["id"], iso(), "merge", f"absorbed provisional id={p['id']}"))
        conn.execute("DELETE FROM candidates WHERE id=?", (p["id"],))
        merged += 1
    conn.commit()
    return merged


# ---- runs / events ----------------------------------------------------------
def start_run(conn, kind, role_id=None):
    cur = conn.execute(
        "INSERT INTO ingest_runs (kind,role_id,started_at,status) VALUES (?,?,?,?)",
        (kind, role_id, iso(), "running"))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, status, counts=None, notes=None, error=None):
    conn.execute(
        "UPDATE ingest_runs SET finished_at=?,status=?,counts=?,notes=?,error=? WHERE id=?",
        (iso(), status, jdump(counts), notes, error, run_id))
    conn.commit()


def email_seen(conn, email_id):
    return conn.execute(
        "SELECT 1 FROM events WHERE email_id=? AND kind='email_read' LIMIT 1",
        (email_id,)).fetchone() is not None


def mark_email_seen(conn, email_id, detail=None):
    conn.execute("INSERT INTO events (email_id,ts,kind,detail) VALUES (?,?,?,?)",
                 (email_id, iso(), "email_read", detail))


# ---- queries ----------------------------------------------------------------
def list_roles(conn):
    return conn.execute("""
        SELECT r.*,
          (SELECT COUNT(*) FROM candidates c WHERE c.role_id=r.id) AS n_cand,
          (SELECT COUNT(*) FROM candidates c WHERE c.role_id=r.id AND c.status='triaged') AS n_triaged,
          (SELECT COUNT(*) FROM candidates c WHERE c.role_id=r.id AND c.status='filed') AS n_filed
        FROM roles r ORDER BY r.last_seen DESC""").fetchall()


def role_by_ref(conn, ref):
    """Resolve a role by job_id or numeric id."""
    row = conn.execute("SELECT * FROM roles WHERE job_id=?", (str(ref),)).fetchone()
    if row:
        return row
    if str(ref).isdigit():
        return conn.execute("SELECT * FROM roles WHERE id=?", (int(ref),)).fetchone()
    return None


def list_candidates(conn, role_id=None, status=None, tier=None, min_score=None,
                    order="overall_score DESC NULLS LAST, id ASC", limit=None):
    q = "SELECT * FROM candidates WHERE 1=1"
    args = []
    if role_id is not None:
        q += " AND role_id=?"; args.append(role_id)
    if status:
        q += " AND status=?"; args.append(status)
    if tier:
        q += " AND tier=?"; args.append(tier)
    if min_score is not None:
        q += " AND overall_score>=?"; args.append(min_score)
    q += f" ORDER BY {order}"
    if limit:
        q += " LIMIT ?"; args.append(limit)
    return conn.execute(q, args).fetchall()


def save_triage(conn, cand_id, score_json, overall, tier, rationale, outreach):
    conn.execute(
        """UPDATE candidates SET score_json=?,overall_score=?,tier=?,rationale=?,
           outreach_draft=?,status='triaged',triaged_at=? WHERE id=?""",
        (jdump(score_json), overall, tier, rationale, outreach, iso(), cand_id))


def mark_filed(conn, cand_id, path):
    conn.execute("UPDATE candidates SET status='filed', filed_path=? WHERE id=?",
                 (str(path), cand_id))
