---
name: google-slides-skill
description: Create and manage Google Slides presentations. Use when the user asks to create slides, add content to presentations, or export to PDF/PPTX.
allowed-tools: Bash, Read
---

# Google Slides Skill

Create, edit, and export Google Slides presentations.

## Setup

Uses same Google OAuth as gmail-skill. If configured, this works automatically.

Otherwise: same setup as google-sheets-skill, but enable Google Slides API.

## Commands

### List & Info

```bash
python3 ~/.claude/skills/google-slides-skill/slides_skill.py list [--limit N]
python3 ~/.claude/skills/google-slides-skill/slides_skill.py get PRESENTATION_ID
```

### Create & Manage

```bash
# Create new presentation
python3 ~/.claude/skills/google-slides-skill/slides_skill.py create --title "My Deck"

# Add slide
python3 ~/.claude/skills/google-slides-skill/slides_skill.py add-slide PRES_ID [--layout blank|title|title_body]

# Delete slide
python3 ~/.claude/skills/google-slides-skill/slides_skill.py delete-slide PRES_ID --slide-id SLIDE_ID
```

### Add Content

```bash
# Add text box (x, y, w, h in inches)
python3 ~/.claude/skills/google-slides-skill/slides_skill.py add-text PRES_ID --slide-id SLIDE_ID --text "Hello" --x 1 --y 1 --w 8 --h 1

# Add image from URL
python3 ~/.claude/skills/google-slides-skill/slides_skill.py add-image PRES_ID --slide-id SLIDE_ID --url "https://..." --x 1 --y 2 --w 4 --h 3
```

### Find & Replace

```bash
python3 ~/.claude/skills/google-slides-skill/slides_skill.py replace-text PRES_ID --find "{{name}}" --replace "John"
```

### Export

```bash
python3 ~/.claude/skills/google-slides-skill/slides_skill.py export PRES_ID --format pdf --output deck.pdf
python3 ~/.claude/skills/google-slides-skill/slides_skill.py export PRES_ID --format pptx --output deck.pptx
```

## Slide Layouts

- `blank` - Empty slide
- `title` - Title slide
- `title_body` - Title + body text
- `title_two_columns` - Title + two columns
- `title_only` - Just title
- `section` - Section header
- `big_number` - Large number display

## Presentation ID

Found in URL: `https://docs.google.com/presentation/d/PRESENTATION_ID/edit`
