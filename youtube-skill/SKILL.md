---
name: youtube-skill
description: Manage YouTube videos, playlists, and channels. Use when the user asks to upload videos, manage playlists, search YouTube, or interact with comments.
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
python3 ~/.claude/skills/youtube-skill/youtube_skill.py playlist PLAYLIST_ID
python3 ~/.claude/skills/youtube-skill/youtube_skill.py create-playlist --title "Name" [--privacy public|private|unlisted]
python3 ~/.claude/skills/youtube-skill/youtube_skill.py add-to-playlist PLAYLIST_ID --video VIDEO_ID
python3 ~/.claude/skills/youtube-skill/youtube_skill.py remove-from-playlist PLAYLIST_ITEM_ID
```

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
