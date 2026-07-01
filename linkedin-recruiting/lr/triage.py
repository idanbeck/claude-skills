"""Batch triage: score candidates against the role profile via claude -p."""
import json

from . import config, store
from .claude_client import call_json

AXES = ["technical_skills", "problem_solving", "communication",
        "cultural_fit", "growth_potential"]


def load_profile(role_row=None, profile_path=None):
    if profile_path:
        return json.loads(open(profile_path).read())
    if role_row is not None and role_row["job_id"]:
        p = config.ROLE_PROFILE_DIR / f"{role_row['job_id']}.json"
        if p.exists():
            return json.loads(p.read_text())
    return json.loads((config.ROLE_PROFILE_DIR / "_default.json").read_text())


def _system_prompt(profile):
    tmpl = (config.PROMPTS_DIR / "triage_system.md").read_text()
    return (tmpl
            .replace("{ROLE_PROFILE_JSON}", json.dumps(profile, indent=2))
            .replace("{ANCHOR}", profile.get("calibration_anchor", "")))


def _clamp(x):
    try:
        return max(1.0, min(5.0, float(x)))
    except (TypeError, ValueError):
        return None


def _weighted_overall(scores, weights):
    vals = {a: _clamp(scores.get(a)) for a in AXES}
    usable = {a: v for a, v in vals.items() if v is not None}
    if not usable:
        return _clamp(scores.get("overall"))
    w = {a: float(weights.get(a, 1.0)) for a in usable}
    tot = sum(w.values()) or 1.0
    return round(sum(usable[a] * w[a] for a in usable) / tot, 2)


def _tier(overall, thresholds):
    ro = float(thresholds.get("reach_out", config.TIER_REACH_OUT))
    mb = float(thresholds.get("maybe", config.TIER_MAYBE))
    if overall is None:
        return "pass"
    if overall >= ro:
        return "reach-out"
    if overall >= mb:
        return "maybe"
    return "pass"


def _candidate_payload(row):
    return {
        "id": row["id"],
        "name": row["display_name"] or row["full_name"],
        "headline": row["headline"],
        "location": row["location"],
        "answers": store.jload(row["answers"], []),
        "resume_excerpt": (row["resume_text"] or "")[:4000] or None,
        "enrichment": store.jload(row["enrichment"], None),
    }


def run_triage(conn, role_ref=None, batch_size=5, limit=None, retriage=False,
               profile_path=None):
    role_row = store.role_by_ref(conn, role_ref) if role_ref else None
    role_id = role_row["id"] if role_row else None
    profile = load_profile(role_row, profile_path)
    weights = profile.get("scoring_weights", {})
    thresholds = profile.get("tier_thresholds", {})
    system = _system_prompt(profile)
    batch_tmpl = (config.PROMPTS_DIR / "triage_batch.tmpl").read_text()

    statuses = None if retriage else ("new", "enriched")
    rows = []
    q = "SELECT * FROM candidates WHERE 1=1"
    args = []
    if role_id is not None:
        q += " AND role_id=?"; args.append(role_id)
    if statuses:
        q += " AND status IN (%s)" % ",".join("?" * len(statuses)); args += list(statuses)
    q += " ORDER BY id ASC"
    if limit:
        q += " LIMIT ?"; args.append(limit)
    rows = conn.execute(q, args).fetchall()

    counts = {"scored": 0, "reach-out": 0, "maybe": 0, "pass": 0, "failed": 0,
              "candidates": len(rows)}
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        payload = [_candidate_payload(r) for r in batch]
        user = batch_tmpl.replace("{N}", str(len(payload))).replace(
            "{CANDIDATES_JSON}", json.dumps(payload, indent=2))
        result = call_json(system + "\n\n" + user)
        results = (result or {}).get("results") if isinstance(result, dict) else None
        by_id = {int(r.get("id")): r for r in results} if results else {}
        for r in batch:
            res = by_id.get(r["id"])
            if not res:
                counts["failed"] += 1
                continue
            scores = res.get("scores", {})
            overall = _weighted_overall(scores, weights)
            tier = _tier(overall, thresholds)
            score_json = {"axes": {a: _clamp(scores.get(a)) for a in AXES},
                          "model_overall": _clamp(scores.get("overall")),
                          "computed_overall": overall,
                          "red_flags": res.get("red_flags", [])}
            store.save_triage(conn, r["id"], score_json, overall, tier,
                              res.get("rationale", ""), res.get("outreach", "") or "")
            counts["scored"] += 1
            counts[tier] = counts.get(tier, 0) + 1
        conn.commit()
    return counts
