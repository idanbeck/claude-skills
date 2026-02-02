---
name: figma-skill
description: Read Figma files, export assets, and manage comments. Use when the user asks to get Figma designs, export images from Figma, or work with Figma components.
allowed-tools: Bash, Read
---

# Figma Skill

Read Figma files, export assets, list components/styles, and manage comments.

## Setup

1. Go to Figma → Account Settings → Personal Access Tokens
2. Create a new token
3. Create `~/.claude/skills/figma-skill/config.json`:
   ```json
   {"access_token": "YOUR_TOKEN"}
   ```

## File Keys

Found in Figma URLs: `figma.com/file/FILE_KEY/...`

## Commands

### User Info

```bash
python3 ~/.claude/skills/figma-skill/figma_skill.py me
```

### Files & Projects

```bash
# Get file info
python3 ~/.claude/skills/figma-skill/figma_skill.py get FILE_KEY

# List files in project
python3 ~/.claude/skills/figma-skill/figma_skill.py files --project PROJECT_ID

# List projects in team
python3 ~/.claude/skills/figma-skill/figma_skill.py projects TEAM_ID

# File version history
python3 ~/.claude/skills/figma-skill/figma_skill.py versions FILE_KEY
```

### Nodes & Export

```bash
# Get specific nodes
python3 ~/.claude/skills/figma-skill/figma_skill.py nodes FILE_KEY --ids "1:2,1:3"

# Export images
python3 ~/.claude/skills/figma-skill/figma_skill.py images FILE_KEY --ids "1:2" --format png --scale 2
```

**Export formats:** png, jpg, svg, pdf

### Components & Styles

```bash
python3 ~/.claude/skills/figma-skill/figma_skill.py components FILE_KEY
python3 ~/.claude/skills/figma-skill/figma_skill.py styles FILE_KEY
python3 ~/.claude/skills/figma-skill/figma_skill.py team-components TEAM_ID
```

### Comments

```bash
# List comments
python3 ~/.claude/skills/figma-skill/figma_skill.py comments FILE_KEY

# Add comment
python3 ~/.claude/skills/figma-skill/figma_skill.py add-comment FILE_KEY --message "Nice work!"

# Comment on specific node
python3 ~/.claude/skills/figma-skill/figma_skill.py add-comment FILE_KEY --message "Review this" --node-id "1:23"
```

## Node IDs

Node IDs are in format `1:23`. Find them by:
- Using `get FILE_KEY` to see page structure
- In Figma: Right-click → Copy/Paste → Copy as CSS (includes node ID)
- In Figma dev mode

## Output

All commands output JSON.
