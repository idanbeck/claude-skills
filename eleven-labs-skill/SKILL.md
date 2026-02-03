# Eleven Labs Skill

AI-powered voice generation, voice cloning, and sound effects using Eleven Labs.

## Getting API Access

1. Sign up at https://elevenlabs.io
2. Go to Profile → API Keys
3. Copy your API key

**Pricing:** Free tier includes limited characters/month. Paid plans for more usage and voice cloning.

## Setup

```bash
# Install dependencies
pip3 install elevenlabs

# Configure API key
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py setup YOUR_API_KEY
```

## Commands

### List Available Voices

```bash
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py voices
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py voices --category premade
```

### Generate Speech (Text-to-Speech)

```bash
# Basic usage (default voice)
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py speak "Hello, welcome to our film."

# With specific voice
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py speak "Hello world" --voice "Rachel"
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py speak "Hello world" --voice "Adam"

# With specific model
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py speak "Hello" --model eleven_multilingual_v2
```

Output saved to `~/.claude/skills/eleven-labs-skill/output/`

### Clone a Voice

```bash
# Provide 1-3 audio samples of the voice to clone
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py clone "My Voice" sample1.mp3 sample2.mp3

# With description
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py clone "Narrator" audio.mp3 --description "Deep narrator voice"
```

**Tips for voice cloning:**
- Use clean audio with minimal background noise
- 1-3 minutes of audio works best
- Consistent speaking style improves results

### Generate Sound Effects

```bash
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py sfx "thunder rolling in the distance"
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py sfx "footsteps on gravel" --duration 3
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py sfx "crowd cheering in a stadium" --duration 10
```

### List Models

```bash
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py models
```

### View Generation History

```bash
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py history
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py history --limit 50
```

### Delete a Cloned Voice

```bash
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py delete-voice VOICE_ID
```

## Output

All audio files saved to `~/.claude/skills/eleven-labs-skill/output/`

```json
{
  "status": "success",
  "file": "/Users/you/.claude/skills/eleven-labs-skill/output/speech_20260202_153000.mp3",
  "text": "Hello, welcome to our film.",
  "voice": "21m00Tcm4TlvDq8ikWAM"
}
```

## Popular Voices

| Name | Style | Good For |
|------|-------|----------|
| Rachel | Neutral American | Narration, general |
| Adam | Deep American | Trailers, dramatic |
| Bella | British | Storytelling |
| Antoni | American | Conversational |
| Elli | American Young | Animation, youth |
| Josh | American Deep | Documentary |
| Arnold | American Crisp | Professional |
| Sam | American Raspy | Character work |

## Use with Film-Maker Skill

This skill integrates with the film-maker skill for full production:

```bash
# Generate dialogue for a scene
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py speak "To be or not to be" --voice "Josh"

# Generate ambient sound
python3 ~/.claude/skills/eleven-labs-skill/eleven_labs_skill.py sfx "rain on window" --duration 30
```

## Requirements

```
elevenlabs>=1.0.0
```

## Security Notes

- API key stored in `~/.claude/skills/eleven-labs-skill/config.json`
- Can also use `ELEVENLABS_API_KEY` environment variable

#elevenlabs #voice #tts #audio #film
