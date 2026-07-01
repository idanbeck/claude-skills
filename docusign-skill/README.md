# docusign-skill

Server-to-server DocuSign CLI for the Claude skills set. Send PDFs, anchor-place signature fields, track status, download completed envelopes.

## Install

```bash
pip install -r requirements.txt
```

## Setup (one-time, ~10 min)

1. **In DocuSign Admin → Apps and Keys:**
   - Create an Integration Key
   - Generate an RSA keypair; download the private key to `~/.claude/skills/docusign-skill/private.key`
   - Note your User ID + API Account ID

2. **Run setup:**
   ```bash
   python3 docusign_skill.py setup
   ```

3. **Grant one-time consent:**
   ```bash
   python3 docusign_skill.py consent
   # follow the printed URL in a browser; click Allow
   ```

4. **Verify:**
   ```bash
   python3 docusign_skill.py whoami
   ```

See `SKILL.md` for full command reference.

## Quick test

```bash
python3 docusign_skill.py send-pdf \
  ./my-agreement.pdf \
  --signer "Alice Smith <alice@example.com>" \
  --subject "Please sign" \
  --dry-run
```

Drop `--dry-run` to actually send.

## Notes on environments

- **Production:** `account.docusign.com` (default; pass `--env prod` during setup)
- **Demo / sandbox:** `account-d.docusign.com` (pass `--env demo`)

Note: integration keys are environment-specific. A demo key won't work against prod and vice versa. If you want both, set up the skill twice (different `SKILL_DIR` or rename credentials).
