---
name: linkedin-recruiting
description: Triage people who applied to Zerg's LinkedIn job posts and surface the best to reach out to. Ingests applicants (account-free email digests + a burner-session Applicants UI pull), ranks them against a role profile and Zerg's bar, drafts outreach in Idan's voice, and files keepers as People/Recruiting/[Name].md. Use when reviewing LinkedIn job applicants, building a candidate shortlist, or processing the applicant backlog.
allowed-tools: Bash, Read
---

# linkedin-recruiting

Inbound LinkedIn applicant triage. LinkedIn has **no API** for applicants/messaging/search (2026), so this skill uses two account-safe channels and a local triage brain.

## CRITICAL safety
- **Outreach is DRAFTED, never sent.** Drafts live in the DB and the candidate page with a `drafted/sent/responded` checklist. Sending is always a human action.
- **Never use Idan's real account for the roster pull.** The Applicants-UI pull runs on a **burner** LinkedIn account that Idan adds as a Zerg page/job admin. Pacing is human-speed; on any login/checkpoint the run stops and screenshots evidence.

## Pipeline
```
email digests (account-free) ─┐
burner Applicants UI ─────────┴→ sqlite candidate store → triage (claude -p) → report
                                       → People/Recruiting/[Name].md + outreach draft
```

## Setup
```bash
python3 ~/.claude/skills/linkedin-recruiting/linkedin_recruiting.py init
# edit role_profiles/_default.json -> paste the real JD into "jd_text" (optional; a seeded bar exists)
```

## Channel A — email (account-free, run anytime)
```bash
python3 linkedin_recruiting.py ingest-email --account idan@zergai.com   # parse digests -> roles + previews
python3 linkedin_recruiting.py roles                                    # what we know per job
```
Digests give applicant counts + a handful of named previews (name/headline/location/applicant_id) per role. Idempotent.

## Channel B — burner Applicants UI (full roster + resumes)
Prereq, one time: create a burner LinkedIn account; **Idan adds it as a Zerg Company Page admin / job manager** (Page → Admin tools → Manage admins). Then:
```bash
python3 linkedin_recruiting.py login --visible      # sign the burner in (session persists)
python3 linkedin_recruiting.py ingest-applicants --role <job_id> --max 25 --visible
```
- `--max` caps applicants per run; the backlog is **resumable** across runs/days (progress in the DB). Pace is randomized (`--pace-min/--pace-max`).
- On a checkpoint/captcha it stops and saves a screenshot to `evidence/`; re-run `login`, then retry.
- Selectors are centralized in `lr/ingest_applicants.py`; the first real run captures html/screenshot evidence so any DOM tuning is offline. After a pull, re-run `triage` and `file`.

## Triage / report / file
```bash
python3 linkedin_recruiting.py triage [--role <job_id>] [--retriage]   # batch score vs role profile + Zerg bar
python3 linkedin_recruiting.py report [--role <job_id>] [--top 25]     # ranked shortlist (md/csv)
python3 linkedin_recruiting.py file --tier reach-out [--dry-run]       # write keepers to People/Recruiting/
python3 linkedin_recruiting.py status
```
- Scorecard axes match `templates/Interview Candidate.md` (Technical / Problem Solving / Communication / Cultural Fit / Growth Potential / Overall, 1-5). Tiers: reach-out ≥3.8, maybe ≥3.0, else pass (tunable in the role profile).
- Calibrated against `People/Recruiting/Franklin Yiu.md` (4.4 = strong hire) and the Marty negative signal (`Personas/Marty.md`).
- `file` instantiates the vault template, fills frontmatter + an idempotent `lr:auto` AI-Screen block (re-filing preserves human interview notes), and copies any resume to `People/Recruiting/[Name]Resume.pdf`.

## Data
- `recruiting.db` (sqlite): `roles`, `candidates` (deduped by `applicant_id` → profile URL → name+headline), `ingest_runs`, `events`.
- `resumes/`, `evidence/` — local only. PII stays on disk + in the vault.

## Notes
- Email previews are headline-only and skew to the generic applicant pool; the **burner pull (resumes + full profiles) is where triage gets sharp.**
- `enrich` is a Phase-5 stub. Outbound sourcing is out of scope (the schema reserves `channel='outbound'`).
- Posting jobs/content uses the separate official-API `linkedin-skill`.
