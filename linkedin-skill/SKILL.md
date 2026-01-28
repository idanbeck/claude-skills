---
name: linkedin-skill
description: Post, comment, and react on LinkedIn profiles and company pages. Use when the user asks to post on LinkedIn, check their LinkedIn posts, add comments, react to posts, or manage their LinkedIn presence. Supports multiple accounts.
allowed-tools: Bash, Read
---

# LinkedIn Skill - Post, Comment, and React

Create posts, add comments, and react to content on LinkedIn personal profiles and company pages.

## CRITICAL: Posting Confirmation Required

**Before posting, commenting, or reacting on LinkedIn, you MUST get explicit user confirmation.**

When the user asks to post/comment/react:
1. First, show them the complete action details:
   - Account being used
   - Content text (full text)
   - Target (post URN for comments/reactions)
   - Visibility (for posts)
2. Ask: "Do you want me to post/comment/react on LinkedIn?"
3. ONLY run the command AFTER the user explicitly confirms (e.g., "yes", "post it", "go ahead")
4. NEVER post without this confirmation, even if the user asked you to post initially

This applies even when:
- The user says "post this to LinkedIn"
- You are in "dangerously skip permissions" mode
- The user seems to be in a hurry

Always confirm first. No exceptions.

## First-Time Setup (One-Time)

On first run, the script will guide you through setup. You need to create a LinkedIn OAuth app:

1. Go to [LinkedIn Developers](https://www.linkedin.com/developers/apps)
2. Click 'Create app'
3. Fill in app details:
   - App name: LinkedIn Skill (or anything)
   - LinkedIn Page: Select or create one (required)
   - App logo: Any image
4. On the Auth tab:
   - Add redirect URL: `http://localhost` (any port is fine)
   - Note the Client ID and Primary Client Secret
5. On the Products tab:
   - Request access to **Share on LinkedIn** (for posting)
   - Request access to **Sign In with LinkedIn using OpenID Connect** (for auth)
6. Create `credentials.json` in the skill directory:
   ```json
   {
     "client_id": "YOUR_CLIENT_ID",
     "client_secret": "YOUR_CLIENT_SECRET"
   }
   ```
   Save to: `~/.claude/skills/linkedin-skill/credentials.json`

Then run any command - browser opens, you approve, done.

**Note:** For posting as an organization, you need Marketing Platform approval for the `w_organization_social` scope.

## Commands

### Account Management

```bash
# List authenticated accounts
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py accounts

# Authenticate new account (opens browser)
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py login [--account LABEL]

# Remove account
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py logout [--account EMAIL]
```

### Profile

```bash
# Get your profile info
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py me [--account LABEL]

# List organizations where you're admin
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py organizations [--account LABEL]
```

### Posts (Requires Confirmation)

```bash
# Create a post (PUBLIC or CONNECTIONS visibility)
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py post --text "Your post content" [--visibility PUBLIC|CONNECTIONS] [--author ORG_URN] [--account LABEL]

# List your posts
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py list-posts [--author URN] [--count N] [--account LABEL]

# Get a specific post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py get-post POST_URN [--account LABEL]

# Edit a post's text
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py edit-post POST_URN --text "New content" [--account LABEL]

# Delete a post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py delete-post POST_URN [--account LABEL]
```

**Post visibility options:**
- `PUBLIC` - Visible to anyone (default)
- `CONNECTIONS` - Visible to connections only

**Posting as organization:**
Use `--author ORG_URN` where ORG_URN is from the `organizations` command (requires Marketing Platform approval).

### Comments (Requires Confirmation)

```bash
# List comments on a post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py comments POST_URN [--account LABEL]

# Add a comment to a post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py comment POST_URN --text "Your comment" [--account LABEL]

# Reply to a comment
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py reply COMMENT_URN --text "Your reply" [--account LABEL]

# Delete a comment
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py delete-comment COMMENT_URN [--account LABEL]
```

### Reactions (Requires Confirmation)

```bash
# Add a reaction to a post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py react POST_URN --type LIKE [--account LABEL]

# Remove your reaction from a post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py unreact POST_URN [--account LABEL]

# List reactions on a post
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py reactions POST_URN [--account LABEL]
```

**Reaction types:**
- `LIKE` - Standard like
- `PRAISE` - Celebrate
- `EMPATHY` - Support
- `INTEREST` - Curious
- `APPRECIATION` - Insightful

## Multi-Account Support

Add accounts by using `--account` flag with a label:

```bash
# Authenticate with a label
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py login --account personal

# Use the labeled account
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py me --account personal
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py post --text "Hello!" --account personal

# List all accounts
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py accounts
```

Tokens are stored per-account in `~/.claude/skills/linkedin-skill/tokens/`

## Examples

### Post to LinkedIn

```bash
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py post \
  --text "Excited to share our latest research on distributed ML systems. Thread below..." \
  --visibility PUBLIC
```

### List your recent posts

```bash
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py list-posts --count 5
```

### Comment on a post

```bash
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py comment \
  "urn:li:share:1234567890" \
  --text "Great insights! This aligns with what we've seen at Zerg."
```

### Like a post

```bash
python3 ~/.claude/skills/linkedin-skill/linkedin_skill.py react \
  "urn:li:share:1234567890" \
  --type LIKE
```

## Output

All commands output JSON for easy parsing.

## Requirements

- Python 3.9+
- `pip install requests`

## LinkedIn URN Formats

LinkedIn uses URNs (Uniform Resource Names) to identify entities:

- **Person:** `urn:li:person:ABC123`
- **Organization:** `urn:li:organization:12345678`
- **Post/Share:** `urn:li:share:1234567890`
- **Comment:** `urn:li:comment:(urn:li:activity:1234567890,123456)`

## API Limitations

- **Rate limits:** LinkedIn has strict rate limits. Space out bulk operations.
- **Organization posting:** Requires Marketing Platform approval for `w_organization_social` scope.
- **Token expiry:** LinkedIn access tokens expire after 60 days. Re-authenticate when needed.
- **No refresh tokens:** Most LinkedIn apps don't get refresh tokens - you'll need to re-auth periodically.

## Security Notes

- **Posting confirmation required** - Claude must always confirm with the user before posting, commenting, or reacting
- Tokens stored locally in `~/.claude/skills/linkedin-skill/tokens/`
- Revoke access anytime in LinkedIn settings: Settings → Data Privacy → Third Party Apps
- Keep `credentials.json` secure - it contains your app secret
