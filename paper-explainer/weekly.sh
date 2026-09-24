#!/bin/zsh
# Weekly paper compendium: runs Sunday 09:00 via launchd (com.idanbeck.paper-explainer-weekly).
export PATH="/opt/homebrew/bin:/Library/TeX/texbin:/Users/idanbeck/.local/bin:/usr/local/bin:/usr/bin:/bin"
LOG=~/paper-videos/weekly.log
mkdir -p ~/paper-videos
cd "/Users/idanbeck/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck" || exit 1
COUNT=$(python3 ~/.claude/skills/paper-explainer/pe.py week | python3 -c "import json,sys;print(len(json.load(sys.stdin)['items']))")
echo "$(date) papers this week: $COUNT" >> $LOG
[ "$COUNT" = "0" ] && exit 0
/Users/idanbeck/.local/bin/claude -p --dangerously-skip-permissions \
  "Use the paper-explainer skill to build this week's paper compendium (stitched video + weekly podcast episode + weekly vault note), then DM Idan on Slack with the vault note path and a 3-line summary of the threads across this week's papers." \
  >> $LOG 2>&1
