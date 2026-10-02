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
- `factcheck.workflow.js`: adversarial fact-check workflow, fail-closed (step 2.5)
- `pe.py`: CLI (`tts`, `render`, `podcast`, `publish`, `week`, `stitch`)
- `lib/narrated.py`: Manim base class `NarratedScene` + palette/helpers (`T`, `fit`, `pill`, `title_card`, `bar_chart`, `hbar_rows`)
- `tools/tts_prep.py`: written-form `script.json` + `lexicon.json` → spoken-form `tts_script.json` (step 2)
- `tools/audiocheck.py`: whisper transcription of the narration/podcast audio, diffing spoken numbers against the text (step 2.6)
- `tools/captions.py`: captions in written form, timed to pauses in the audio, remuxed into `final.mp4` (step 4)
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
- Write in **written form**, because captions are generated from this text: digits and names as they should appear on screen ("50.9 percent", "Qwen3-4B", "GRPO"). Avoid symbols the voice can't speak (`×`, `≈`, `→`, `/`, `%`): write "percent", "seven eighths".
- Put pronunciation rules in `<workdir>/lexicon.json` as `{"rules": [["Qwen3-4B", "Qwen three, four B"], ["0.4", "zero point four"]]}`. Shared defaults (GRPO, LLM, VAE, FP16, ...) live in `tools/tts_prep.py`. Spell out small decimals and anything ambiguous.
- Keep claims exact. Anything that is the paper's own claim stays attributed to the paper; skeptical notes from the vault analysis can go in the final segment, and the final segment should carry the caveats.

TTS (after the fact-check in 2.5):
```bash
python3 ~/.claude/skills/paper-explainer/tools/tts_prep.py . --say     # review the spoken text
python3 ~/.claude/skills/paper-explainer/pe.py tts tts_script.json --workdir .
```
It caches by text hash, so editing one segment re-bills only that segment. It writes `durations.json`.

### 2.5 Fact-check before spending on voice (required)
Write the podcast `dialogue.json` (step 5) now too, then run the adversarial fact-check workflow over the vault note, `script.json` and `dialogue.json`:
```
Workflow({scriptPath: "~/.claude/skills/paper-explainer/factcheck.workflow.js", args: {
  sources: ["<workdir>/page.txt or the PDF path"],
  figures: ["<workdir>/figs/fig1.png", ...],          // extract figures: tables and charts hold numbers the text omits
  quirks: "<any source self-contradictions you noticed>",
  artifacts: [{key:"note", path:"<vault note>"}, {key:"script", path:"<workdir>/script.json"}, {key:"dialogue", path:"<workdir>/dialogue.json"}]}})
```
Each artifact gets two lenses (numbers, framing), and every reported issue goes to an independent refuter. The workflow is **fail-closed**: a lost checker or refuter shows up in `dropped[]`, and a non-empty `dropped[]` means the gate has not passed (resume until it is empty). Apply **every confirmed fix** to all three artifacts, and read the refuters' *rejection* reasons too, because they sometimes falsify a claim in your own note. Save the result as `factcheck.json`. If you wrote new claims while applying fixes, run a small numbers-lens re-check on just those passages before TTS (on Invent a Dataset and PixelUMM the re-check caught a new claim of mine that was half wrong). Why this is required: on Unslopping AI (2026-09-28) it confirmed 49 of 62 reported issues. They included invented specifics, causes the source hedges stated as settled, misattributed methodology, and an error in *our own* skeptical critique. Never trust a WebFetch summary for numbers: pull the raw text and figures (`curl` the HTML, download the PNGs, read them).

### 2.6 Check the spoken numbers (required after any TTS)
```bash
python3 ~/.claude/skills/paper-explainer/tools/audiocheck.py . [--podcast]
```
ElevenLabs silently misreads about 3% of segments: comma numbers ("5,120" → "5,020") and letter+digit names ("V four" → "five four"). Whisper flags candidates, but about half are false (dropped phrases, "too" heard as "2"), so confirm each flag with Scribe (`python3 ~/.claude/skills/voice-mode/voice_mode.py stt audio/s03.mp3`). For a real misread, add a lexicon rule or spell it out ("vee four"), regenerate `tts_script.json`, and re-run `pe.py tts`. The cache re-voices only the changed segment.

For blog posts (no arXiv PDF), archive a PDF for the vault/scholar with `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-pdf-header-footer --print-to-pdf="<vault>/Reading/pdfs/<title>.pdf" <url>`.

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
- Palette: `BG FG MUTED BLUE TEAL YELLOW RED GREEN PURPLE`. **All text via `T(text, size, color)`, never raw `Text()`.** `T` lays text out at 48 pt or more and scales it down. Raw small Pango text gets broken letter spacing ("co ntext", "p er") even at 1080p, which Idan flagged on 2026-10-02. Use a minimum size of 16. Keep content in the safe area (x within ±6.6, y within ±3.45), and call `fit(group)` on anything wide. Don't leave a static stretch longer than about 8 s. `MathTex` works (MacTeX installed). Helpers: `pill`, `title_card`, `bar_chart(values, labels, colors, max_value, fmt)` (vertical), `hbar_rows([(name, value, color)], maxv)` (horizontal, common bar start; returns rows as `[name, bar, value]`).
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
Also build a mid-frame sheet (at 50% of each segment), because end frames miss elements that fade out. Check for overlaps, text running off the frame, labels inside shaded regions, misaligned baselines, and reference lines drawn at the wrong height. Fix, then re-render only what changed with `--only s02,s09`. Tip: write `scene.py` while the fact-check runs, and smoke-render it against estimated durations (`words / 2.6` into `smoke/durations.json`).

When it's clean, **delete `media/videos/scene/480p15` first**: `pe.py render` picks each scene's newest mp4 across all quality folders, so a stale draft can splice into the final. Then run the final pass with `--quality h` (1080p30, about 1 min of render per 6 min of video). Then align the captions:
```bash
python3 ~/.claude/skills/paper-explainer/tools/captions.py .     # written-form cues timed to audio pauses, remuxed into final.mp4
```

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

Triggered by launchd every Sunday 09:00 (`weekly.sh`), or on request ("compile this week's videos").
1. Run `pe.py week` to get this week's papers from the queue (one entry per title). If there are none, stop.
2. Build the shareable compendium:
   ```bash
   python3 ~/.claude/skills/paper-explainer/tools/compendium.py [--days 7]
   ```
   It renders an intro card listing the papers, re-encodes and concatenates the videos (1080p30), merges their captions with time offsets, and embeds chapter markers. It also copies the individual videos and writes `Links.md`, with chapter timestamps and the links from each paper note's `**Source:**` line. Output goes to `~/Downloads/Paper-Explainers-<YYYY-Www>/`, plus `Reading/Videos/Weekly/<YYYY-Www> - Paper Compendium.{mp4,srt}` for the vault. This is what Idan posts to X.
3. Write `weekly-dialogue.json`: one episode covering every paper this week. Draw on the vault notes' "My Thoughts" and look for **connections across the papers**, which is the main value over the individual episodes. Scale the length to the week: about 4 min per paper plus about 5 min of connections, capped at 20 min, and don't pad. **Fact-check it** with `factcheck.workflow.js` (artifact: the weekly dialogue; sources: each paper's `paper.txt` and vault note) before any TTS. Then render it with `pe.py podcast` and run `tools/audiocheck.py <workdir> --podcast`.
4. Write `Reading/Videos/Weekly/<YYYY-Www> - Paper Compendium.md`: embed the compendium video and the episode, list each paper with links to its paper note and video note, and add a short "threads this week" section.
5. Notify Idan with the Downloads folder path and `Links.md`: by Slack DM via slack-skill if running headless, otherwise in chat. Never print a skill's `config.json` or environment variables while doing this; a headless run once leaked Slack tokens into the log that way.

## Voices
`narrator` = George (warm storyteller), `host` = Alice (clear educator), `guest` = Brian (deep, resonant). Any ElevenLabs voice id also works. Idan's own professional clone (`2OfNNDdqoRdl5K0o1XYw`) is available but **only use it if he asks**.

## Gotchas
- This ffmpeg build has no libass, so captions are soft (mov_text CC track) plus a sidecar `.srt`, not burned in.
- In one `self.play`, never combine `FadeIn(group)` with `Indicate(submobject)`: Indicate restores the pre-fade state and the element vanishes. Play them sequentially.
- Never pass an empty string to `T("")` (empty Text breaks layout math).
- Segment ids must be `s01`…`sNN`; the scene classes must be `S01`…`SNN`.
- `MathTex(r"\mathbb 1")` renders as a broken glyph. Use `\mathbf{1}` for an indicator.
- When drawing a reference line on a `bar_chart`, measure from the bars' bottom (`bars[0].get_bottom()`), not the group's corner; the group includes the labels below the bars.
- zergscholar rejects PDFs over 20 MB (HTTP 413). Upload a `gs -dPDFSETTINGS=/ebook` copy with `--pdf` and keep the original in the vault.
- Titles containing `:` break the zergscholar PDF auto-match and the vault filename. Use ` - ` in the vault title and pass `--pdf` explicitly to push-paper.
- The final mp4 is roughly 3 MB per minute. The vault is in iCloud, so keep renders in `~/paper-videos/`.
