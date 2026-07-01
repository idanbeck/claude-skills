"""Paths, knobs, and constants for the linkedin-recruiting skill."""
import os
import shutil
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent          # .../linkedin-recruiting
SKILLS_ROOT = SKILL_DIR.parent                              # .../.claude/skills

DB_PATH = SKILL_DIR / "recruiting.db"
ROLE_PROFILE_DIR = SKILL_DIR / "role_profiles"
PROMPTS_DIR = SKILL_DIR / "prompts"
RESUMES_DIR = SKILL_DIR / "resumes"
EVIDENCE_DIR = SKILL_DIR / "evidence"

# Sibling skills we shell out to (never reimplement their auth)
GMAIL_SKILL = SKILLS_ROOT / "gmail-skill" / "gmail_skill.py"
PLAYWRIGHT_SKILL = SKILLS_ROOT / "playwright-skill" / "playwright_skill.py"

# Vault (Obsidian)
VAULT_ROOT = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    "/Users/idanbeck/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck",
))
TEMPLATE_PATH = VAULT_ROOT / "templates" / "Interview Candidate.md"
RECRUITING_DIR = VAULT_ROOT / "People" / "Recruiting"
COMP_ANALYSIS = VAULT_ROOT / "Epoch" / "People" / "Comp Analysis.md"
PERSONAS_DIR = VAULT_ROOT / "Personas"
WRITING_STYLE = VAULT_ROOT / "writing_style.md"
FRANKLIN_ANCHOR = RECRUITING_DIR / "Franklin Yiu.md"

# Email channel
DEFAULT_GMAIL_ACCOUNT = "idan@zergai.com"
DIGEST_QUERY = "from:jobs-listings@linkedin.com"

# Burner browser (in-process Playwright; cookies persisted to this state file)
BURNER_SESSION = "linkedin_burner"
BURNER_STATE = SKILL_DIR / "burner_state.json"

# Model invocation (house pattern: claude -p)
CLAUDE_BIN = (os.environ.get("CLAUDE_BIN")
              or shutil.which("claude")
              or os.path.expanduser("~/.local/bin/claude"))
CLAUDE_TIMEOUT_S = 600

# Tier thresholds on the 1-5 overall score (tunable)
TIER_REACH_OUT = 3.8
TIER_MAYBE = 3.0

# Burner pacing (seconds)
PACE_MIN = 6
PACE_MAX = 15
PACE_BIG_EVERY = 10
PACE_BIG_MIN = 60
PACE_BIG_MAX = 120

# Auto-managed block sentinels in vault candidate pages
AUTO_START = "<!-- lr:auto:start -->"
AUTO_END = "<!-- lr:auto:end -->"
