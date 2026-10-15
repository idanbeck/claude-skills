---
name: dieter
description: Run the Dieter loop on anything carrying more than it needs, including writing, decks, UI layouts, images, CAD and other design. Name the core first, along with whatever holds it up. Then keep taking things away, testing each cut, until nothing else can go without the core or its structure failing. A fresh reader then checks that the point survived and nothing load-bearing went missing. Use when Idan says "dieter this", "/dieter", "take things away", "strip it down", "cut the fluff", "less but better" or "make it minimal", or wants the essence of something without the decoration. For code, use /simplify instead.
---

# Dieter

Dieter Rams designed for Braun for three decades under one motto, *Weniger, aber besser*: less, but better. The last of his ten principles is that "good design is as little design as possible". The line usually quoted alongside it is Saint-Exupéry's: perfection is reached not when there is nothing left to add, but when there is nothing left to take away.

That doesn't mean cutting until nothing is left. Most things have a core, the one idea or the one function. Around it sit two kinds of material:

- **The frame** holds the core up: the evidence, the ask, the constraint, the structure.
- **Ornament** is everything else: decoration, repetition, warm-up, hedging and padding that dilute the core.

A glass building is mostly glass, but it still needs its steel frame or it falls over. Find the glass and the frame, and take away everything else.

Models pad by default. They restate, hedge, add a third example, close with a summary, put an icon next to a label. Dieter is the counterweight.

## Files

| File | Role |
|---|---|
| `~/.claude/skills/dieter/MEDIUMS.md` | For each medium (prose, decks, UI, images, CAD): what the core usually is, what is usually frame, what is usually ornament, and how to test a cut. Read the matching section before cutting. |
| House rules (private) | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck/Epoch/Company Information/External Material House Rules.md`. For company material, read its claims, status-words and naming sections. Some things there are frame: a number's qualifier, a status word, a required name. No cut removes them. |

**This repo is public.** Never write customer names, partner names, figures or anything from the house rules into this skill's files.

## Settings

Read them from the arguments (`/dieter critic=fresh keep="the joke, the logo"`) or from plain words ("full Dieter" means `critic=fresh`).

| Setting | Default | What it does |
|---|---|---|
| `critic` | `self` | `self`: you look for cuts yourself. `fresh`: every round, a new subagent sees only the current version and the core, and says what it would take away (see below). It has no attachment to anything in the piece. `none`: no subagents at all, not even the cold read. |
| `cold_reads` | `1` | How many cold reads you may run. |
| `keep` | none | Elements Idan wants kept whatever the loop finds ("keep the joke", "keep the logo"). They are locked: never cut, and reported as kept on request. |
| `rounds` | `8` | The round cap. The loop usually ends sooner, at the first round that finds nothing to take away. |

The defaults cost one subagent per run. Never raise a setting on your own, and state the settings used in the report.

Use `general-purpose` subagents, never a fork (a fork inherits your whole context). Run them in the foreground and wait for the result before you go on.

## Work folder

Keep everything in `<scratchpad>/dieter/<slug>/`:

- `core.md`: the core, the frame and the keep list.
- `v0.*`: the original, untouched. Then `v1` … `vN`, one per round, in the native format (`v2.md`, `v3.tex`, `v2.scad`).
- `cuts.md`: every element tested, whether it was cut or kept, and why.
- `cold-read.md`: what the cold reader said, and your answer to each finding.

Never write into `~/.claude/skills`. HR or legal material about a person ends as a `.docx` in `~/Downloads`, never in Drive.

## The loop

### 1. Name the core and the frame

Before touching anything, write `core.md`:

- **The core.** One sentence on what this thing is for.
  - For writing: the point the reader must leave with.
  - For a deck: the one idea it proves.
  - For a screen: the one task it's for.
  - For an image: the subject.
  - For a part: its function.
- **Who it's for.** The reader, user or maker, and what they already know. What is padding for an expert can be frame for a newcomer.
- **The frame.** What has to stay for the core to stand. MEDIUMS.md lists the usual frame for each medium. Add whatever law, contract or the house rules require.
- **The keep list**, from `keep`.

If you can't write the core in one sentence, that is the first finding: the piece is doing two jobs. Ask Idan which job it's for (AskUserQuestion, one question), unless the conversation already says. Otherwise infer the core from the conversation without asking.

The core is fixed for the whole run. Cuts serve the core; the core never shifts to fit the cuts.

### 2. Inventory

Break v0 into elements, top-down: sections, then paragraphs, then sentences, then phrases. For a deck, slides before slide elements. For an app, screens before components. For an assembly, parts before features. Tag each element:

- **core:** the core itself.
- **frame:** holds the core up. Write down what it holds up.
- **ornament:** decoration, repetition, restatement, warm-up, hedging, platitude, flourish, or a second example that adds nothing.
- **unsure:** test it.

Start with the biggest elements. Cutting a paragraph does more than tightening its sentences, and the wording of a paragraph that's going doesn't matter.

### 3. Take away, and test each cut

For each candidate, make the version without it, then read, render or rebuild the result. Ask three questions:

1. Does the core still come through, as clearly as before or more?
2. Does the reader or user lose anything they need?
3. Does anything else now fail: a reference to it, a transition, a load path, a layout?

If nothing is lost, cut it. If something is lost, keep it and write down what it holds up. Log both in `cuts.md`, one line each.

**Allowed moves:**

- **Delete.**
- **Merge** two elements that each do half a job into one that does the whole job.
- **Replace** something elaborate with something plain or standard that does the same job: a phrase with a word, a custom component with a standard one, a custom part with a stock part, three colors with one.
- **Reorder** when a better order lets a transition or a preview go.

**Not allowed:**

- **Adding.** No new content, claims, features or decoration. If a cut leaves a hole, the cut was wrong, so restore it.
- **Changing the core.**
- **Cutting frame on a hunch.** Frame comes out only when you can show it holds nothing up. For anything structural or safety-related, showing that takes a calculation, a simulation or a test. Without one, it's a `needs Idan` item.
- **Cutting toward a number.** Word count, slide count and part count get reported, never targeted.

### 4. Again

After each round, read the new version whole, as if seeing it for the first time. Cuts expose more cuts:

- a transition with nothing left to bridge;
- a heading over a single paragraph;
- a qualifier for a sentence that's gone;
- a container holding one thing;
- frame that no longer holds anything up.

Always run at least two rounds, because the first round's cuts expose new ones. After that, the loop ends at the first round that takes nothing away. That is the point where there's nothing left to take away. If you reach the `rounds` cap while still finding cuts, say so.

For visual material (decks, UIs, images, CAD), judge renders, not source. Render to PNG every round, and look for anything the cut broke.

### `critic=fresh`: fresh eyes every round

You still run the round yourself. In addition, every round, spawn one subagent.

- **Give it:** the core sentence, the frame list, the keep list, the current version (rendered if it's visual), and the ornament list from the matching MEDIUMS.md section.
- **Don't give it:** v0, `cuts.md` or your reasoning.

Ask it two things:

- What would it take away, element by element, and why does each one hold nothing up?
- Which elements here are frame that it would be afraid to lose?

Run the cut test on every cut it proposes, and log the result. The loop ends when neither you nor the critic finds anything to take away, or at the cap.

### 5. Cold read: does the building stand?

When the loop ends, spawn a fresh subagent as the reader. Its prompt holds only:

- the persona: who they are, what they know, what they're busy with;
- the final version, rendered if it's visual.

Tell it to judge only what is in the prompt. It must not open files, and must ignore any background it may have about the sender, their company or their family, because subagents can load memory. **Don't give it the core, v0 or the cut log.**

Ask it for:

- what this is for, in one sentence;
- anything it had to guess at, or that felt missing;
- anything that still feels extra;
- for visual material: what the eye lands on first, and anything it couldn't find or didn't know how to use.

Write its answers to `cold-read.md`, then answer **every** finding:

- **Something missing, or a takeaway that doesn't match the core:** a cut took frame. Restore the smallest piece of v0 that fixes it. Restore it; don't write something new.
- **Something still extra:** run the cut test on it. A small cut that passes can go in now. A structural one means another round, if rounds remain.
- **The read passes** when the takeaway matches the core and nothing load-bearing is reported missing.
- **A version that changed materially after its cold read needs another one.** If `cold_reads` is used up, say plainly in the report that the final hasn't had a cold read.

### 6. Deliver

Produce the final in its native format, with the skill that owns that format: `gmail-skill` drafts for email, the deck's own toolchain for decks, the project's build for UI and CAD. For Slack, write a paste-ready `final.md` in Slack's markup.

**Never send, post or publish anything.** Idan reads it first.

Report in chat, short:

- The core, in one sentence.
- The settings used, the number of rounds, and why it stopped: nothing left to take away, or the cap.
- Before and after, in the medium's units (words, slides, components, parts).
- What came out, grouped by kind. For example: "the warm-up, three restatements, the second example, the closing summary."
- What stayed that looks cuttable, and what it holds up. This is where Idan is most likely to disagree.
- The cold reader's takeaway, word for word.
- The `needs Idan` items, as quick questions. Examples: a section he may want back, a structural cut, splitting a piece that does two jobs.
- Where the final and `cuts.md` are. v0 is untouched, so any cut can be restored.

## With Kissinger

The two skills answer different questions. Kissinger asks "is this the best you can do?", and may add what's missing. Dieter asks "what can go?", and never adds.

When both run, Kissinger goes first and gets the substance right. Dieter then strips the result before Kissinger's cold read, so one cold read covers both. Kissinger's `dieter=on` setting does this. Dieter never removes anything Kissinger's gates require.

## Gotchas

- **Cutting the frame.** The glass falls over. The usual victims:
  - a number's qualifier;
  - the ask;
  - context this reader doesn't have;
  - a control's label;
  - a fillet that relieves stress.

  If you can't say what an element holds up, test it. Don't assume it's ornament.
- **Telegram prose.** Fewer words, not broken sentences. Dropping articles, verbs and connectives makes text harder to read, not cleaner. Every sentence that stays should read naturally aloud.
- **Keeping the abstract, cutting the specific.** That's backwards. The concrete example, number or name usually carries the core, and the general statement around it is usually the padding.
- **Minimalism as decoration.** Thin grey type, low contrast, hidden controls and unlabeled icons can be ornament themselves, because the user pays for them. Less, but better: a cut that makes the thing worse to use was never a cut.
- **Cutting warmth that is the job.** In a message where the relationship is the point, the kind line is frame.
- **Substitution creep.** Cutting a tagline and then writing a new one is adding. Restore the old one or leave the space.
- **Over-merging.** Two ideas jammed into one sentence or one component isn't simpler.
- **Stopping after one pass.** The first round always leaves things behind. Read the cut version whole and go again.
