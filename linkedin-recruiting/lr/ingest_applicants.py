"""Burner-session applicants-UI adapter (in-process Playwright).

Drives a BURNER LinkedIn account (added by Idan as a Zerg page/job admin) through the
native Applicants UI to pull the full roster + resumes that no API and no email exposes.

Lifecycle note: the sibling playwright-skill only persists cookies (not the live page)
across CLI calls, so we drive Playwright directly here — one page stays alive for the
whole run, so navigation -> extract works. Cookies persist to config.BURNER_STATE.

Read-only, human-paced, resumable. Selectors are centralized below and may need a one-time
tuning pass against the live DOM — every miss captures html/screenshot evidence so that
tuning is offline.
"""
import base64
import json
import random
import sys
import time

from . import config, store

STATE = config.BURNER_STATE

# ---- JS payloads (resilient, multi-selector) --------------------------------
JS_ENUMERATE = r"""
(() => {
  const out = []; const seen = new Set();
  document.querySelectorAll('a[href*="/applicants/"]').forEach(a => {
    const m = (a.href||'').match(/\/applicants\/(\d+)\//);
    if (!m) return; const aid = m[1];
    if (seen.has(aid)) return; seen.add(aid);
    const name = (a.getAttribute('aria-label')||a.textContent||'').trim().replace(/\s+/g,' ');
    out.push({aid, href: a.href.split('?')[0], name: name.slice(0,120)});
  });
  return out;
})()
"""

JS_SCROLL_LIST = r"""
(() => {
  const cands = Array.from(document.querySelectorAll('*')).filter(e => {
    const s = getComputedStyle(e);
    return (s.overflowY==='auto'||s.overflowY==='scroll') && e.scrollHeight > e.clientHeight+40;
  }).sort((a,b)=>b.scrollHeight-a.scrollHeight);
  const el = cands[0] || document.scrollingElement || document.body;
  const before = el.scrollTop;
  el.scrollTop = before + Math.round(600 + Math.random()*400);
  window.scrollBy(0, 500);
  return {scrolled: el.scrollTop - before, scrollTop: el.scrollTop, scrollHeight: el.scrollHeight};
})()
"""

JS_DETAIL = r"""
(() => {
  const t = el => el ? (el.textContent||'').trim().replace(/\s+/g,' ') : null;
  const q = sels => { for (const s of sels){ const e=document.querySelector(s); if(e) return e; } return null; };
  const name = t(q(['h1','.artdeco-entity-lockup__title','[class*="profile-card"] [class*="name"]']));
  const headline = t(q(['.artdeco-entity-lockup__subtitle','[class*="headline"]']));
  const location = t(q(['.artdeco-entity-lockup__caption','[class*="location"]']));
  let profile = null;
  const pl = document.querySelector('a[href*="linkedin.com/in/"], a[href*="/in/"]');
  if (pl) profile = pl.href.split('?')[0];
  const answers = [];
  document.querySelectorAll('[class*="screening"], [class*="question-card"], [class*="qualification"]').forEach(b => {
    const qq = t(b.querySelector('[class*="question"], h3, dt, strong'));
    const aa = t(b.querySelector('[class*="answer"], p, dd, span'));
    if (qq || aa) answers.push({question: qq, answer: aa});
  });
  let contact = null;
  const cblk = q(['[class*="contact-info"]','[class*="contact"]']);
  if (cblk) {
    const txt = cblk.innerText || '';
    const em = txt.match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
    const ph = txt.match(/(\+?\d[\d\s().-]{7,}\d)/);
    if (em || ph) contact = {email: em ? em[0] : null, phone: ph ? ph[0] : null};
  }
  let resume = null;
  const rl = document.querySelector('a[href*="resume"], a[download], a[href*="/dms/"], a[href*="ambry"]');
  if (rl) resume = rl.href;
  return {name, headline, location, profile, answers, contact, resume};
})()
"""

JS_FETCH_B64 = r"""
(async () => {
  try {
    const r = await fetch(%URL%, {credentials:'include'});
    if (!r.ok) return {ok:false, err:'http '+r.status};
    const buf = await r.arrayBuffer(); const bytes = new Uint8Array(buf);
    let bin=''; const CH=0x8000;
    for (let i=0;i<bytes.length;i+=CH) bin += String.fromCharCode.apply(null, bytes.subarray(i,i+CH));
    return {ok:true, b64: btoa(bin), type: r.headers.get('content-type')||''};
  } catch (e) { return {ok:false, err:String(e)}; }
})()
"""


def _is_blocked(url):
    u = (url or "").lower()
    return any(k in u for k in ("/login", "/checkpoint", "/uas/", "/authwall", "/captcha"))


class Burner:
    """In-process Playwright browser keyed to the burner's saved cookies."""
    def __init__(self, headless=True):
        self.headless = headless
        self._p = self._b = self.ctx = self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self._b = self._p.chromium.launch(headless=self.headless)
        self.ctx = self._b.new_context(
            storage_state=str(STATE) if STATE.exists() else None,
            viewport={"width": 1400, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"))
        self.page = self.ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self.ctx:
                self.ctx.storage_state(path=str(STATE))
        except Exception:
            pass
        try:
            self._b and self._b.close()
            self._p and self._p.stop()
        except Exception:
            pass

    def goto(self, url):
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.5, 3.0))
        return self.page.url

    def js(self, code):
        try:
            return self.page.evaluate(code)
        except Exception as e:  # noqa: BLE001
            print(f"[burner.js] {e}", file=sys.stderr)
            return None

    def evidence(self, tag):
        config.EVIDENCE_DIR.mkdir(exist_ok=True)
        png = config.EVIDENCE_DIR / f"{tag}.png"
        html = config.EVIDENCE_DIR / f"{tag}.html"
        try:
            self.page.screenshot(path=str(png), full_page=True)
            html.write_text(self.page.content())
        except Exception:
            pass
        return str(png), str(html)


def login(visible=True):
    """Headed sign-in for the burner; saves cookies to config.BURNER_STATE."""
    from playwright.sync_api import sync_playwright
    print("Opening a browser. Sign in with the BURNER account, reach your feed, "
          "then come back here.", file=sys.stderr)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        ctx = b.new_context(storage_state=str(STATE) if STATE.exists() else None)
        page = ctx.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        try:
            input("Press Enter once you are signed in (on your LinkedIn feed)... ")
        except EOFError:
            time.sleep(60)
        ctx.storage_state(path=str(STATE))
        url = page.url
        b.close()
    ok = ("feed" in url or "/in/" in url) and not _is_blocked(url)
    print(json.dumps({"saved_state": str(STATE), "current_url": url, "logged_in": ok,
                      "next": "Idan must add this burner as a Zerg Company Page admin / "
                              "job manager so it can see applicants, then run ingest-applicants."},
                     indent=2))


def _enumerate(br, job_id, expected, max_n):
    url = f"https://www.linkedin.com/hiring/jobs/{job_id}/applicants/"
    cur = br.goto(url)
    if _is_blocked(cur):
        png, _ = br.evidence(f"blocked_{job_id}")
        return None, "blocked", png
    acc, stable = {}, 0
    for _ in range(60):
        for a in (br.js(JS_ENUMERATE) or []):
            acc.setdefault(a["aid"], a)
        if (max_n and len(acc) >= max_n) or (expected and len(acc) >= expected):
            break
        n_before = len(acc)
        br.js(JS_SCROLL_LIST)
        time.sleep(random.uniform(2.0, 4.0))
        stable = stable + 1 if len(acc) == n_before else 0
        if stable >= 2:
            break
    status = "partial" if (expected and len(acc) < expected) else "ok"
    return list(acc.values()), status, None


def _extract(br, job_id, aid, want_resume):
    cur = br.goto(f"https://www.linkedin.com/hiring/jobs/{job_id}/applicants/{aid}/detail/")
    if _is_blocked(cur):
        return None, "blocked"
    data = br.js(JS_DETAIL) or {}
    if not data.get("name"):
        png, html = br.evidence(f"applicant_{aid}")
        data["_evidence_png"], data["_evidence_html"] = png, html
    if want_resume and data.get("resume"):
        res = br.js(JS_FETCH_B64.replace("%URL%", json.dumps(data["resume"])))
        if res and res.get("ok"):
            try:
                path = config.RESUMES_DIR / f"{job_id}_{aid}.pdf"
                path.write_bytes(base64.b64decode(res["b64"]))
                data["_resume_path"] = str(path)
            except (ValueError, OSError):
                pass
    return data, "ok"


def ingest(conn, role_ref=None, all_open=False, max_n=25, pace=(6, 15),
           visible=False, want_resume=True, refresh=False):
    config.RESUMES_DIR.mkdir(exist_ok=True)
    config.EVIDENCE_DIR.mkdir(exist_ok=True)
    if not STATE.exists():
        return {"error": "burner not logged in — run `login` first"}

    if all_open:
        roles = [r for r in store.list_roles(conn) if (r["status"] or "open") == "open"]
    elif role_ref:
        r = store.role_by_ref(conn, role_ref)
        roles = [r] if r else []
    else:
        roles = store.list_roles(conn)
    roles = [r for r in roles if r and r["job_id"]]
    if not roles:
        return {"error": "no matching roles — run ingest-email or pass --role"}

    totals = {"roles": 0, "enumerated": 0, "extracted": 0, "resumes": 0,
              "new": 0, "updated": 0, "blocked": 0, "merged": 0}
    with Burner(headless=not visible) as br:
        for role in roles:
            job_id = role["job_id"]
            run_id = store.start_run(conn, "applicants_ui", role["id"])
            listing, status, ev = _enumerate(br, job_id, role["applicant_count"], max_n)
            if status == "blocked":
                store.finish_run(conn, run_id, "blocked",
                                 {"note": "checkpoint/login"}, error=ev)
                totals["blocked"] += 1
                print(f"role {job_id}: BLOCKED (login/checkpoint). Evidence {ev}. "
                      f"Run `login` + retry.", file=sys.stderr)
                break
            listing = listing or []
            totals["enumerated"] += len(listing)
            for a in listing:   # seed roster (thin) from enumeration
                store.upsert_candidate(conn, role["id"], applicant_id=a["aid"],
                                       detail_url=a["href"], display_name=a["name"],
                                       source="email_preview")
            conn.commit()

            need = conn.execute(
                "SELECT applicant_id FROM candidates WHERE role_id=? AND applicant_id IS NOT NULL "
                "AND (extracted_at IS NULL OR source!='applicants_ui' OR ?) ORDER BY id",
                (role["id"], 1 if refresh else 0)).fetchall()
            aids = [r["applicant_id"] for r in need][:max_n]
            for i, aid in enumerate(aids):
                data, st = _extract(br, job_id, aid, want_resume)
                if st == "blocked":
                    store.finish_run(conn, run_id, "blocked", totals, error="checkpoint mid-run")
                    totals["blocked"] += 1
                    print(f"role {job_id}: BLOCKED mid-extract; resumable on re-run.",
                          file=sys.stderr)
                    return totals
                if data:
                    res = store.upsert_candidate(
                        conn, role["id"], applicant_id=aid,
                        profile_url=data.get("profile"), full_name=data.get("name"),
                        display_name=data.get("name"), headline=data.get("headline"),
                        location=data.get("location"), answers=data.get("answers") or None,
                        contact=data.get("contact"), resume_path=data.get("_resume_path"),
                        resume_downloaded=bool(data.get("_resume_path")),
                        source="applicants_ui")
                    totals["extracted"] += 1
                    totals["new" if res == "new" else "updated"] += 1
                    if data.get("_resume_path"):
                        totals["resumes"] += 1
                conn.commit()
                time.sleep(random.uniform(*pace))
                if (i + 1) % config.PACE_BIG_EVERY == 0:
                    time.sleep(random.uniform(config.PACE_BIG_MIN, config.PACE_BIG_MAX))
            store.finish_run(conn, run_id, status,
                             {"enumerated": len(listing), "extracted": len(aids)})
            totals["roles"] += 1
    totals["merged"] = store.reconcile(conn)
    return totals
