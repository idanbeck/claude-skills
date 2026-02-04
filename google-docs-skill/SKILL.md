# Google Docs Skill

Create, read, write, and export Google Docs.

## Setup

Uses shared Google OAuth credentials from gmail-skill or other Google skills. If not available:

1. Go to https://console.cloud.google.com/apis/credentials
2. Create OAuth client (Desktop app)
3. Download JSON and save as `~/.claude/skills/google-docs-skill/credentials.json`
4. Enable **Google Docs API** and **Google Drive API** in your project

## Commands

### List Documents

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py list [--limit N] [--account EMAIL]
```

### Create Document

```bash
# Empty document
python3 ~/.claude/skills/google-docs-skill/docs_skill.py create --title "My Document"

# With initial content
python3 ~/.claude/skills/google-docs-skill/docs_skill.py create --title "My Document" --content "Hello world"
```

### Get Document Info

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py get DOC_ID
```

### Read Document Content

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py read DOC_ID
```

Returns plain text content of the document.

### Append Text

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py append DOC_ID --text "New content at the end"
```

### Insert Text at Position

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py insert DOC_ID --text "Inserted text" --index 1
```

Note: Google Docs uses 1-based indexing. Index 1 is the start of the document.

### Find and Replace

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py replace DOC_ID --find "old text" --replace "new text"
```

### Export Document

```bash
# Export to PDF
python3 ~/.claude/skills/google-docs-skill/docs_skill.py export DOC_ID --format pdf

# Export to DOCX
python3 ~/.claude/skills/google-docs-skill/docs_skill.py export DOC_ID --format docx --output ~/Downloads/contract.docx

# Export to plain text
python3 ~/.claude/skills/google-docs-skill/docs_skill.py export DOC_ID --format txt
```

**Supported formats:**
- `pdf` - PDF document
- `docx` - Microsoft Word
- `txt` - Plain text
- `html` - HTML
- `odt` - OpenDocument
- `rtf` - Rich Text Format

### Create from Markdown

```bash
python3 ~/.claude/skills/google-docs-skill/docs_skill.py from-markdown ~/Documents/contract.md --title "Contract"
```

Converts markdown file to Google Doc with basic formatting (headings, paragraphs).

### Account Management

```bash
# List accounts
python3 ~/.claude/skills/google-docs-skill/docs_skill.py accounts

# Login
python3 ~/.claude/skills/google-docs-skill/docs_skill.py login --account myemail@gmail.com

# Logout
python3 ~/.claude/skills/google-docs-skill/docs_skill.py logout --account myemail@gmail.com
```

## Examples

### Create a contract and share link

```bash
# Create from markdown
python3 docs_skill.py from-markdown ~/vault/Epoch/Contracts/Agreement.md --title "Constraint PSA"

# Output includes URL:
# "url": "https://docs.google.com/document/d/ABC123/edit"
```

### Export document for email attachment

```bash
python3 docs_skill.py export 1ZPhot-Ao9PrdFEHFLiFBTMEU-q4GPsH-6G6cvljY-xY --format pdf --output ~/Downloads/contract.pdf
```

### Bulk find/replace

```bash
python3 docs_skill.py replace DOC_ID --find "[CLIENT_NAME]" --replace "Epoch ML, Inc."
python3 docs_skill.py replace DOC_ID --find "[DATE]" --replace "February 4, 2026"
```

## Output

All commands output JSON:

```json
{
  "success": true,
  "documentId": "1ZPhot...",
  "title": "My Document",
  "url": "https://docs.google.com/document/d/1ZPhot.../edit"
}
```

## Requirements

```
google-auth
google-auth-oauthlib
google-auth-httplib2
google-api-python-client
```

## Security Notes

- Uses OAuth 2.0 (no passwords stored)
- Tokens stored in `~/.claude/skills/google-docs-skill/tokens/`
- Shares credentials with other Google skills if available

#google #docs #documents #export
