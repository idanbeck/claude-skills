#!/usr/bin/env python3
"""linkedin-recruiting — ingest LinkedIn applicants, triage them, file keepers to the vault.

Inbound applicant triage. Applicant roster comes from (a) account-free email digests and
(b) a BURNER LinkedIn session driving the Applicants UI. Outreach is DRAFTED, never sent.
See SKILL.md.
"""
import argparse
import json
import sys

from lr import config, store


def _out(data, as_json):
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    return data


# ---- handlers ---------------------------------------------------------------
def cmd_init(args, conn):
    store.init_db(args.db)
    config.RESUMES_DIR.mkdir(exist_ok=True)
    config.EVIDENCE_DIR.mkdir(exist_ok=True)
    print(f"initialized {args.db}")
    print(f"role profile: {config.ROLE_PROFILE_DIR / '_default.json'} "
          f"(edit jd_text to paste the real JD)")


def cmd_ingest_email(args, conn):
    from lr import ingest_email
    counts = ingest_email.ingest(conn, account=args.account, since=args.since,
                                 max_results=args.max_results, query=args.query,
                                 dry_run=args.dry_run)
    if args.json:
        _out(counts, True)
    else:
        print("ingest-email:", ", ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_roles(args, conn):
    rows = store.list_roles(conn)
    if args.json:
        return _out([dict(r) for r in rows], True)
    if not rows:
        print("no roles yet — run ingest-email")
        return
    print(f"{'job_id':<12} {'cand':>4} {'triaged':>7} {'filed':>5} {'cnt':>4} {'status':<7} title")
    for r in rows:
        print(f"{(r['job_id'] or '-'):<12} {r['n_cand']:>4} {r['n_triaged']:>7} "
              f"{r['n_filed']:>5} {(r['applicant_count'] or 0):>4} {(r['status'] or ''):<7} "
              f"{r['title'] or ''}")


def cmd_status(args, conn):
    roles = store.list_roles(conn)
    cand = conn.execute(
        "SELECT status, COUNT(*) n FROM candidates GROUP BY status").fetchall()
    runs = conn.execute(
        "SELECT kind, status, finished_at FROM ingest_runs ORDER BY id DESC LIMIT 6").fetchall()
    data = {
        "roles": len(roles),
        "candidates_by_status": {r["status"]: r["n"] for r in cand},
        "total_candidates": sum(r["n"] for r in cand),
        "recent_runs": [dict(r) for r in runs],
    }
    if args.json:
        return _out(data, True)
    print(f"roles: {data['roles']}  candidates: {data['total_candidates']}")
    for k, v in data["candidates_by_status"].items():
        print(f"  {k}: {v}")
    print("recent runs:")
    for r in runs:
        print(f"  {r['kind']:<14} {r['status']:<8} {r['finished_at'] or '(running)'}")


def cmd_reconcile(args, conn):
    n = store.reconcile(conn)
    print(f"reconciled (merged) {n} provisional candidate(s)")


def cmd_triage(args, conn):
    from lr import triage
    counts = triage.run_triage(conn, role_ref=args.role, batch_size=args.batch_size,
                               limit=args.limit, retriage=args.retriage,
                               profile_path=args.profile)
    print("triage:", ", ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_report(args, conn):
    from lr import report
    out = report.build_report(conn, role_ref=args.role, fmt=args.format,
                              out_path=args.out, tier=args.tier, top=args.top)
    if args.out:
        print(f"wrote {out}")
    else:
        print(out)


def cmd_file(args, conn):
    from lr import file_vault
    counts = file_vault.file_candidates(conn, role_ref=args.role, tier=args.tier,
                                        min_score=args.min_score, force=args.force,
                                        limit=args.limit, dry_run=args.dry_run)
    print("file:", ", ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_login(args, conn):
    from lr import ingest_applicants
    ingest_applicants.login(visible=args.visible)


def cmd_ingest_applicants(args, conn):
    from lr import ingest_applicants
    counts = ingest_applicants.ingest(conn, role_ref=args.role, all_open=args.all_open,
                                      max_n=args.max, pace=(args.pace_min, args.pace_max),
                                      visible=args.visible, want_resume=not args.no_resume,
                                      refresh=args.refresh)
    print("ingest-applicants:", ", ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_enrich(args, conn):
    from lr import enrich
    counts = enrich.run_enrich(conn, role_ref=args.role, limit=args.limit,
                               only_tier=args.only_tier)
    print("enrich:", ", ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_show(args, conn):
    row = conn.execute("SELECT * FROM candidates WHERE id=?", (args.candidate,)).fetchone()
    print(json.dumps(dict(row) if row else {}, indent=2, default=str))


def cmd_run(args, conn):
    from lr import ingest_email
    print("== ingest-email ==")
    print(ingest_email.ingest(conn, account=args.account))
    print("== reconcile ==")
    print(store.reconcile(conn), "merged")
    from lr import triage, report
    print("== triage ==")
    print(triage.run_triage(conn))
    print("== report ==")
    print(report.build_report(conn, fmt="md"))


# ---- argparse ---------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="linkedin-recruiting")
    p.add_argument("--db", default=str(config.DB_PATH))
    p.add_argument("--json", action="store_true")
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    sp = sub.add_parser("ingest-email")
    sp.add_argument("--account", default=config.DEFAULT_GMAIL_ACCOUNT)
    sp.add_argument("--since", help="Gmail date YYYY/MM/DD")
    sp.add_argument("--max-results", type=int, default=100)
    sp.add_argument("--query")
    sp.add_argument("--dry-run", action="store_true")

    sub.add_parser("roles")
    sub.add_parser("status")
    sub.add_parser("reconcile")

    sp = sub.add_parser("triage")
    sp.add_argument("--role")
    sp.add_argument("--batch-size", type=int, default=5)
    sp.add_argument("--limit", type=int)
    sp.add_argument("--retriage", action="store_true")
    sp.add_argument("--profile", help="path to a role_profile json override")

    sp = sub.add_parser("report")
    sp.add_argument("--role")
    sp.add_argument("--format", choices=["md", "csv"], default="md")
    sp.add_argument("--out")
    sp.add_argument("--tier")
    sp.add_argument("--top", type=int)

    sp = sub.add_parser("file")
    sp.add_argument("--role")
    sp.add_argument("--tier", default="reach-out")
    sp.add_argument("--min-score", type=float)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("login")
    sp.add_argument("--visible", action="store_true", default=True)

    sp = sub.add_parser("ingest-applicants")
    sp.add_argument("--role")
    sp.add_argument("--all-open", action="store_true")
    sp.add_argument("--max", type=int, default=25)
    sp.add_argument("--pace-min", type=int, default=config.PACE_MIN)
    sp.add_argument("--pace-max", type=int, default=config.PACE_MAX)
    sp.add_argument("--visible", action="store_true")
    sp.add_argument("--no-resume", action="store_true")
    sp.add_argument("--refresh", action="store_true")

    sp = sub.add_parser("enrich")
    sp.add_argument("--role")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--only-tier")

    sp = sub.add_parser("run")
    sp.add_argument("--account", default=config.DEFAULT_GMAIL_ACCOUNT)

    sp = sub.add_parser("show")
    sp.add_argument("--candidate", type=int, required=True)

    args = p.parse_args()
    conn = store.get_conn(args.db)
    handlers = {
        "init": cmd_init, "ingest-email": cmd_ingest_email, "roles": cmd_roles,
        "status": cmd_status, "reconcile": cmd_reconcile, "triage": cmd_triage,
        "report": cmd_report, "file": cmd_file, "login": cmd_login,
        "ingest-applicants": cmd_ingest_applicants, "enrich": cmd_enrich,
        "show": cmd_show, "run": cmd_run,
    }
    try:
        handlers[args.cmd](args, conn)
    finally:
        conn.commit()
        conn.close()


if __name__ == "__main__":
    main()
