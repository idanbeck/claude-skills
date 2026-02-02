---
name: reddit-skill
description: Post, comment, and browse Reddit. Use when the user asks to post on Reddit, read subreddits, check their Reddit inbox, vote on posts, or search Reddit content.
allowed-tools: Bash, Read
---

# Reddit Skill - Post, Comment, Browse

Submit posts, comment, vote, and browse Reddit.

## CRITICAL: Posting Confirmation Required

**Before posting or commenting on Reddit, you MUST get explicit user confirmation.**

Show: subreddit, title, content. Ask for confirmation before submitting.

## Setup

1. Go to https://www.reddit.com/prefs/apps
2. Click "create another app..."
3. Fill in:
   - Name: Claude Reddit Skill
   - Type: script
   - Redirect URI: `http://localhost:9996`
4. Create `~/.claude/skills/reddit-skill/credentials.json`:
   ```json
   {"client_id": "YOUR_ID", "client_secret": "YOUR_SECRET"}
   ```
5. Run: `python3 ~/.claude/skills/reddit-skill/reddit_skill.py login`

## Commands

### Browsing

```bash
# Frontpage
python3 ~/.claude/skills/reddit-skill/reddit_skill.py frontpage [--limit N] [--sort hot|new|top]

# Subreddit
python3 ~/.claude/skills/reddit-skill/reddit_skill.py subreddit NAME [--limit N] [--sort hot|new|top|rising]

# Search
python3 ~/.claude/skills/reddit-skill/reddit_skill.py search "query" [--subreddit NAME] [--limit N]
```

### Posting (Requires Confirmation)

```bash
# Text post
python3 ~/.claude/skills/reddit-skill/reddit_skill.py post SUBREDDIT --title "Title" --text "Content"

# Link post
python3 ~/.claude/skills/reddit-skill/reddit_skill.py post SUBREDDIT --title "Title" --url "https://..."

# Comment on post
python3 ~/.claude/skills/reddit-skill/reddit_skill.py comment t3_POSTID --text "Comment"

# Reply to comment
python3 ~/.claude/skills/reddit-skill/reddit_skill.py reply COMMENTID --text "Reply"
```

### Voting & Saving

```bash
python3 ~/.claude/skills/reddit-skill/reddit_skill.py vote THING_ID --dir up|down|none
python3 ~/.claude/skills/reddit-skill/reddit_skill.py save THING_ID
python3 ~/.claude/skills/reddit-skill/reddit_skill.py unsave THING_ID
```

### User Content

```bash
python3 ~/.claude/skills/reddit-skill/reddit_skill.py me
python3 ~/.claude/skills/reddit-skill/reddit_skill.py submissions [USERNAME] [--limit N]
python3 ~/.claude/skills/reddit-skill/reddit_skill.py comments [USERNAME] [--limit N]
python3 ~/.claude/skills/reddit-skill/reddit_skill.py inbox [--limit N]
python3 ~/.claude/skills/reddit-skill/reddit_skill.py subscriptions
```

## Thing IDs

Reddit uses "thing IDs" with prefixes:
- `t1_` = comment
- `t3_` = post/link
- `t4_` = message

Get IDs from command outputs or URLs.

## Output

All commands output JSON.
