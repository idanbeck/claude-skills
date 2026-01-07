#!/usr/bin/env python3
"""
Nano Banana Pro - AI Image Generation using Gemini 3 Pro Image

Usage:
    python generate_image.py "prompt" [options]

Options:
    --resolution    1K, 2K, or 4K (default: 2K)
    --aspect        Aspect ratio like 16:9, 1:1, 4:3 (default: 16:9)
    --output        Output directory (default: ./generated_images)
    --reference     Reference image(s) for style/editing
    --format        Output format: png, jpeg, webp (default: png)
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: google-genai library not installed.")
    print("Install with: pip install google-genai")
    sys.exit(1)


# Resolution mapping
RESOLUTIONS = {
    "1K": (1024, 1024),
    "2K": (2048, 2048),
    "4K": (4096, 4096),
}

# Aspect ratio mapping (width, height multipliers)
ASPECT_RATIOS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "1:1": (1, 1),
    "3:2": (3, 2),
    "2:3": (2, 3),
}


def sanitize_filename(text: str, max_length: int = 50) -> str:
    """Convert prompt to safe filename."""
    # Remove special characters, keep alphanumeric and spaces
    clean = re.sub(r'[^\w\s-]', '', text.lower())
    # Replace spaces with underscores
    clean = re.sub(r'\s+', '_', clean)
    # Truncate
    return clean[:max_length]


def calculate_dimensions(resolution: str, aspect: str) -> tuple[int, int]:
    """Calculate pixel dimensions from resolution and aspect ratio."""
    base_size = RESOLUTIONS.get(resolution, RESOLUTIONS["2K"])[0]
    aspect_w, aspect_h = ASPECT_RATIOS.get(aspect, ASPECT_RATIOS["16:9"])

    # Scale to fit within base_size while maintaining aspect
    if aspect_w >= aspect_h:
        width = base_size
        height = int(base_size * aspect_h / aspect_w)
    else:
        height = base_size
        width = int(base_size * aspect_w / aspect_h)

    return width, height


def load_reference_images(paths: list[str]) -> list:
    """Load reference images for style transfer/editing."""
    images = []
    for path in paths:
        path = Path(path).expanduser()
        if path.exists():
            with open(path, "rb") as f:
                image_data = f.read()
            # Determine mime type
            suffix = path.suffix.lower()
            mime_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }
            mime_type = mime_types.get(suffix, "image/png")
            images.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))
        else:
            print(f"Warning: Reference image not found: {path}")
    return images


def generate_image(
    prompt: str,
    resolution: str = "2K",
    aspect: str = "16:9",
    output_dir: str = "./generated_images",
    reference_images: list[str] = None,
    output_format: str = "png",
) -> str:
    """Generate an image using Gemini 3 Pro Image model."""

    # Check for API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    # Initialize client
    client = genai.Client(api_key=api_key)

    # Create output directory
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    # Calculate dimensions
    width, height = calculate_dimensions(resolution, aspect)

    # Build content parts
    contents = []

    # Add reference images if provided
    if reference_images:
        ref_images = load_reference_images(reference_images)
        contents.extend(ref_images)

    # Add the text prompt (with no-text instruction unless user wants text)
    if "text" not in prompt.lower() and "typography" not in prompt.lower() and "words" not in prompt.lower() and "label" not in prompt.lower():
        prompt = f"{prompt}. Do not include any text, words, labels, or typography in the image."
    contents.append(prompt)

    # Generate image
    print(f"Generating image: {prompt[:50]}...")
    print(f"Resolution: {resolution}, Aspect: {aspect}")

    try:
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect,
                ),
            ),
        )

        # Extract image from response
        image_data = None
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                image_data = part.inline_data.data
                break

        if not image_data:
            print("Error: No image generated in response.")
            if response.text:
                print(f"Model response: {response.text}")
            sys.exit(1)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prompt = sanitize_filename(prompt)
        filename = f"{timestamp}_{safe_prompt}.{output_format}"
        filepath = output_path / filename

        # Save image
        with open(filepath, "wb") as f:
            f.write(image_data)

        print(f"Image saved: {filepath}")
        return str(filepath)

    except Exception as e:
        print(f"Error generating image: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate images using Gemini 3 Pro Image model"
    )
    parser.add_argument("prompt", help="Image generation prompt")
    parser.add_argument(
        "--resolution",
        choices=["1K", "2K", "4K"],
        default="2K",
        help="Output resolution (default: 2K)",
    )
    parser.add_argument(
        "--aspect",
        choices=list(ASPECT_RATIOS.keys()),
        default="16:9",
        help="Aspect ratio (default: 16:9)",
    )
    parser.add_argument(
        "--output",
        default="./generated_images",
        help="Output directory (default: ./generated_images)",
    )
    parser.add_argument(
        "--reference",
        nargs="+",
        help="Reference image(s) for style transfer or editing",
    )
    parser.add_argument(
        "--format",
        choices=["png", "jpeg", "webp"],
        default="png",
        help="Output format (default: png)",
    )

    args = parser.parse_args()

    generate_image(
        prompt=args.prompt,
        resolution=args.resolution,
        aspect=args.aspect,
        output_dir=args.output,
        reference_images=args.reference,
        output_format=args.format,
    )


if __name__ == "__main__":
    main()
