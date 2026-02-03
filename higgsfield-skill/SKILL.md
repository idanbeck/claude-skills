# Higgsfield Skill

AI video generation - create videos from images or text prompts using Higgsfield AI.

## Getting API Access

1. Sign up at https://higgsfield.ai
2. Request API access (may require waitlist)
3. Get your API key from the dashboard

**Note:** API access may be limited. Check Higgsfield's current availability.

## Setup

```bash
# Install dependencies
pip3 install requests

# Configure API key
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py setup YOUR_API_KEY
```

## Commands

### Image-to-Video (i2v)

Animate a static image into video:

```bash
# Basic usage
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py i2v image.png

# With motion prompt
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py i2v character.png --prompt "character turns head and smiles"

# With more options
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py i2v scene.jpg \
    --prompt "camera slowly zooms in" \
    --duration 6 \
    --motion 0.7
```

**Options:**
- `--prompt, -p` - Describe the motion/animation
- `--duration, -d` - Video length in seconds (default: 4)
- `--fps` - Frames per second (default: 24)
- `--motion, -m` - Motion strength 0.0-1.0 (default: 0.5)
- `--negative-prompt, -n` - What to avoid

### Text-to-Video (t2v)

Generate video from a text description:

```bash
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py t2v "A sunset over calm ocean waves"

python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py t2v "A robot walking through a futuristic city" \
    --duration 6 \
    --aspect-ratio "16:9" \
    --style "cinematic"
```

**Options:**
- `--duration, -d` - Video length in seconds
- `--fps` - Frames per second
- `--aspect-ratio, -a` - Video aspect ratio (default: 16:9)
- `--style, -s` - Style preset
- `--negative-prompt, -n` - What to avoid

### Check Generation Status

```bash
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py status GENERATION_ID

# Auto-download when complete
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py status GENERATION_ID --download
```

### Wait for Completion

Submit and wait until the video is ready:

```bash
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py wait GENERATION_ID

# With custom timeout (default: 5 minutes)
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py wait GENERATION_ID --timeout 120
```

### Download Video

```bash
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py download GENERATION_ID
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py download GENERATION_ID --output my_video.mp4
```

### List Recent Generations

```bash
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py list
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py list --limit 50
```

## Output

All videos saved to `~/.claude/skills/higgsfield-skill/output/`

```json
{
  "status": "submitted",
  "generation_id": "gen_abc123",
  "message": "Video generation started. Use 'status' command to check progress.",
  "check_command": "python3 higgsfield_skill.py status gen_abc123"
}
```

## Workflow Example

```bash
# 1. Generate a storyboard frame with nano-banana
# (creates image.png)

# 2. Animate the frame
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py i2v image.png \
    --prompt "character walks forward, camera follows" \
    --duration 4

# 3. Wait for completion (saves to output/)
python3 ~/.claude/skills/higgsfield-skill/higgsfield_skill.py wait gen_abc123
```

## Use with Film-Maker Skill

This skill is designed to work with the film-maker orchestration skill:

1. **nano-banana** generates storyboard images
2. **higgsfield** animates them into video clips
3. **eleven-labs** adds voiceover and sound effects
4. **ffmpeg** combines everything into the final film

## Motion Prompt Tips

For best results with image-to-video:

- Be specific about camera movement: "camera slowly pans left"
- Describe character actions: "person turns and walks away"
- Include environmental motion: "leaves rustling in wind"
- Use intensity modifiers: "subtle", "gentle", "dramatic"

**Good prompts:**
- "Gentle zoom in on face, soft lighting"
- "Character blinks and smiles subtly"
- "Camera dollies around subject, cinematic motion blur"

**Avoid:**
- Vague prompts like "make it move"
- Contradictory instructions
- Too many simultaneous actions

## Requirements

```
requests>=2.28.0
```

## Security Notes

- API key stored in `~/.claude/skills/higgsfield-skill/config.json`
- Can also use `HIGGSFIELD_API_KEY` environment variable

#higgsfield #video #ai #animation #film
