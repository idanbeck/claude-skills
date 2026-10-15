# What to take away

Each section covers one medium:

- **Core:** what it usually is.
- **Frame:** keep it unless you can show it holds nothing up.
- **Ornament:** cut it first.
- **Check:** how to test a cut.
- **Usually fails by:** the common mistakes.

Company-specific frame (required names, status words, qualifiers) comes from the private house rules, never from here.

## Prose: email, Slack, post, memo, doc

**Core:** the point the reader leaves with, plus the ask if there is one.

**Frame:**
- The ask and its deadline.
- The facts that make the claim true.
- Every number's qualifier, source and date.
- Names, dates and amounts.
- The one example that makes it concrete.
- Context this reader doesn't already have.
- Tone, when the relationship is the job.
- Required legal or contractual wording.

**Ornament, cut first:**
- **Warm-up:** "I hope this finds you well", "I wanted to reach out", "As you know", "In today's…".
- **Meta:** "In this post I'll…", "To summarize", "It's worth noting", "Let me explain".
- **Restatement:** a closing summary, an intro that previews what follows, a sentence that repeats the one before it.
- **Stacked hedges:** "might possibly", "somewhat", "I think it may". Keep one hedge where the uncertainty is real.
- **Intensifiers and empty adjectives:** "very", "really", "truly", "incredibly", "robust", "seamless", "powerful".
- **Platitudes:** lines any company could write about anything.
- **Rhythm lists:** three items where one is the point.
- **Extra examples:** the second and third example, when the first one already lands.
- **Patch transitions:** ones that only exist because the order is wrong. Reorder instead.
- **Padding at the close:** "let me know if you have any questions", when the ask already says what to do.

**Check:** read it aloud, start to finish. Could the reader still act on it? Has any sentence lost what it refers to?

**Usually fails by:** telegraphic sentences. Cutting the qualifier. Cutting the one concrete example and keeping the generalization.

## Deck or presentation

**Core:** the one idea the deck proves. Each slide has one claim, which is its title.

**Frame:**
- The title claims, in order. That's the skim path.
- The proof for each claim.
- The ask.
- Each number's source.
- What the audience needs to know to follow.
- For a deck that's sent rather than presented: what a reader needs without the speaker there.

**Ornament, cut first:**
- **Whole slides:**
  - an agenda;
  - "about us" before it has been earned;
  - section dividers;
  - "thank you" and "questions?";
  - a recap;
  - two slides that make the same point.
- **On a slide:** a subtitle or bullets that restate the title, decorative icons and stock photos, the logo on every slide, footers.
- **Charts:**
  - gridlines;
  - a legend where direct labels work;
  - 3D, gradients and shadows;
  - a second chart that shows the same thing;
  - more than one highlight color.
- **Words the speaker will say anyway:** cut them from a deck that's presented. Keep them in a deck that's sent.

**Check:** render every slide to PNG each round. Skim test: the titles alone tell the story. Each slide reads in about ten seconds.

**Usually fails by:** cutting the proof and keeping the adjectives. Merging two claims onto one slide.

## UI layout: screen, page, app, dashboard

**Core:** the one task the screen is for, and its primary action.

**Frame:**
- The primary action, and how a user finds it.
- Labels on anything ambiguous.
- Feedback: loading, success, error.
- Empty states.
- Accessibility:
  - contrast;
  - focus states;
  - hit targets;
  - screen-reader labels.
- A way back out.
- Confirmation before anything destructive.

**Ornament, cut first:**
- **Containers:**
  - cards inside cards;
  - borders and dividers where spacing does the job;
  - background panels.
- **Duplicates:**
  - the same action in two places;
  - an icon beside a text label that says the same thing;
  - a heading that repeats the navigation.
- **Text:** helper text that restates the label, marketing copy inside a tool, instructions for obvious controls.
- **Visuals:**
  - more than one accent color;
  - gradients and shadows;
  - animation that doesn't signal a change of state;
  - decorative illustrations.
- **Options:** settings nobody changes, and secondary actions given primary weight.

**Check:** take a screenshot each round from the dev server, Playwright or a render. Do the task as a first-time user would: can you find the primary action in five seconds? Run a contrast check whenever colors change. Check the error and empty states too, not only the happy path.

**Usually fails by:** hiding controls for a cleaner look. Stripping labels from icons. Deleting error and empty states because they don't show up in the happy-path screenshot.

## Image, graphic, illustration

**Core:** the subject, and what the viewer should notice first.

**Frame:**
- The subject.
- Legibility of any text that has to be there.
- Required marks.
- Enough context to read the subject (scale, setting) when it matters.

**Ornament, cut first:**
- Competing focal points.
- Background clutter.
- Text overlays that repeat the caption.
- Frames, drop shadows, glows and gradients.
- Extra colors.
- Filler elements.

**Check:**
- Look at it as a thumbnail: does the subject still read first?
- For a generated image, regenerate from a shorter prompt with the cut elements removed, rather than painting over them.
- For an existing image, crop or remove. Where you can't edit, deliver a cut list.

**Usually fails by:** cropping away context the subject needs. Flattening contrast until nothing reads.

## CAD, hardware, physical design

**Core:** the part's or assembly's function, and its load path.

**Frame:**
- Strength and stiffness margins.
- Tolerances and fits.
- Manufacturability:
  - draft angles;
  - minimum wall thickness and radii;
  - tool access.
- Thermal paths.
- Safety features.
- Assembly and service access.
- Mounting interfaces.

A fillet at a stress concentration is frame. A fillet for looks is not.

**Ornament, cut first:**
- Decorative fillets and chamfers.
- Embossing and surface texture.
- Ribs and bosses that carry no load.
- Cosmetic covers.
- A custom part where a stock part works.
- Extra fasteners, or a second fastener size where one size works.
- Extra machining setups.

**Moves:**
- Consolidate parts.
- Standardize: one screw size, stock tube and plate, standard bearings.
- Cut features.
- Reduce setups.

Every structural or safety cut needs a calculation, a simulation or a test. Without one, it's `needs Idan`. Never cut a safety factor on judgment.

**Check:**
- **Model is code** (OpenSCAD, CadQuery, build123d): edit the source, rebuild and render views each round. It must still regenerate.
- **Report before and after:** part count, unique parts, fastener count, feature count and mass.
- **Native file you can't edit** (Fusion, SolidWorks, Onshape): deliver a cut list. For each feature, say what it does and whether it can go.

**Usually fails by:** cutting a fillet that was relieving stress. Consolidating parts that can then no longer be assembled or serviced. Designing out the tolerance a real-world fit needs.

## Code

Use `/simplify` for reuse, simplification and efficiency. Dieter's prose rules still apply to comments, docs and READMEs.

## Anything else

Write the core, the frame and the ornament list for this medium into `core.md` before cutting, so they can't shift to fit the cuts.
