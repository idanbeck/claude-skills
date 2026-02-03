#!/usr/bin/env python3
"""Film Maker Skill - Orchestrate AI film production using Nano Banana, Eleven Labs, FAL (Kling/Luma), and FFmpeg."""

import argparse
import json
import sys
import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

CONFIG_DIR = Path(__file__).parent
PROJECTS_DIR = CONFIG_DIR / "projects"
SKILLS_DIR = Path.home() / ".claude" / "skills"


def output(data):
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


def run_skill(skill_name, args_list):
    """Run another skill and return result."""
    skill_path = SKILLS_DIR / skill_name / f"{skill_name.replace('-', '_')}.py"

    if not skill_path.exists():
        # Try alternate naming
        alt_path = SKILLS_DIR / skill_name / f"{skill_name.replace('-skill', '_skill')}.py"
        if alt_path.exists():
            skill_path = alt_path
        else:
            return {"error": f"Skill not found: {skill_name}"}

    try:
        result = subprocess.run(
            ["python3", str(skill_path)] + args_list,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"output": result.stdout}
        if result.stderr:
            return {"error": result.stderr}
        return {"status": "completed"}
    except subprocess.TimeoutExpired:
        return {"error": "Skill timeout"}
    except Exception as e:
        return {"error": str(e)}


def check_dependencies():
    """Check if required skills and tools are available."""
    issues = []

    # Check skills
    required_skills = [
        ("nano-banana-pro", "Image generation"),
        ("eleven-labs-skill", "Voice/audio generation"),
        ("fal-video-skill", "Video generation (Kling, Luma, etc.)"),
    ]

    for skill_dir, description in required_skills:
        skill_path = SKILLS_DIR / skill_dir
        if not skill_path.exists():
            issues.append(f"Missing skill: {skill_dir} ({description})")

    # Check ffmpeg
    if not shutil.which("ffmpeg"):
        issues.append("ffmpeg not installed (needed for video assembly)")

    return issues


def cmd_check(args):
    """Check if all dependencies are available."""
    issues = check_dependencies()

    if issues:
        output({
            "status": "incomplete",
            "issues": issues,
            "message": "Some dependencies are missing"
        })
    else:
        output({
            "status": "ready",
            "message": "All dependencies available",
            "skills": ["nano-banana-pro", "eleven-labs-skill", "fal-video-skill"],
            "tools": ["ffmpeg"]
        })


def cmd_new_project(args):
    """Create a new film project."""
    if not args.name:
        output({"error": "Project name required", "usage": "film_maker_skill.py new \"My Film\""})
        return

    # Create project directory
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in args.name)
    safe_name = safe_name.replace(" ", "_").lower()
    timestamp = datetime.now().strftime("%Y%m%d")
    project_dir = PROJECTS_DIR / f"{safe_name}_{timestamp}"

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "images").mkdir(exist_ok=True)
    (project_dir / "audio").mkdir(exist_ok=True)
    (project_dir / "video").mkdir(exist_ok=True)
    (project_dir / "output").mkdir(exist_ok=True)

    # Create project config
    project_config = {
        "name": args.name,
        "created": datetime.now().isoformat(),
        "scenes": [],
        "settings": {
            "resolution": args.resolution or "1920x1080",
            "fps": args.fps or 24,
            "aspect_ratio": "16:9"
        }
    }

    with open(project_dir / "project.json", 'w') as f:
        json.dump(project_config, f, indent=2)

    # Create script template
    script_template = f"""# {args.name} - Script

## Scene 1: Opening
**Visual:** [Describe the opening shot]
**Audio:** [Describe voiceover/music/sfx]
**Duration:** 5 seconds

## Scene 2:
**Visual:** [Describe the shot]
**Audio:** [Describe audio]
**Duration:** 5 seconds

## Scene 3: Closing
**Visual:** [Describe closing shot]
**Audio:** [Describe audio]
**Duration:** 5 seconds
"""

    with open(project_dir / "script.md", 'w') as f:
        f.write(script_template)

    output({
        "status": "success",
        "project": args.name,
        "path": str(project_dir),
        "structure": {
            "project.json": "Project configuration",
            "script.md": "Film script template",
            "images/": "Generated storyboard images",
            "audio/": "Generated audio files",
            "video/": "Generated video clips",
            "output/": "Final assembled film"
        },
        "next_step": f"Edit {project_dir}/script.md to write your script"
    })


def cmd_generate_frame(args):
    """Generate a storyboard frame using nano-banana."""
    if not args.prompt:
        output({"error": "Prompt required"})
        return

    # Find project directory
    project_dir = None
    if args.project:
        project_dir = PROJECTS_DIR / args.project
        if not project_dir.exists():
            # Try to find by partial name
            for p in PROJECTS_DIR.iterdir():
                if args.project.lower() in p.name.lower():
                    project_dir = p
                    break

    # Run nano-banana
    nano_args = ["generate", args.prompt]
    if args.style:
        nano_args.extend(["--style", args.style])
    if args.aspect_ratio:
        nano_args.extend(["--aspect-ratio", args.aspect_ratio])

    result = run_skill("nano-banana-pro", nano_args)

    if "error" in result:
        output(result)
        return

    # Copy to project if specified
    if project_dir and result.get("file"):
        import shutil
        src = Path(result["file"])
        dest = project_dir / "images" / f"frame_{datetime.now().strftime('%H%M%S')}_{src.name}"
        shutil.copy(src, dest)
        result["project_file"] = str(dest)

    output(result)


def cmd_generate_audio(args):
    """Generate audio using eleven-labs."""
    if not args.text and not args.sfx:
        output({"error": "Either --text or --sfx required"})
        return

    if args.sfx:
        # Generate sound effect
        el_args = ["sfx", args.sfx]
        if args.duration:
            el_args.extend(["--duration", str(args.duration)])
    else:
        # Generate speech
        el_args = ["speak", args.text]
        if args.voice:
            el_args.extend(["--voice", args.voice])

    result = run_skill("eleven-labs-skill", el_args)

    # Copy to project if specified
    if args.project and result.get("file"):
        project_dir = None
        for p in PROJECTS_DIR.iterdir():
            if args.project.lower() in p.name.lower():
                project_dir = p
                break

        if project_dir:
            import shutil
            src = Path(result["file"])
            dest = project_dir / "audio" / src.name
            shutil.copy(src, dest)
            result["project_file"] = str(dest)

    output(result)


def cmd_animate(args):
    """Animate an image using FAL (Kling, Luma, etc.)."""
    if not args.image:
        output({"error": "Image path required"})
        return

    # Find project directory to save output
    project_dir = None
    if args.project:
        if PROJECTS_DIR.exists():
            for p in PROJECTS_DIR.iterdir():
                if args.project.lower() in p.name.lower():
                    project_dir = p
                    break

    # Build FAL video skill args
    fal_args = ["i2v", args.image]
    if args.prompt:
        fal_args.extend(["--prompt", args.prompt])
    if args.duration:
        fal_args.extend(["--duration", str(args.duration)])
    if args.model:
        fal_args.extend(["--model", args.model])

    # If project specified, output directly to project video folder
    if project_dir:
        timestamp = datetime.now().strftime("%H%M%S")
        output_path = project_dir / "video" / f"clip_{timestamp}.mp4"
        fal_args.extend(["--output", str(output_path)])

    result = run_skill("fal-video-skill", fal_args)

    # Add project info to result
    if project_dir and "file" in result:
        result["project"] = str(project_dir)
        result["project_file"] = result.get("file")

    output(result)


def cmd_assemble(args):
    """Assemble video clips and audio into final film using ffmpeg."""
    if not args.project:
        output({"error": "Project name required"})
        return

    # Find project
    project_dir = None
    for p in PROJECTS_DIR.iterdir():
        if args.project.lower() in p.name.lower():
            project_dir = p
            break

    if not project_dir:
        output({"error": f"Project not found: {args.project}"})
        return

    video_dir = project_dir / "video"
    audio_dir = project_dir / "audio"
    output_dir = project_dir / "output"

    # Get video files
    video_files = sorted(video_dir.glob("*.mp4"))
    if not video_files:
        output({"error": "No video files found in project"})
        return

    # Create file list for ffmpeg concat
    concat_file = project_dir / "concat.txt"
    with open(concat_file, 'w') as f:
        for vf in video_files:
            f.write(f"file '{vf}'\n")

    # Output filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"film_{timestamp}.mp4"

    # Assemble video clips
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_dir / "video_only.mp4")
    ]

    try:
        subprocess.run(concat_cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        output({"error": f"Video concatenation failed: {e.stderr.decode()}"})
        return

    # Check for audio
    audio_files = sorted(audio_dir.glob("*.mp3")) + sorted(audio_dir.glob("*.wav"))

    if audio_files and not args.no_audio:
        # Concatenate audio files
        if len(audio_files) > 1:
            audio_concat = project_dir / "audio_concat.txt"
            with open(audio_concat, 'w') as f:
                for af in audio_files:
                    f.write(f"file '{af}'\n")

            audio_concat_cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(audio_concat),
                "-c", "copy",
                str(project_dir / "audio_combined.mp3")
            ]
            subprocess.run(audio_concat_cmd, capture_output=True, check=True)
            combined_audio = project_dir / "audio_combined.mp3"
        else:
            combined_audio = audio_files[0]

        # Merge video and audio
        merge_cmd = [
            "ffmpeg", "-y",
            "-i", str(output_dir / "video_only.mp4"),
            "-i", str(combined_audio),
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output_file)
        ]
        subprocess.run(merge_cmd, capture_output=True, check=True)

        # Clean up
        (output_dir / "video_only.mp4").unlink(missing_ok=True)
    else:
        # Just rename video-only file
        (output_dir / "video_only.mp4").rename(output_file)

    # Get file info
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(output_file)
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True)
    duration = "unknown"
    if probe_result.returncode == 0:
        try:
            probe_data = json.loads(probe_result.stdout)
            duration = probe_data.get("format", {}).get("duration", "unknown")
        except:
            pass

    output({
        "status": "success",
        "file": str(output_file),
        "duration": duration,
        "video_clips": len(video_files),
        "audio_tracks": len(audio_files) if not args.no_audio else 0
    })


def cmd_list_projects(args):
    """List all film projects."""
    if not PROJECTS_DIR.exists():
        output({"projects": [], "count": 0})
        return

    projects = []
    for p in sorted(PROJECTS_DIR.iterdir()):
        if p.is_dir() and (p / "project.json").exists():
            with open(p / "project.json") as f:
                config = json.load(f)

            projects.append({
                "name": config.get("name"),
                "path": str(p),
                "created": config.get("created"),
                "scenes": len(config.get("scenes", [])),
                "images": len(list((p / "images").glob("*"))) if (p / "images").exists() else 0,
                "audio": len(list((p / "audio").glob("*"))) if (p / "audio").exists() else 0,
                "video": len(list((p / "video").glob("*"))) if (p / "video").exists() else 0,
            })

    output({"projects": projects, "count": len(projects)})


def cmd_workflow(args):
    """Show the recommended film production workflow."""
    workflow = """
# AI Film Production Workflow

## 1. Create Project
```bash
python3 film_maker_skill.py new "My Short Film"
```

## 2. Write Script
Edit `projects/my_short_film_YYYYMMDD/script.md` with your scenes.

## 3. Generate Storyboard Frames
For each scene, generate an image:
```bash
python3 film_maker_skill.py frame "A hero standing on a cliff at sunset, cinematic" --project my_short
```

## 4. Generate Audio
Create voiceover and sound effects:
```bash
# Voiceover
python3 film_maker_skill.py audio --text "In a world where..." --voice "Josh" --project my_short

# Sound effects
python3 film_maker_skill.py audio --sfx "wind howling" --duration 10 --project my_short
```

## 5. Animate Frames
Convert images to video clips:
```bash
python3 film_maker_skill.py animate projects/my_short/images/frame_001.png --prompt "camera slowly pushes in" --duration 5
```
Then copy resulting video to projects/my_short/video/

## 6. Assemble Final Film
```bash
python3 film_maker_skill.py assemble my_short
```

## Tips
- Keep clips 3-6 seconds for pacing
- Use consistent style prompts for visual coherence
- Generate more footage than needed, then select the best
- Add music with: ffmpeg -i film.mp4 -i music.mp3 -c:v copy -c:a aac final.mp4
"""
    print(workflow)


def main():
    parser = argparse.ArgumentParser(description="AI Film Production Pipeline")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Check dependencies
    subparsers.add_parser("check", help="Check if all dependencies are available")

    # New project
    new_parser = subparsers.add_parser("new", help="Create a new film project")
    new_parser.add_argument("name", nargs="?", help="Project name")
    new_parser.add_argument("--resolution", "-r", default="1920x1080", help="Video resolution")
    new_parser.add_argument("--fps", type=int, default=24, help="Frames per second")

    # Generate frame
    frame_parser = subparsers.add_parser("frame", help="Generate a storyboard frame")
    frame_parser.add_argument("prompt", nargs="?", help="Image description")
    frame_parser.add_argument("--project", "-p", help="Project name")
    frame_parser.add_argument("--style", "-s", help="Style preset")
    frame_parser.add_argument("--aspect-ratio", "-a", default="16:9", help="Aspect ratio")

    # Generate audio
    audio_parser = subparsers.add_parser("audio", help="Generate audio")
    audio_parser.add_argument("--text", "-t", help="Text for speech")
    audio_parser.add_argument("--sfx", help="Sound effect description")
    audio_parser.add_argument("--voice", "-v", help="Voice for speech")
    audio_parser.add_argument("--duration", "-d", type=float, help="Duration for SFX")
    audio_parser.add_argument("--project", "-p", help="Project name")

    # Animate
    animate_parser = subparsers.add_parser("animate", help="Animate an image")
    animate_parser.add_argument("image", nargs="?", help="Image path")
    animate_parser.add_argument("--prompt", "-p", help="Motion prompt")
    animate_parser.add_argument("--duration", "-d", type=int, default=5, help="Duration in seconds")
    animate_parser.add_argument("--model", "-m", default="kling", help="Model: kling, kling-pro, luma, minimax")
    animate_parser.add_argument("--project", help="Project name (auto-saves to video folder)")

    # Assemble
    assemble_parser = subparsers.add_parser("assemble", help="Assemble final film")
    assemble_parser.add_argument("project", nargs="?", help="Project name")
    assemble_parser.add_argument("--no-audio", action="store_true", help="Skip audio")

    # List projects
    subparsers.add_parser("projects", help="List all projects")

    # Workflow guide
    subparsers.add_parser("workflow", help="Show production workflow guide")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "check": cmd_check,
        "new": cmd_new_project,
        "frame": cmd_generate_frame,
        "audio": cmd_generate_audio,
        "animate": cmd_animate,
        "assemble": cmd_assemble,
        "projects": cmd_list_projects,
        "workflow": cmd_workflow,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
