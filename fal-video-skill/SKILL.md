# FAL Video Skill

Generate videos using FAL.ai - access to Kling, Luma Dream Machine, Minimax, Runway, and more through a single API.

## Setup

1. Get API key from https://fal.ai/dashboard/keys
2. Configure:
```bash
python3 ~/.claude/skills/fal-video-skill/fal_video_skill.py config YOUR_API_KEY
```

Or set environment variable:
```bash
export FAL_KEY="your_api_key"
```

## Commands

### Image to Video (i2v)

Animate a still image:

```bash
python3 ~/.claude/skills/fal-video-skill/fal_video_skill.py i2v IMAGE [OPTIONS]
```

**Arguments:**
- `IMAGE` - Path to local image or URL
- `--prompt, -p` - Motion/animation prompt (e.g., "camera slowly zooms in, subtle movement")
- `--model, -m` - Model to use (default: kling)
- `--duration, -d` - Duration in seconds (default: 5)
- `--aspect-ratio, -a` - Aspect ratio: 16:9, 9:16, 1:1
- `--output, -o` - Output file path
- `--timeout, -t` - Timeout in seconds (default: 300)

**Examples:**
```bash
# Basic image animation
python3 fal_video_skill.py i2v hero_shot.png --prompt "slow camera push in, dust particles floating"

# Using Luma model
python3 fal_video_skill.py i2v scene.jpg --model luma --prompt "gentle breeze, leaves rustling"

# Pro quality with Kling
python3 fal_video_skill.py i2v portrait.png --model kling-pro --duration 10

# Vertical video for social
python3 fal_video_skill.py i2v image.png --aspect-ratio 9:16 --prompt "dynamic motion"
```

### Text to Video (t2v)

Generate video from text description:

```bash
python3 ~/.claude/skills/fal-video-skill/fal_video_skill.py t2v PROMPT [OPTIONS]
```

**Arguments:**
- `PROMPT` - Video description
- `--model, -m` - Model to use (default: kling-t2v)
- `--duration, -d` - Duration in seconds
- `--aspect-ratio, -a` - Aspect ratio
- `--output, -o` - Output file path

**Examples:**
```bash
# Generate from text
python3 fal_video_skill.py t2v "A lone astronaut walking on Mars, cinematic lighting, dust swirling"

# Hunyuan (open source model)
python3 fal_video_skill.py t2v "Ocean waves crashing on rocks at sunset" --model hunyuan

# Minimax for longer content
python3 fal_video_skill.py t2v "A timelapse of a flower blooming" --model minimax-t2v
```

### List Models

```bash
python3 ~/.claude/skills/fal-video-skill/fal_video_skill.py models
```

### Check Config

```bash
python3 ~/.claude/skills/fal-video-skill/fal_video_skill.py config
```

## Available Models

### Image to Video
| Model | Quality | Speed | Best For |
|-------|---------|-------|----------|
| `kling` | Excellent | Medium | General i2v, best quality |
| `kling-pro` | Best | Slow | High-quality production |
| `luma` | Great | Medium | Creative, artistic motion |
| `minimax` | Good | Fast | Longer clips |
| `runway` | Excellent | Medium | Professional production |
| `svd` | Good | Fast | Quick previews |

### Text to Video
| Model | Quality | Speed | Best For |
|-------|---------|-------|----------|
| `kling-t2v` | Excellent | Medium | General t2v |
| `kling-pro-t2v` | Best | Slow | High-quality production |
| `minimax-t2v` | Good | Fast | Longer content |
| `hunyuan` | Good | Medium | Open source, no restrictions |
| `luma` | Great | Medium | Creative content |

## Motion Prompt Tips

Good prompts for i2v:
- "slow camera push in, atmospheric"
- "subtle parallax effect, depth movement"
- "character blinks and turns head slowly"
- "wind blowing through hair, gentle motion"
- "clouds drifting in background"
- "water ripples, reflections moving"

Avoid:
- Vague prompts like "make it move"
- Too many simultaneous actions
- Physically impossible motion

## Output

Videos are saved to `~/.claude/skills/fal-video-skill/output/` by default.

JSON output includes:
```json
{
  "status": "success",
  "model": "kling",
  "file": "/path/to/video.mp4",
  "url": "https://fal.media/...",
  "duration": 5
}
```

## Pricing (approximate)

FAL uses pay-per-use pricing:
- Kling Standard: ~$0.05/second
- Kling Pro: ~$0.10/second
- Luma: ~$0.03/second
- Minimax: ~$0.02/second
- Hunyuan: ~$0.01/second

A 5-second Kling video costs ~$0.25.

## Integration with Film Maker

This skill is designed to work with the film-maker-skill:

```bash
# Generate frame with nano-banana
python3 nano_banana_skill.py generate "astronaut on mars, cinematic"

# Animate with FAL
python3 fal_video_skill.py i2v output/image.png --prompt "slow zoom, dust particles"

# Add to film project
cp output/video.mp4 ~/film_project/video/scene_01.mp4
```

## Requirements

```
requests>=2.28.0
```

## Security Notes

- API key stored in `~/.claude/skills/fal-video-skill/config.json` with 600 permissions
- Can also use `FAL_KEY` or `FAL_API_KEY` environment variables
- Videos downloaded locally, URLs expire after ~24 hours

#video #ai #fal #kling #luma #film
