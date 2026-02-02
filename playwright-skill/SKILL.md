---
name: playwright-skill
description: Browser automation for web tasks. Use when the user needs to automate browser interactions, take screenshots, extract data from websites, fill forms, or perform web scraping. Supports persistent sessions for logged-in state.
allowed-tools: Bash, Read
---

# Playwright Skill - Browser Automation

Automate browser tasks: navigate, click, type, extract data, take screenshots, and more.

## First-Time Setup

```bash
pip install playwright
playwright install chromium
```

## Core Concepts

### Sessions
Sessions persist browser state (cookies, localStorage) across commands. Use named sessions for different accounts/sites:

```bash
# Default session
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://example.com

# Named session for a specific site
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://github.com --session github
```

Sessions are saved to `~/.claude/skills/playwright-skill/sessions/`

### Headless vs Visible
By default, browser runs headless (invisible). Use `--visible` to see what's happening:

```bash
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://example.com --visible
```

## Commands

### Navigation

```bash
# Open a URL
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open URL [--session NAME] [--visible]

# Wait for element to appear
python3 ~/.claude/skills/playwright-skill/playwright_skill.py wait SELECTOR [--timeout MS] [--session NAME]

# Scroll page
python3 ~/.claude/skills/playwright-skill/playwright_skill.py scroll [--direction up|down] [--amount PIXELS] [--session NAME]
```

### Interaction

```bash
# Click an element
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click SELECTOR [--session NAME]

# Type text into input
python3 ~/.claude/skills/playwright-skill/playwright_skill.py type SELECTOR "text to type" [--clear] [--session NAME]

# Execute JavaScript
python3 ~/.claude/skills/playwright-skill/playwright_skill.py eval "document.title" [--session NAME]
```

### Data Extraction

```bash
# Extract text from element
python3 ~/.claude/skills/playwright-skill/playwright_skill.py extract SELECTOR [--session NAME]

# Extract attribute
python3 ~/.claude/skills/playwright-skill/playwright_skill.py extract "a.link" --attr href [--session NAME]

# Extract from all matching elements
python3 ~/.claude/skills/playwright-skill/playwright_skill.py extract "li.item" --all [--session NAME]

# Get page HTML
python3 ~/.claude/skills/playwright-skill/playwright_skill.py html [--selector SELECTOR] [--output FILE] [--session NAME]
```

### Screenshots & PDF

```bash
# Screenshot current page
python3 ~/.claude/skills/playwright-skill/playwright_skill.py screenshot [--output FILE] [--session NAME]

# Screenshot with URL
python3 ~/.claude/skills/playwright-skill/playwright_skill.py screenshot https://example.com --output example.png

# Full-page screenshot
python3 ~/.claude/skills/playwright-skill/playwright_skill.py screenshot --full-page --output full.png

# Save as PDF
python3 ~/.claude/skills/playwright-skill/playwright_skill.py pdf https://example.com --output page.pdf
```

### Cookies & Sessions

```bash
# List all cookies
python3 ~/.claude/skills/playwright-skill/playwright_skill.py cookies [--session NAME]

# Get specific cookie
python3 ~/.claude/skills/playwright-skill/playwright_skill.py cookies --name session_id [--session NAME]

# Set cookie
python3 ~/.claude/skills/playwright-skill/playwright_skill.py cookies --set "name=value" --domain example.com [--session NAME]

# List all sessions
python3 ~/.claude/skills/playwright-skill/playwright_skill.py sessions

# Close session (saves state)
python3 ~/.claude/skills/playwright-skill/playwright_skill.py close [--session NAME]

# Close all sessions
python3 ~/.claude/skills/playwright-skill/playwright_skill.py close --all
```

## Selectors

Playwright supports multiple selector types:

```bash
# CSS selectors
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "button.submit"
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "#login-form input[type=email]"

# Text selectors
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "text=Sign In"
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "text=Submit"

# XPath
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "xpath=//button[@type='submit']"

# Combining
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "form >> text=Submit"
```

## Examples

### Login Flow (Manual First Time)

```bash
# Open login page visibly
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://example.com/login --visible --session mysite

# ... manually log in while browser is visible ...

# Close to save session
python3 ~/.claude/skills/playwright-skill/playwright_skill.py close --session mysite

# Future runs use saved session (logged in)
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://example.com/dashboard --session mysite
```

### Scrape a List

```bash
# Open page
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://news.ycombinator.com

# Extract all headlines
python3 ~/.claude/skills/playwright-skill/playwright_skill.py extract ".titleline a" --all

# Extract with links
python3 ~/.claude/skills/playwright-skill/playwright_skill.py extract ".titleline a" --attr href --all
```

### Fill a Form

```bash
python3 ~/.claude/skills/playwright-skill/playwright_skill.py open https://example.com/form --session formtest
python3 ~/.claude/skills/playwright-skill/playwright_skill.py type "input[name=email]" "user@example.com" --session formtest
python3 ~/.claude/skills/playwright-skill/playwright_skill.py type "input[name=message]" "Hello world" --session formtest
python3 ~/.claude/skills/playwright-skill/playwright_skill.py click "button[type=submit]" --session formtest
```

### Screenshot a Page

```bash
python3 ~/.claude/skills/playwright-skill/playwright_skill.py screenshot https://example.com --output example.png --full-page
```

### Run JavaScript

```bash
# Get page title
python3 ~/.claude/skills/playwright-skill/playwright_skill.py eval "document.title"

# Get scroll position
python3 ~/.claude/skills/playwright-skill/playwright_skill.py eval "window.scrollY"

# Count elements
python3 ~/.claude/skills/playwright-skill/playwright_skill.py eval "document.querySelectorAll('a').length"
```

## Output

All commands output JSON for easy parsing.

## Requirements

- Python 3.9+
- `pip install playwright`
- `playwright install chromium`

## Tips

- **First login**: Use `--visible` to manually log in, then save session for headless reuse
- **Flaky selectors**: Use `wait` command before interacting with dynamic content
- **Rate limiting**: Add delays between actions with `eval "await new Promise(r => setTimeout(r, 2000))"`
- **Debugging**: Take screenshots to see what went wrong
- **Multiple accounts**: Use different session names for each account

## Security Notes

- Session files contain authentication cookies - keep `sessions/` directory secure
- Don't share session files - they can grant account access
- Clear sessions when done with sensitive sites: `close --session NAME`
