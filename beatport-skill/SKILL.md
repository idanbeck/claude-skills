---
name: beatport-skill
description: Search Beatport, read your library/purchases/downloads, match a Spotify or YouTube crate to buyable Beatport tracks with BPM and key, and prep a harmonically-ordered DJ set for Ableton. Use when Idan wants to find tracks on Beatport, price out what to buy for a set, check what he already owns, or organize downloaded files into a set order. Builds a costed purchase plan; Idan does the actual checkout.
allowed-tools: Bash, Read
---

# Beatport (crate matching, purchase planning, set prep)

Turn tracks earmarked in Spotify/YouTube into a costed Beatport buy list, then into a
harmonically-ordered folder Ableton can chew on.

**This skill never buys anything.** It produces a reviewed plan and a list of URLs; Idan
completes checkout in his browser.

## Hard rules (do not skip)

1. **No purchases, ever.** There is no `buy` command and you must not add one, drive a
   checkout with browser automation, or enter card details. `plan` ends the automated part
   of the job. Hand Idan the list, the total, and the URLs.
2. **Never handle the Beatport password.** `POST /v4/auth/login/` accepts username+password
   and it *works* — do not use it. Auth is a bearer token Idan pastes, or PKCE. If a login
   is needed, ask him to do it in his browser.
3. **Show the total before he opens the cart.** `plan` prints per-track prices and an
   estimated total. Beatport returns prices in different units across endpoints, so the
   plan reports both `estimated_total` and `estimated_total_raw_sum` — if they disagree,
   say the total is unverified rather than quoting a number confidently.
4. **Never auto-buy an ambiguous match.** `match` sorts results into three piles;
   `needs_review_before_buying` means the matcher found a plausible-but-uncertain track.
   Show those to Idan with the alternatives and let him pick. Buying the wrong remix is
   the expensive, annoying mistake this skill exists to prevent.
5. **Check `already_owned` first.** Run `purchases`/`library` before planning a buy so he
   isn't re-buying tracks. Beatport will happily sell the same track twice.
6. **Don't invent endpoints.** The `/my/*` surface is not publicly documented. Use `probe`
   and `spec` to find what actually works on his account, then `get` that path. If a
   listing command fails, discover — don't guess a path and report its 404 as "no data".

## How Beatport is actually reachable (verified 2026-08-27)

Two planes, and mixing them up is the main way this goes wrong:

- **`api.beatport.com/v4` — scriptable.** Answers clean JSON, returns `401
  {"detail":"Authentication credentials were not provided."}` unauthenticated. **No
  Cloudflare challenge.** Everything this skill does goes here.
- **`www.beatport.com` — not scriptable.** Returns a Cloudflare "Just a moment..."
  interstitial to plain HTTP clients, including `/api/auth/session`. Anything on `www.`
  (cart, checkout, the downloads page) needs a real browser — Idan's, or `playwright-skill`
  with a persistent session. Do not try to curl it and do not report the Cloudflare page
  as "Beatport is down".

Other verified facts:
- `GET /v4/auth/o/authorize/` 302s to `/v4/auth/login/` when the browser has no Beatport
  session — so PKCE only completes if Idan is already logged in.
- `POST /v4/auth/o/token/` returns `{"error":"invalid_client"}` for an unregistered
  `client_id`. PKCE therefore needs a real registered client; without one, use a pasted
  bearer token.
- `GET /v4/swagger-ui/json/` is the OpenAPI spec and **it is itself auth-gated**. Once
  authenticated it is the authoritative endpoint list — that is what `spec` fetches.

## Setup

Two modes. Start with (a); it works today with no partner approval.

**(a) Pasted bearer token** — Idan opens beatport.com logged in, DevTools > Network, clicks
any `api.beatport.com` request, copies the `Authorization` header value after `Bearer `:

```bash
python3 ~/.claude/skills/beatport-skill/beatport_skill.py setup --token 'eyJ...'
```

Tokens are short-lived. On a 401 the skill tells him exactly how to grab a fresh one — ask,
don't retry in a loop.

**(b) Registered API client** (Beatport partner portal), which gets auto-refresh:

```bash
python3 ~/.claude/skills/beatport-skill/beatport_skill.py setup --client-id YOUR_ID
python3 ~/.claude/skills/beatport-skill/beatport_skill.py login
```

Then confirm and discover the account's real endpoints:

```bash
python3 ~/.claude/skills/beatport-skill/beatport_skill.py auth-status
python3 ~/.claude/skills/beatport-skill/beatport_skill.py probe
python3 ~/.claude/skills/beatport-skill/beatport_skill.py spec --grep my
```

`probe` tries a list of candidate `/my/*` paths, records which return 200 in `cache.json`,
and the listing commands then use only the paths known to work. **Run it once per account
before the first `library`/`purchases`/`downloads` call.**

## Commands

### Discovery and raw access
```bash
beatport_skill.py auth-status                  # is the token good, whose account
beatport_skill.py probe                        # which /my/ endpoints work (caches result)
beatport_skill.py spec [--grep my]             # authoritative OpenAPI path list
beatport_skill.py get /my/downloads/ --param per_page=10   # raw authenticated GET
```

### Catalog
```bash
beatport_skill.py search "artist track" [--limit 20] [--type tracks|releases|artists]
beatport_skill.py track TRACK_ID               # BPM, key, Camelot, label, price, URL
```

### Your account
```bash
beatport_skill.py library [--all]              # saved / My Beatport tracks
beatport_skill.py purchases [--all]            # what you already bought
beatport_skill.py downloads [--all]            # download entitlements
```

### Crate workflow
```bash
beatport_skill.py match CRATE.json [--min-score 0.72] [--refresh]
beatport_skill.py plan CRATE.json              # buy list + total, NO purchase
beatport_skill.py report CRATE.json [--target-bpm 128] [--bpm-tolerance 8]
beatport_skill.py organize CRATE.json --dir ~/Music/friday-set
beatport_skill.py camelot "A Minor"
```

## The Friday-set pipeline

```
Spotify liked / playlist ─┐
                          ├─> crate.json ─> match ─> plan ─> [Idan buys] ─> download
YouTube liked / playlist ─┘                            │                        │
                                                    report                   organize
                                                (set order)              (files + m3u8)
```

1. **Export what he earmarked** (see `spotify-skill` / `youtube-skill`):
   ```bash
   python3 ~/.claude/skills/spotify-skill/spotify_skill.py export-crate --name friday --playlist "<url>" --all
   python3 ~/.claude/skills/youtube-skill/youtube_skill.py export-crate --name friday-yt --all
   ```
   Crates land in `~/.claude/skills/beatport-skill/crates/`.

2. **Check what he already owns** — `purchases --all` — so step 4 doesn't re-buy.

3. **Match to Beatport:** `match crates/friday.json`. Matching is ISRC-first (exact, from
   Spotify) then fuzzy on artist+title+mix. It writes results back into the crate.

4. **Plan, then hand off:** `plan crates/friday.json`. Show Idan `to_buy` with prices and
   the total, `needs_review_before_buying` with alternatives, and `unmatched_on_beatport`.
   **Stop there.** He opens the URLs and checks out.

5. **After he downloads** (Beatport delivers ZIPs — unzip into one folder):
   ```bash
   beatport_skill.py organize crates/friday.json --dir ~/Music/friday-set
   ```
   Matches files to crate entries, reports anything missing or unexpected, and writes an
   `.m3u8` **in harmonic set order**.

6. **Set order:** `report crates/friday.json --target-bpm 128`. Gives a greedy Camelot walk
   (compatible key, smallest BPM step) plus a `rough_transitions` list of the joins that
   need work. It is a starting point to hand-tune, not a finished set.

### Ableton
Drag the folder (or the `.m3u8`) into Ableton's browser. Set the project tempo from
`report`'s `bpm_range`. Warp each clip. Beatport's BPM/key are metadata from the label —
trust them for planning the order, verify by ear before the set.

## Crate format (v1)

One shared shape written by all three skills:

```json
{
  "crate_version": 1,
  "name": "friday",
  "origin": "spotify:playlist:37i9...",
  "tracks": [
    {
      "source": "spotify", "source_id": "...", "url": "...",
      "artist": "Bicep", "title": "Glue", "mix": "",
      "isrc": "GBCFB1700123", "duration_ms": 330000,
      "bpm": null, "key": null,
      "beatport": {
        "beatport_id": 11111, "artist": "Bicep", "title": "Glue",
        "mix": "Original Mix", "label": "Ninja Tune",
        "bpm": 128, "key": "A Minor", "camelot": "8A",
        "price": "$2.49", "price_value": 2.49,
        "url": "https://www.beatport.com/track/glue/11111",
        "match_method": "isrc", "match_score": 1.0, "purchased": false
      }
    }
  ]
}
```

- `beatport: null` — nothing found; check `beatport_candidates` on the track.
- `match_method`: `isrc` (exact) · `fuzzy` (confident) · `fuzzy-ambiguous` (**review**).
- Mark `purchased: true` after a buy so later runs treat it as owned.

## Matching notes

- **ISRC is the good path.** Spotify exposes it, Beatport carries it, and it makes matching
  exact. YouTube has no ISRC, so YouTube crates are fuzzy-only — review them harder.
- **The matcher deliberately rejects unrequested remixes.** "Glue" will not silently match
  "Glue (Chaos In The CBD Remix)"; a remix only matches if the crate side names the
  remixer. This is asymmetric on purpose — a wrong remix is a wasted purchase and a
  wrong track in the set.
- `--min-score` defaults to 0.72, validated against a labelled set in `test_matching.py`.
  Lower it to surface more candidates for review, not to auto-buy more.
- **Not everything is on Beatport.** Bootlegs, edits, and non-dance releases often aren't.
  `unmatched_on_beatport` is a normal outcome, not a failure — those need another source.

## Tests

```bash
python3 ~/.claude/skills/beatport-skill/test_matching.py
```

40 checks over the Camelot wheel (all 24 keys, enharmonics, wraparound) and the matcher
(remix discrimination, accents, `feat.`, apostrophes, false positives). No network or
credentials needed. **Run it after touching `score_match`, `to_camelot`, or
`harmonic_order`.**

## Notes

- Standard library only — no pip installs.
- `config.json`, `tokens/`, `cache.json` are gitignored. `crates/` is user data, also
  gitignored.
- Rate limiting: `match` sleeps `--delay` (0.25s) between lookups. A 100-track crate is a
  couple of hundred requests — don't hammer it.
