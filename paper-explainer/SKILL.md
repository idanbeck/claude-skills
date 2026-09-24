---
name: paper-explainer
description: Turn a research paper into a narrated 3Blue1Brown-style Manim explainer video plus a two-host podcast episode, and file both in the Obsidian vault next to the paper note. Use EVERY time Idan asks to add a paper to the knowledge base and/or zergscholar (after the vault note + scholar push), when he asks for a video/podcast/explainer of a paper, and for the weekly paper compendium ("weekly compendium", "this week's papers").
---

# Paper Explainer

Every paper added to the knowledge base gets:
1. **An explainer video**: 5–8 min, 1080p30, Manim animation, ElevenLabs narration, soft CC captions + `.srt`.
2. **A podcast episode**: 5–8 min, two voices (host asks, guest explains), loudness-normalized mp3.
3. **A vault video note** at `Reading/Videos/<Title>.md` that embeds both, with a transcript, linked both ways with the paper note.

Once a week there is also a **compendium**: all of the week's videos stitched together, plus one longer podcast episode covering the week.

Tooling lives here: `~/.claude/skills/paper-explainer/`
- `pe.py`: CLI (`tts`, `render`, `podcast`, `publish`, `week`, `stitch`)
- `lib/narrated.py`: Manim base class `NarratedScene` + palette/helpers (`T`, `pill`, `title_card`, `bar_chart`)
- `.venv/`: Manim Community 0.21 (system: ffmpeg, MacTeX, cairo/pango)
- `weekly.sh` + launchd `com.idanbeck.paper-explainer-weekly`: Sunday 09:00 compendium

Work directory per paper: `~/paper-videos/<slug>/` (outside iCloud, so render scratch never syncs). Only the finished outputs are copied into the vault.

## Per-paper workflow

Do this right after the vault note and zergscholar push succeed. The video is the reason the user wants papers added, so don't skip it and don't wait to be asked.

### 1. Understand the paper visually
Read the PDF pages directly, not just the abstract: figures, the method diagram, the main results table, and the ablation. Explainers work when they are built on the paper's own figures and real numbers. Pick:
- the **one-sentence thesis**
- the **problem picture**: what goes wrong without this idea
- the **mechanism**: 2–4 components, each one visual
- the **one result that proves it**, plus the most instructive ablation or failure case
- the **takeaway**

### 2. Write `script.json` (narration)
```json
{"title": "...", "voice": "narrator",
 "segments": [{"id": "s01", "narration": "..."}, {"id": "s02", "narration": "..."}]}
```
- 10–14 segments, 20–40 s each, **800–1,000 words total** (≈5.5–7 min at ElevenLabs pace).
- One idea per segment. The narration drives the animation, so write sentences that can be drawn.
- 3Blue1Brown register: concrete before abstract, a question before the answer, real numbers from the paper, no hype words. Follow the vault writing style: short sentences, plain words, few em dashes.
- Write numbers and symbols the way they should be *spoken* ("ninety two point eight", "L zero style", "delta").
- Keep claims exact. Anything that is the paper's own claim stays attributed to the paper; skeptical notes from the vault analysis can go in the final segment.

Run `python3 ~/.claude/skills/paper-explainer/pe.py tts script.json --workdir .`. It caches by text hash, so editing one segment re-bills only that segment. It writes `durations.json`.

### 3. Write `scene.py` (Manim)
```python
from narrated import *
class S01(NarratedScene):        # class name == segment id, uppercased
    def construct(self):
        ...                       # build visuals
        self.until(0.4)           # wait until 40% through this segment's narration
        ...
```
- `NarratedScene` pads each scene to its narration length, so audio sync is automatic. Use `self.until(frac)` to land visual beats on the words (read `durations.json` and the narration to choose fractions).
- Palette: `BG FG MUTED BLUE TEAL YELLOW RED GREEN PURPLE`. Text via `T(text, size, color)`. `MathTex` works (MacTeX installed). Helpers: `pill`, `title_card`, `bar_chart(values, labels, colors, max_value, fmt)`.
- Visual grammar: build up incrementally, never show a finished slide; one focal element at a time; recreate the paper's key figure as an animated chart with real numbers; show equations only when the narration explains them; move or fade old elements before adding new ones; keep 0.3–0.5 margins from the frame edge.
- When bars start near the same value, truncate the axis and label it "axes truncated".

### 4. Render with a QA loop (required)
```bash
python3 ~/.claude/skills/paper-explainer/pe.py render script.json scene.py --workdir . --quality l
```
Then build a contact sheet of every scene's final frame and **look at it**:
```bash
mkdir -p qa; for f in segments/s*.mp4; do d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f"); ffmpeg -y -v error -ss $(python3 -c "print(max(0,$d-0.6))") -i "$f" -frames:v 1 qa/$(basename $f .mp4).png; done
ffmpeg -y -v error -pattern_type glob -i 'qa/s*.png' -filter_complex "scale=640:-1,tile=3x5:padding=6:color=white" -frames:v 1 qa/sheet.png
```
Check for overlaps, text running off the frame, labels inside shaded regions, and misaligned baselines. Fix, then re-render only what changed with `--only s02,s09`. When it's clean, run the final pass with `--quality h` (1080p30, about 1 min of render per 6 min of video).

### 5. Podcast `dialogue.json`
```json
{"title": "Paper Explainer — <title>", "voices": {"A": "host", "B": "guest"},
 "lines": [{"speaker": "A", "text": "..."}, {"speaker": "B", "text": "..."}]}
```
About 900–1,100 words, 25–35 lines. A (Alice, curious host) asks the questions a smart outsider would ask; B (Brian) explains with concrete examples. Cover the same arc as the video, but talk it through; don't read the video script aloud. End with "what would you take from this if you were building X tomorrow." Then run `pe.py podcast dialogue.json --workdir . --out <slug>-podcast.mp3`.

### 6. Publish
```bash
python3 ~/.claude/skills/paper-explainer/pe.py publish script.json --workdir . \
  --title "<vault-safe paper title>" --paper-note "Reading/Research/<note>.md" \
  --podcast <slug>-podcast.mp3 --scene scene.py --dialogue dialogue.json
```
This copies the mp4/srt/mp3/sources into `Reading/Videos/<Title>/`, writes `Reading/Videos/<Title>.md`, adds an `**Explainer video:**` link to the paper note, and appends the paper to `Reading/Videos/_queue.jsonl` for the weekly compendium.

### 7. Deliver
Send the mp4 (and podcast mp3) to Idan with SendUserFile when it's available, and give the vault note path. Report the length and the ElevenLabs characters billed (narration + podcast is about 11K characters per paper).

## Weekly compendium

Triggered by launchd every Sunday 09:00 (`weekly.sh`), or on request.
1. Run `pe.py week` to get this week's papers from the queue. If there are none, stop.
2. Run `pe.py stitch <each week's mp4> --workdir ~/paper-videos/weekly-<YYYY-Www> --out "<vault>/Reading/Videos/Weekly/<YYYY-Www> - Paper Compendium.mp4"`.
3. Write `weekly-dialogue.json`: one episode, 12–20 min, covering every paper this week. Draw on the vault notes' "My Thoughts" and look for **connections across the papers**, which is the main value over the individual episodes. Render it with `pe.py podcast`.
4. Write `Reading/Videos/Weekly/<YYYY-Www> - Paper Compendium.md`: embed the stitched video and the episode, list each paper with links to its paper note and video note, and add a short "threads this week" section.
5. Notify Idan (Slack DM via slack-skill if running headless; otherwise SendUserFile).

## Voices
`narrator` = George (warm storyteller), `host` = Alice (clear educator), `guest` = Brian (deep, resonant). Any ElevenLabs voice id also works. Idan's own professional clone (`2OfNNDdqoRdl5K0o1XYw`) is available but **only use it if he asks**.

## Gotchas
- This ffmpeg build has no libass, so captions are soft (mov_text CC track) plus a sidecar `.srt`, not burned in.
- Segment ids must be `s01`…`sNN`; the scene classes must be `S01`…`SNN`.
- Titles containing `:` break the zergscholar PDF auto-match and the vault filename. Use ` - ` in the vault title and pass `--pdf` explicitly to push-paper.
- The final mp4 is roughly 3 MB per minute. The vault is in iCloud, so keep renders in `~/paper-videos/`.
