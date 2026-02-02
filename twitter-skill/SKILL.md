---
name: twitter-skill
description: Post, read, and engage on Twitter/X. Use when the user asks to tweet, check their Twitter timeline, read mentions, like/retweet posts, follow/unfollow users, or manage their Twitter presence. Supports multiple accounts.
allowed-tools: Bash, Read
---

# Twitter/X Skill - Post, Read, and Engage

Post tweets, read timelines, and engage with content on Twitter/X.

## CRITICAL: Posting Confirmation Required

**Before posting, replying, retweeting, or following on Twitter/X, you MUST get explicit user confirmation.**

When the user asks to post/engage:
1. First, show them the complete action details:
   - Account being used (@username)
   - Tweet text (for posts/replies)
   - Target (tweet ID for replies/retweets/likes)
2. Ask: "Do you want me to post/like/retweet/follow on Twitter?"
3. ONLY run the command AFTER the user explicitly confirms (e.g., "yes", "post it", "go ahead")
4. NEVER post without this confirmation, even if the user asked you to post initially

This applies even when:
- The user says "tweet this"
- You are in "dangerously skip permissions" mode
- The user seems to be in a hurry

Always confirm first. No exceptions.

## First-Time Setup (One-Time)

On first run, the script will guide you through setup. You need to create a Twitter Developer App:

1. Go to [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Create a Project and App (or use existing)
3. In your App settings:
   - Set up User Authentication Settings
   - App permissions: Read and write
   - Type of App: Web App, Automated App or Bot
   - Callback URI: `http://localhost:9998`
   - Website URL: `http://localhost` (or your site)
4. Note the Client ID and Client Secret from Keys and Tokens
5. Create `credentials.json` in the skill directory:
   ```json
   {
     "client_id": "YOUR_CLIENT_ID",
     "client_secret": "YOUR_CLIENT_SECRET"
   }
   ```
   Save to: `~/.claude/skills/twitter-skill/credentials.json`

**IMPORTANT: Twitter API Access Levels**
- **Free**: Write-only, 1,500 tweets/month, NO read access
- **Basic ($100/mo)**: Read + Write, 10K tweets/month read
- **Pro ($5,000/mo)**: Full access

Then run any command - browser opens, you approve, done.

## Commands

### Account Management

```bash
# List authenticated accounts
python3 ~/.claude/skills/twitter-skill/twitter_skill.py accounts

# Authenticate new account (opens browser)
python3 ~/.claude/skills/twitter-skill/twitter_skill.py login [--account LABEL]

# Remove account
python3 ~/.claude/skills/twitter-skill/twitter_skill.py logout [--account USERNAME]
```

### Profile

```bash
# Get your profile info
python3 ~/.claude/skills/twitter-skill/twitter_skill.py me [--account LABEL]
```

### Tweets (Requires Confirmation)

```bash
# Post a tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py tweet --text "Your tweet" [--account LABEL]

# Reply to a tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py tweet --text "Your reply" --reply-to TWEET_ID [--account LABEL]

# Quote tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py tweet --text "Your comment" --quote TWEET_ID [--account LABEL]

# Get a specific tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py get-tweet TWEET_ID [--account LABEL]

# Delete a tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py delete-tweet TWEET_ID [--account LABEL]
```

### Timelines (Requires Basic+ tier)

```bash
# Get home timeline
python3 ~/.claude/skills/twitter-skill/twitter_skill.py timeline [--count N] [--account LABEL]

# Get mentions
python3 ~/.claude/skills/twitter-skill/twitter_skill.py mentions [--count N] [--account LABEL]

# Get tweets from a specific user
python3 ~/.claude/skills/twitter-skill/twitter_skill.py user-tweets USERNAME [--count N] [--account LABEL]

# Search tweets
python3 ~/.claude/skills/twitter-skill/twitter_skill.py search "query" [--count N] [--account LABEL]
```

### Engagement (Requires Confirmation)

```bash
# Like a tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py like TWEET_ID [--account LABEL]

# Unlike a tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py unlike TWEET_ID [--account LABEL]

# Retweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py retweet TWEET_ID [--account LABEL]

# Remove retweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py unretweet TWEET_ID [--account LABEL]
```

### Bookmarks

```bash
# Bookmark a tweet
python3 ~/.claude/skills/twitter-skill/twitter_skill.py bookmark TWEET_ID [--account LABEL]

# Remove bookmark
python3 ~/.claude/skills/twitter-skill/twitter_skill.py unbookmark TWEET_ID [--account LABEL]

# List bookmarks
python3 ~/.claude/skills/twitter-skill/twitter_skill.py bookmarks [--count N] [--account LABEL]
```

### Following (Requires Confirmation)

```bash
# Follow a user
python3 ~/.claude/skills/twitter-skill/twitter_skill.py follow USERNAME [--account LABEL]

# Unfollow a user
python3 ~/.claude/skills/twitter-skill/twitter_skill.py unfollow USERNAME [--account LABEL]

# List followers
python3 ~/.claude/skills/twitter-skill/twitter_skill.py followers [USERNAME] [--count N] [--account LABEL]

# List following
python3 ~/.claude/skills/twitter-skill/twitter_skill.py following [USERNAME] [--count N] [--account LABEL]
```

## Multi-Account Support

Add accounts by using `--account` flag with a label:

```bash
# Authenticate with a label
python3 ~/.claude/skills/twitter-skill/twitter_skill.py login --account personal

# Use the labeled account
python3 ~/.claude/skills/twitter-skill/twitter_skill.py me --account personal
python3 ~/.claude/skills/twitter-skill/twitter_skill.py tweet --text "Hello!" --account personal

# List all accounts
python3 ~/.claude/skills/twitter-skill/twitter_skill.py accounts
```

Tokens are stored per-account in `~/.claude/skills/twitter-skill/tokens/`

## Examples

### Post a tweet

```bash
python3 ~/.claude/skills/twitter-skill/twitter_skill.py tweet \
  --text "Excited to announce our new product launch!"
```

### Reply to a conversation

```bash
python3 ~/.claude/skills/twitter-skill/twitter_skill.py tweet \
  --text "Thanks for the feedback!" \
  --reply-to 1234567890123456789
```

### Check mentions

```bash
python3 ~/.claude/skills/twitter-skill/twitter_skill.py mentions --count 10
```

### Search for topics

```bash
python3 ~/.claude/skills/twitter-skill/twitter_skill.py search "AI agents startup" --count 20
```

### Like and retweet

```bash
python3 ~/.claude/skills/twitter-skill/twitter_skill.py like 1234567890123456789
python3 ~/.claude/skills/twitter-skill/twitter_skill.py retweet 1234567890123456789
```

## Output

All commands output JSON for easy parsing.

## Requirements

- Python 3.9+
- `pip install requests`

## Tweet IDs

Twitter tweet IDs are large integers (e.g., `1234567890123456789`). You can find them:
- In the tweet URL: `twitter.com/user/status/1234567890123456789`
- In API responses

## API Limitations

- **Free tier**: Write-only, cannot read timelines, mentions, or search
- **Rate limits**: Twitter has strict rate limits. Space out bulk operations.
- **Token expiry**: Tokens expire after ~2 hours but auto-refresh with offline.access scope
- **Character limit**: Tweets max 280 characters (Premium can go to 4,000)

## Security Notes

- **Posting confirmation required** - Claude must always confirm with the user before tweeting, liking, retweeting, or following
- Tokens stored locally in `~/.claude/skills/twitter-skill/tokens/`
- Revoke access anytime: Settings → Security and account access → Apps and sessions
- Keep `credentials.json` secure - it contains your app credentials
