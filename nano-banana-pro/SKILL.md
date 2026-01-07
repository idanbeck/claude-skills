---
name: nano-banana-pro
description: Generate images using AI. Use when the user asks to create, generate, or make images, pictures, graphics, illustrations, visuals, or artwork. Also use for image editing with reference images.
allowed-tools: Bash, Read, Write
---

# Nano Banana Pro - AI Image Generation

Generate images using Google's Gemini 3 Pro Image model.

## Usage

Run the generation script:

```bash
python ~/.claude/skills/nano-banana-pro/generate_image.py "your prompt here" [options]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--resolution` | Output size: 1K, 2K, or 4K | 2K |
| `--aspect` | Aspect ratio: 16:9, 1:1, 4:3, 9:16, 3:4 | 16:9 |
| `--output` | Output directory path | ./generated_images |
| `--reference` | Reference image(s) for style/editing (up to 14) | None |
| `--format` | Output format: png, jpeg, webp | png |

## Examples

### Basic generation

```bash
python ~/.claude/skills/nano-banana-pro/generate_image.py "a serene mountain landscape at sunset, photorealistic"
```

### Square image for social media

```bash
python ~/.claude/skills/nano-banana-pro/generate_image.py "abstract geometric pattern in blue and gold" --aspect 1:1 --resolution 2K
```

### High-res with custom output

```bash
python ~/.claude/skills/nano-banana-pro/generate_image.py "futuristic city skyline" --resolution 4K --output ~/Pictures/ai-generated
```

### Style transfer with reference image

```bash
python ~/.claude/skills/nano-banana-pro/generate_image.py "transform this into a watercolor painting" --reference input.jpg
```

### Image editing with reference

```bash
python ~/.claude/skills/nano-banana-pro/generate_image.py "add a rainbow in the sky" --reference landscape.png
```

## Output

Images are saved with timestamp filenames:
- Format: `{timestamp}_{sanitized_prompt}.{format}`
- Example: `20260106_143052_serene_mountain_landscape.png`

The script outputs the full path to the generated image.

## Requirements

- Python 3.10+
- `google-genai` library
- `GEMINI_API_KEY` environment variable

## Notes

- Gemini 3 Pro Image requires paid billing (no free tier)
- Generated images include SynthID watermarking
- Reference images enable style transfer and editing capabilities
- **No text by default**: The script automatically adds "no text/typography" instructions unless your prompt explicitly mentions text, typography, words, or labels. To include text, add words like "with text overlay" or "include typography" to your prompt.
