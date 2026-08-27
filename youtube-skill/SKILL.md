---
name: youtube-skill
description: Manage YouTube videos, playlists, and channels, and export liked videos or a playlist as a DJ crate for Beatport matching. Use when the user asks to upload videos, manage playlists, search YouTube, interact with comments, or turn tracks they liked/saved on YouTube into a buy list.
allowed-tools: Bash, Read
---

# YouTube Skill

Upload videos, manage playlists, search, and interact with YouTube.

## Setup

Uses Google OAuth (same as gmail-skill). Enable **YouTube Data API v3** in your Google Cloud project.

If you have gmail-skill set up, this should work. Otherwise:
1. Enable YouTube Data API v3 at console.cloud.google.com
2. Create/download OAuth credentials
3. Save to `~/.claude/skills/youtube-skill/credentials.json`

## Commands

### Channel & Videos

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py me
python3 ~/.claude/skills/youtube-skill/youtube_skill.py channels
python3 ~/.claude/skills/youtube-skill/youtube_skill.py videos [--channel CHANNEL_ID] [--limit N]
python3 ~/.claude/skills/youtube-skill/youtube_skill.py video VIDEO_ID
```

### Search

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py search "query" [--limit N] [--type video|channel|playlist]
```

### Playlists

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py playlists [--channel CHANNEL_ID]
python3 ~/.claude/skills/youtube-skill/youtube_skill.py playlist PLAYLIST_ID [--limit N] [--all]
python3 ~/.claude/skills/youtube-skill/youtube_skill.py create-playlist --title "Name" [--privacy public|private|unlisted]
python3 ~/.claude/skills/youtube-skill/youtube_skill.py add-to-playlist PLAYLIST_ID --video VIDEO_ID
python3 ~/.claude/skills/youtube-skill/youtube_skill.py remove-from-playlist PLAYLIST_ITEM_ID
```

### Liked videos (earmarked tracks)

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py liked [--limit 50] [--all]
```

Returns your thumbs-upped videos already parsed into `artist` / `title` / `mix`, in crate
shape. `--all` follows pagination; without it you get one page of 50.

### Export a DJ crate

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py export-crate --name friday-yt --all
python3 ~/.claude/skills/youtube-skill/youtube_skill.py export-crate --name friday-yt --playlist "https://youtube.com/playlist?list=PL..." --all
```

Writes `~/.claude/skills/beatport-skill/crates/<name>.json`, then:

```bash
python3 ~/.claude/skills/beatport-skill/beatport_skill.py match ~/.claude/skills/beatport-skill/crates/friday-yt.json
```

**YouTube crates are lower-confidence than Spotify ones.** YouTube has no structured
artist/title and no ISRC, so `artist`/`title` are parsed heuristically from the video title
— stripping "(Official Video)", "[HD]", "| Out Now" and splitting on a dash, falling back
to the channel name (a "<Artist> - Topic" channel is reliable). Every track keeps its
`raw_title` so you can check the parse, and `export-crate` reports `unparsed_artist` for
titles it could not split. Review those before buying anything; Beatport matching for these
is fuzzy-only.

### Comments

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py comments VIDEO_ID [--limit N]
python3 ~/.claude/skills/youtube-skill/youtube_skill.py comment VIDEO_ID --text "Great video!"
python3 ~/.claude/skills/youtube-skill/youtube_skill.py reply COMMENT_ID --text "Thanks!"
```

### Subscriptions

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py subscriptions
python3 ~/.claude/skills/youtube-skill/youtube_skill.py subscribe CHANNEL_ID
python3 ~/.claude/skills/youtube-skill/youtube_skill.py unsubscribe SUBSCRIPTION_ID
```

### Upload

```bash
python3 ~/.claude/skills/youtube-skill/youtube_skill.py upload --file video.mp4 --title "My Video" [--description "..."] [--privacy private]
```

## Video IDs

Found in URLs: `youtube.com/watch?v=VIDEO_ID`

## Privacy Options

- `public` - Anyone can see
- `unlisted` - Only people with link
- `private` - Only you

## Output

All commands output JSON.

## Notes

- `liked`, `playlist --all`, and `export-crate` follow pagination; other listings return a
  single page.
- The YouTube Data API has a **10,000 unit/day quota** and `search` costs 100 units per
  call. Listing playlist items and liked videos is 1 unit, so crate exports are cheap —
  repeated `search` is what burns the quota.
- Watch Later and history are **not** readable through the API (YouTube removed that access
  years ago). Use liked videos or a real playlist as the earmarking mechanism instead.
