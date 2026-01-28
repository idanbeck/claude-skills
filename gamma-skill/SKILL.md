# Gamma Skill - Presentation Generation

Generate presentations, documents, webpages, and social content using Gamma's AI.

## First-Time Setup (~2 minutes)

### 1. Get API Access

Gamma API requires a **Pro, Ultra, Teams, or Business** account.

1. Go to [Gamma Settings](https://gamma.app/settings)
2. Navigate to **Members** tab
3. Click **API key** tab
4. Click **Create key**
5. Copy the key (format: `sk-gamma-xxxxxxxx`)

### 2. Save API Key

```bash
echo '{"api_key": "sk-gamma-YOUR-KEY-HERE"}' > ~/.claude/skills/gamma-skill/config.json
```

## Commands

### Generate Presentation/Document

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate "Your content here" [options]
```

**From file:**
```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate --file notes.md --wait
```

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--format` / `-f` | presentation, document, webpage, social | presentation |
| `--text-mode` / `-m` | generate, condense, preserve | generate |
| `--theme` / `-t` | Theme ID | (Gamma default) |
| `--num-cards` / `-n` | Number of slides (1-60 Pro, 1-75 Ultra) | (auto) |
| `--instructions` / `-i` | Additional specs (max 2000 chars) | |
| `--export-as` / `-e` | pdf or pptx | |
| `--tone` | Content tone (professional, casual, etc.) | |
| `--audience` | Target audience | |
| `--language` | Output language | |
| `--text-amount` | less, default, more | default |
| `--aspect-ratio` | 16:9, 4:3, 1:1, 9:16 | 16:9 |
| `--wait` / `-w` | Wait for completion | false |
| `--timeout` | Max wait seconds | 300 |

### Create from Template

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py from-template TEMPLATE_ID "Your content" [options]
```

Get template ID from the Gamma URL (e.g., `gamma.app/docs/TEMPLATE_ID`).

### Check Generation Status

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py status GENERATION_ID
```

### Get Export URLs

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py export GENERATION_ID
```

Returns PDF/PPTX download URLs (if `--export-as` was used during generation).

### List Themes

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py themes [--limit N]
```

### List Folders

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py folders
```

## Examples

### Quick Pitch Deck

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate \
  "Zerg AI: AI-powered software development.
   Problem: Code migration is slow and expensive.
   Solution: Autonomous AI agents that understand and transform code.
   Market: $500B software services market.
   Traction: 3 enterprise pilots, $500K ARR.
   Team: Ex-Google, Apple, Pixar engineers." \
  --format presentation \
  --num-cards 10 \
  --tone professional \
  --audience investors \
  --wait
```

### Generate from Obsidian Notes

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate \
  --file ~/vault/Writing/pitch-notes.md \
  --format presentation \
  --instructions "Focus on the problem and solution. Use data visualizations." \
  --export-as pdf \
  --wait
```

### Document Generation

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate \
  "Technical documentation for our API..." \
  --format document \
  --text-mode preserve \
  --wait
```

### Social Content

```bash
python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate \
  "Key insights from our AI research paper..." \
  --format social \
  --tone casual \
  --wait
```

## Workflow: Content-First Deck Creation

1. **Draft content** in Obsidian (bullet points, notes, key messages)

2. **Generate initial deck:**
   ```bash
   python3 ~/.claude/skills/gamma-skill/gamma_skill.py generate \
     --file ~/vault/Epoch/Fundraising/pitch-content.md \
     --format presentation \
     --num-cards 12 \
     --tone professional \
     --audience investors \
     --wait
   ```

3. **Review output** - opens in browser at the returned `gammaUrl`

4. **Iterate:**
   - Refine in Gamma's editor, or
   - Adjust content/instructions and regenerate

5. **Export final version:**
   ```bash
   python3 ~/.claude/skills/gamma-skill/gamma_skill.py export GENERATION_ID
   ```

## Text Modes

| Mode | Description |
|------|-------------|
| `generate` | AI expands your notes into full content |
| `condense` | AI summarizes your content |
| `preserve` | Keep your text mostly as-is, just format it |

## Output

All commands return JSON. Example generation response:

```json
{
  "generation_id": "abc123",
  "status": "completed",
  "gammaUrl": "https://gamma.app/docs/abc123"
}
```

## Credit System

Gamma uses credits for generation:

- **Slides:** 3-4 credits each
- **AI Images:** 2-120 credits depending on model
- **Pro:** ~400 credits/month
- **Ultra:** ~1000 credits/month

Monitor usage in Gamma Settings.

## Requirements

- Python 3.9+
- No external dependencies (uses stdlib only)
- Gamma Pro/Ultra/Teams/Business account

## Security Notes

- API key stored in `~/.claude/skills/gamma-skill/config.json` (gitignored)
- Key can be revoked in Gamma Settings > Members > API key
- No OAuth - simple API key authentication

## Troubleshooting

**401 Unauthorized:** Check API key is correct and account has API access.

**429 Rate Limited:** API has generous limits but contact Gamma support if hit.

**Generation timeout:** Increase `--timeout` or check status manually with `status` command.

**Export URLs expired:** URLs are temporary. Re-run `export` command if needed.
