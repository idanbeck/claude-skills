"""Optional read-only enrichment (Phase 5).

Currently a safe no-op placeholder so the `enrich` command exists. Extend to pull
GitHub/website signal for triaged candidates (read-only; no account needed).
"""


def run_enrich(conn, role_ref=None, limit=None, only_tier=None):
    return {"enriched": 0, "note": "enrich is a Phase-5 stub; not yet implemented"}
