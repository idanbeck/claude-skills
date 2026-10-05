#!/bin/zsh
# Weekly paper compendium: runs Sunday 09:00 via launchd (com.idanbeck.paper-explainer-weekly).
export PATH="/opt/homebrew/bin:/Library/TeX/texbin:/Users/idanbeck/.local/bin:/usr/local/bin:/usr/bin:/bin"
LOG=~/paper-videos/weekly.log
mkdir -p ~/paper-videos
cd "/Users/idanbeck/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck" || exit 1
COUNT=$(python3 ~/.claude/skills/paper-explainer/pe.py week 2>>$LOG | python3 -c "import json,sys;print(len(json.load(sys.stdin)['items']))" 2>>$LOG)
# An empty COUNT means the queue could not be read (pe.py already retries iCloud offloading). Proceed anyway and let
# the agent re-check, rather than silently skipping the week.
echo "$(date) papers this week: $COUNT" >> $LOG
[ "$COUNT" = "0" ] && exit 0
/Users/idanbeck/.local/bin/claude -p --dangerously-skip-permissions \
  "Use the paper-explainer skill and follow its Weekly compendium section exactly: build the compendium with tools/compendium.py (Downloads folder + vault copy), write and fact-check the weekly dialogue before any TTS, render the weekly podcast, write the weekly vault note, then DM Idan on Slack with the Downloads folder path, the plain link list from Links.md, and a 3-line summary of the threads across this week's papers. Never print config files, tokens or environment variables." \
  >> $LOG 2>&1
