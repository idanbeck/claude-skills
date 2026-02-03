# Film Maker Skill

Orchestrate AI film production using Nano Banana (images), Eleven Labs (audio), FAL (video), and FFmpeg (assembly).

## Overview

This skill coordinates the full AI film production pipeline:

```
Script/Idea
    ↓
[nano-banana] → Storyboard frames / scenes
    ↓
[eleven-labs] → Voiceover / dialogue / SFX
    ↓
[fal-video] → Animate frames into video (Kling, Luma, etc.)
    ↓
[ffmpeg] → Assemble final film
```

## Prerequisites

### Required Skills
- `nano-banana-pro` - Image generation
- `eleven-labs-skill` - Voice/audio generation
- `fal-video-skill` - Video generation (Kling, Luma, Minimax, etc.)

### Required Tools
- `ffmpeg` - Video assembly (install via `brew install ffmpeg`)

### Check Dependencies
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py check
```

## Quick Start

### 1. Create a Project
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py new "My Epic Short"
```

### 2. Generate Storyboard Frames
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py frame \
    "A lone astronaut on Mars, looking at Earth in the sky, cinematic lighting" \
    --project my_epic
```

### 3. Generate Audio
```bash
# Voiceover
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py audio \
    --text "I never thought I'd see home again..." \
    --voice "Josh" \
    --project my_epic

# Sound effect
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py audio \
    --sfx "wind howling on barren planet" \
    --duration 10 \
    --project my_epic
```

### 4. Animate Frames
```bash
# Using Kling (default, best quality)
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py animate \
    projects/my_epic_*/images/frame_001.png \
    --prompt "slow camera push in, dust particles floating" \
    --duration 5 \
    --project my_epic

# Using Luma
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py animate \
    projects/my_epic_*/images/frame_001.png \
    --model luma \
    --prompt "gentle parallax movement" \
    --project my_epic
```

### 5. Assemble Final Film
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py assemble my_epic
```

## Commands

### Check Dependencies
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py check
```

### Create New Project
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py new "Project Name"
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py new "Project Name" --resolution 4K --fps 30
```

### Generate Storyboard Frame
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py frame "prompt" --project name
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py frame "prompt" --style cinematic --aspect-ratio 21:9
```

### Generate Audio
```bash
# Speech/voiceover
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py audio --text "Dialogue here" --voice "Rachel"

# Sound effects
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py audio --sfx "explosion in distance" --duration 5
```

### Animate Image to Video
```bash
# Default (Kling)
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py animate image.png --prompt "motion description"

# With model selection
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py animate image.png --model kling-pro --prompt "cinematic motion"
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py animate image.png --model luma --prompt "dreamy movement"

# Auto-save to project
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py animate image.png --prompt "motion" --project my_film
```

**Available video models:**
- `kling` - Best quality (default)
- `kling-pro` - Highest quality, slower
- `luma` - Luma Dream Machine, artistic
- `minimax` - Good for longer clips

### Assemble Final Film
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py assemble project_name
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py assemble project_name --no-audio
```

### List Projects
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py projects
```

### Show Workflow Guide
```bash
python3 ~/.claude/skills/film-maker-skill/film_maker_skill.py workflow
```

## Project Structure

```
projects/
└── my_film_20260202/
    ├── project.json      # Project config
    ├── script.md         # Your screenplay
    ├── images/           # Generated frames
    ├── audio/            # Generated audio
    ├── video/            # Animated clips
    └── output/           # Final film
```

## Production Tips

### Visual Consistency
- Use consistent style keywords across all frame prompts
- Example: Always include "cinematic, shallow depth of field, 35mm film"

### Audio Layering
- Generate dialogue first, then ambient sounds
- Use shorter SFX clips and loop them in post

### Motion Prompts (for animate command)
Good animation prompts:
- "subtle camera drift to the right"
- "character blinks and turns head slowly"
- "clouds moving in background, gentle movement"
- "slow zoom in, atmospheric"
- "parallax depth effect, foreground/background separation"

Avoid:
- Vague prompts like "make it move"
- Too many simultaneous actions

### Pacing
- Keep clips 3-6 seconds for good pacing
- Vary shot lengths for visual interest
- Generate more than you need, select the best

## Adding Music

After assembly, add background music:
```bash
ffmpeg -i film.mp4 -i music.mp3 -c:v copy -c:a aac -shortest final_with_music.mp4
```

Or generate music with Suno:
```bash
python3 ~/.claude/skills/suno-music/suno_skill.py generate "epic cinematic orchestral" --instrumental
```

## Example: 30-Second Film

```bash
# 1. Create project
python3 film_maker_skill.py new "Dawn"

# 2. Generate 6 frames (5 sec each = 30 sec)
python3 film_maker_skill.py frame "sunrise over mountains, mist, cinematic" --project dawn
python3 film_maker_skill.py frame "deer in meadow, golden hour light" --project dawn
python3 film_maker_skill.py frame "river flowing through forest, peaceful" --project dawn
python3 film_maker_skill.py frame "eagle soaring over valley" --project dawn
python3 film_maker_skill.py frame "sun fully risen, bright blue sky" --project dawn
python3 film_maker_skill.py frame "fade to white, peaceful ending" --project dawn

# 3. Generate voiceover
python3 film_maker_skill.py audio --text "Every day brings new light. New hope. New beginnings." --voice "Josh" --project dawn

# 4. Animate each frame (with auto-save to project)
python3 film_maker_skill.py animate projects/dawn_*/images/frame_1.png --prompt "slow zoom out, mist rising" --project dawn
# ... repeat for each frame

# 5. Assemble
python3 film_maker_skill.py assemble dawn
```

## Requirements

```
# Core dependencies are in the individual skills
# This skill just needs Python 3.9+ and ffmpeg
```

## API Keys Required

- **Eleven Labs**: Set up in eleven-labs-skill
- **FAL**: Set up in fal-video-skill (`python3 fal_video_skill.py config YOUR_KEY`)
- **Gemini** (for nano-banana): Set up in nano-banana-pro

## Security Notes

- Uses existing skill configurations
- Project files stored in `~/.claude/skills/film-maker-skill/projects/`

#film #video #production #ai #creative
