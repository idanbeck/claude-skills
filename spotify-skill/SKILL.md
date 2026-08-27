---
name: spotify-skill
description: Read Spotify liked songs, playlists, top tracks and recently played, and export them as a DJ crate for Beatport matching. Use when Idan asks what he saved or liked on Spotify, wants to see or dump a playlist, or wants to turn earmarked tracks into a buy list. Read-only - it never modifies playlists or controls playback.
allowed-tools: Bash, Read
---

# Spotify (read-only library + crate export)

Pull liked songs, playlists, and top tracks out of Spotify, and export them in the shared
crate format that `beatport-skill` matches against.

**Read-only by design.** The requested scopes cover reading the library only — no
playlist-modify, no playback control. Don't add write scopes without asking.

## The one thing to know: no BPM or key

Spotify **permanently disabled** `audio-features`, `audio-analysis`, `recommendations`,
`related-artists`, and 30-second previews for any app created after **2024-11-27**. A new
app gets `403` on those endpoints — this is policy, not a bug, and no amount of scope
fixes it.

So a crate exported here has `bpm: null` and `key: null` **by design**. BPM and key come
from Beatport during `beatport_skill.py match`. If Idan asks for the BPM of something he
liked, that is the path — don't go looking for a Spotify endpoint that will serve it.

What Spotify *does* still give, and what makes this whole workflow work: **ISRC**, on
`track.external_ids.isrc`. That is an exact identifier, and matching a crate to Beatport by
ISRC is exact rather than fuzzy. Always prefer a Spotify-sourced crate over a YouTube one.

## Setup

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Add the redirect URI **`http://127.0.0.1:8899/callback`**.
   **It must be the literal `127.0.0.1`.** Spotify explicitly rejects `localhost`; loopback
   is the one case where plain `http` is allowed. Getting this wrong is the #1 setup
   failure.
3. Copy the Client ID (PKCE is used, so **no client secret is needed** — don't ask for one).

```bash
python3 ~/.claude/skills/spotify-skill/spotify_skill.py setup --client-id YOUR_CLIENT_ID
python3 ~/.claude/skills/spotify-skill/spotify_skill.py login
```

`login` opens a browser and runs Authorization Code + PKCE against a one-shot local
callback server. The refresh token is stored in `tokens/` (gitignored, chmod 600) and
refreshed automatically, so `login` is a one-time step.

## Commands

```bash
S=~/.claude/skills/spotify-skill/spotify_skill.py

python3 $S me
python3 $S liked [--limit 50] [--all]
python3 $S playlists [--all]
python3 $S playlist PLAYLIST_ID_OR_URL [--all]     # accepts id, URL, or spotify:playlist: URI
python3 $S top-tracks [--range short|medium|long]
python3 $S recently-played [--limit 50]
python3 $S search "query" [--limit 20]
python3 $S logout
```

`--all` follows pagination to the end; without it you get one page. For a real set, use
`--all` — a 300-track playlist silently truncated to 50 is a bad way to find out.

### Export a crate

```bash
python3 $S export-crate --name friday --liked --all
python3 $S export-crate --name friday --playlist "https://open.spotify.com/playlist/37i9..." --all
python3 $S export-crate --name friday --top
```

Writes `~/.claude/skills/beatport-skill/crates/<name>.json` and reports `with_isrc` — the
count of tracks carrying an ISRC, i.e. how many will match Beatport exactly. Then:

```bash
python3 ~/.claude/skills/beatport-skill/beatport_skill.py match ~/.claude/skills/beatport-skill/crates/friday.json
```

See `beatport-skill` for the rest of the pipeline and the crate schema.

## Output

All commands print JSON. Track objects are already in crate shape (`source`, `source_id`,
`artist`, `title`, `mix`, `isrc`, `duration_ms`, `url`), so any listing can be fed onward
without reshaping.

`mix` is parsed out of the track title when Spotify has it in parentheses — e.g. "Grey
(Tale Of Us Remix)" yields `mix: "Tale Of Us Remix"`. That field is what stops Beatport
matching from picking the wrong remix, so don't strip it.

## Notes

- Standard library only — no pip installs, no spotipy.
- `config.json` and `tokens/` are gitignored.
- **Label is not available.** Spotify's track object doesn't carry it; the crate leaves
  `label: null` and Beatport fills it in during `match`.
- On `429`, the skill stops and says it was rate limited. Wait, don't retry in a loop.
- Podcast episodes in a playlist are skipped, not half-parsed as tracks.
