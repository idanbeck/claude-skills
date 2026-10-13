---
name: kissinger
description: Run the Kissinger loop on material that goes out to customers, investors, partners or readers. Before showing anything, the agent asks itself "Is this the best you can do?", scores the draft against an explicit definition of "best" for that material, revises until the honest answer is yes, then has a fresh reader check it cold. Runs automatically whenever you produce a deck, a one-pager, a case study or an investor update. Use on request for emails, Slack messages, proposals, memos, short stories and anything else when Idan says "kissinger this", "/kissinger", "is this the best you can do", "make it the best version", or wants the best version before he sees it.
---

# Kissinger

Henry Kissinger handed Winston Lord's drafts back with one question: "Is this the best you can do?" Lord would say he'd try again. After the ninth draft he said yes, it was the best he could do. Kissinger said that in that case he would now read it. (Lord's own telling; he calls it slightly apocryphal.)

You play both parts. Idan should never be the first critic of a draft. He reads only the version you can defend as your best, plus a short list of what only he can fix.

## Files

| File | Role |
|---|---|
| `~/.claude/skills/kissinger/PROFILES.md` | What "best" means for each material type. Read the matching profile and the "Every profile" checks before drafting. |
| House rules (private) | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck/Epoch/Company Information/External Material House Rules.md`. Company rules for naming, confidentiality, claims, status words and style. Read it in full for company material. Also read the documents it makes gates: the writing style guide and the claims list. Read its brand and positioning links when the piece is visual or a deck. If the note doesn't exist, run on PROFILES.md alone and say so in the report. |

**This repo is public.** Never write customer names, partner names, figures or anything from the house rules into this skill's files.

## Settings

Read them from the arguments (`/kissinger critic=fresh rounds=9 readers="CFO, staff engineer"`) or from plain words ("full Kissinger" means `critic=fresh`; "get three readers on it" means a `readers` panel).

| Setting | Default | What it does |
|---|---|---|
| `critic` | `self` | `self`: you ask yourself the question every round. `fresh`: you still score every round, and a new subagent also plays Kissinger (see below). `none`: no subagents at all, not even the cold read. |
| `cold_reads` | `1` | How many cold reads you may run. With 2, a failed cold read can be retried after revising. |
| `readers` | one persona from the brief | A panel of personas. Each gets its own cold read, and every one must pass. |
| `rounds` | `5` | The round cap. Lord took nine. |

The defaults cost one subagent per run. Never raise a setting on your own, and state the settings used in the report.

Use `general-purpose` subagents for the critic and the cold reader, never a fork (a fork inherits your whole context). Run them in the foreground and wait for the result before you go on.

## Work folder

Keep everything in `<scratchpad>/kissinger/<slug>/`:

- `brief.md`: the brief and the rubric.
- `v1.md` … `vN.md`: one file per version, or the native source per version (`v2.tex`, `v2-slides.md`).
- `rounds.md`: the answer to the question, every round.
- `cold-read.md`: what each cold reader said, and your answer to each finding.

Never write drafts into `~/.claude/skills`. HR or legal drafts about a person end as a `.docx` in `~/Downloads`, never in Drive.

## The loop

### 1. Brief: decide what "best" means

Fill this in before drafting:

- **Material type.** It picks the profile in PROFILES.md.
- **Reader.** The person who has to act on the job, which isn't always the addressee. A DM to a CTO that gets forwarded to finance is read by finance. For a piece read aloud, the reader is the person reading it out, who reports how the listeners react.
- **Job.** One sentence: what the reader should do, believe or feel afterwards.
- **Channel and constraints.** Length, slide or page count, format, deadline.
- **Sources of truth.** The documents whose facts you may use. Facts from your memory or general background that aren't in these sources don't go in the piece. If they contradict a source, raise that as a `needs Idan` question.
- **Naming mode.** `outreach` or `legal` for company material; the house rules define both. `personal` for family and private pieces, where only the house rules' writing-style section applies.

Infer what you can from the conversation. Ask Idan (AskUserQuestion, two questions at most) only when the reader or the job can't be inferred.

The rubric is the profile's criteria, plus the gates, plus one to three criteria from this brief. Example: "The reader is a CFO, so one number they care about on the first page." Write the brief and the rubric to `brief.md`.

### 2. Draft v1

If Idan handed you a draft, that draft is v1. Don't polish it first. If he handed you rough notes, they are source material, not a draft: write v1 from them.

### 3. Ask "Is this the best you can do?"

Answer in writing, in `rounds.md`:

```
## Round N (vN)
Scores: Idea 3 ("quote"), Proof 2 ("quote"), Ask 4 ("quote") ...
Gates: house rules PASS · claims FAIL (2 unsupported: "...", "...") · format PASS
Gaps:
- [fixable] Slide 4 title is a label, not a claim.
- [needs Idan] No written clearance for the quote on slide 9.
- [trade-off] Adding the second proof point pushes it to two pages.
Answer: No.
Changes for v(N+1):
- ...
```

How to answer:

- **Score each criterion 1 to 5 and quote the draft as evidence.** Commit to the score before you write the fix. If writing the fix changes your mind, change the score, not the argument. If the piece can't be rendered in this run, mark the visual criterion "not scored". Don't call that a trade-off.
- **Gates are pass or fail.**
  - The house rules.
  - The claim check: every number, name and status has a source in the brief, and each claim is labeled supported, stale, unsupported or risky. Check every figure against the house rules' claims list.
  - Format: length, plus the "Every profile" checks in PROFILES.md.
- **Tag every gap.**
  - `fixable`: you can fix it now with what you have.
  - `needs Idan`: a missing fact, a clearance or a decision.
  - `trade-off`: fixing it hurts another criterion; say which.
- **Only material gaps count:** structure, argument, evidence, a cut, a gate, or something a reader would misread. A wording nit is not a gap. Fix it in passing, but it never makes the answer No on its own.
- **The answer is No** if any gate fails or any material gap is fixable. Revise into v(N+1).
- **The answer is Yes** only when all three of these hold:
  - every gate passes;
  - every criterion scores 4 or more, or its gap is tagged `needs Idan` or `trade-off` with the reason written down;
  - the draft is not v1. A first pass is never the best; that's the whole point of the story.

### 4. Revise

- A No must produce a real change: structure, argument, evidence or cuts. Swapping synonyms is not a revision.
- A round where only the wording would change means the loop has converged. Answer Yes, or name what is blocking.
- Never invent a fact to close a gap. Tag it `needs Idan`.
- Claims added in a revision get the claim check next round. New lines are the riskiest lines in the final.
- Compare v(N+1) with vN for this reader. If it isn't better, go back to vN and try a different fix.
- Length should usually go down across rounds. If the final is longer than v1, justify it in the changelog.
- For visual material (decks, one-pagers), from round 2 judge the rendered pages as PNGs, not the source. Look for overflow, cropping, tiny text and slides that say two things.

### `critic=fresh`: a new Kissinger every round

You still score each round as in step 3. In addition, spawn one subagent per round.

- **Give it:** the reader, the job, the constraints and the rubric, written out fresh for it; the house rules path; the current version, rendered if it's visual; and the `needs Idan` list so far, so it can rule on whether each item is truly blocked.
- **Don't give it:** your scores, your claim analysis, or a `brief.md` that contains them.

Ask it to:

- score every criterion with quoted evidence;
- check the gates;
- list gaps, tagged the same way;
- answer one question: is this the best they can do, yes or no, and why.

Answer each gap it raises: fixed in v(N+1), or tagged with a reason it can see next round. The loop ends when it says Yes and every gate passes, or at the cap.

### 5. "Now I'll read it": the cold read

Run the cold read when you reach Yes, **or when you hit the round cap**. A capped run needs an outside read the most.

Spawn a fresh subagent as the reader. Its prompt holds only:

- the persona: who they are, what they know, what they're busy with;
- the finished piece, rendered if it's visual.

Tell it to judge only the text in the prompt. It must not open files, and must ignore any background it may have about the sender, their company or their family, because subagents can load memory. **Don't give it the job, the rubric or the history.** A reader who knows the intent will find it.

Ask it for:

- the takeaway (or, for a story, the effect it had), in one sentence;
- where it would stop reading, skim or lose the listeners;
- what it doesn't believe, and why;
- what it would ask the sender;
- for visual material, what the eye lands on first.

Write its answers to `cold-read.md`, then answer **every** finding: fixed, or tagged with a reason.

- **It passes** when the takeaway matches the job and it raises no gate issue. You may apply fixes that only clarify, as long as they add no claims and change no structure, and list them in the report.
- **It fails** on a mismatch, a gate issue, or a finding that needs a material change. That's a No: go back to step 3 if rounds remain.
- **A version changed materially after its cold read needs another one.** If `cold_reads` is used up, say plainly in the report that the final hasn't had a cold read, and offer to run one.
- **With a `readers` panel,** each persona gets its own subagent, and every one has to pass.

### 6. Stop

Stop at Yes plus a passing cold read, or at the `rounds` cap.

- **At the cap,** deliver the latest version. If it was revised after the last scoring, label it "unscored".
- **If fixable gaps are left,** say so plainly. Don't call it the best.

One-pagers built through `use-case-refresh`: its claim audit counts as the claim gate here, so don't run a second one. The rounds cover the writing and the rendered page.

### 7. Deliver

Produce the final in its native format with the skill that owns that format:

- **Decks:** pptx, `google-slides-skill` or `gamma-skill`.
- **One-pagers:** the vault `build.sh` (see `use-case-refresh`).
- **Documents:** docs or docx.
- **Emails:** a `gmail-skill` draft.
- **Slack messages:** a paste-ready `final.md` in Slack's own markup: `*bold*`, `•` bullets, no headings.
- **Stories:** `final.md`, or a doc if Idan wants one.

Keep anything meant only for Idan in a separate "For Idan" block in `final.md`. That covers don't-say lists, checks before sending and questions the reader is likely to ask. Never put it in speaker notes, alt text, comments or anything else that travels with the piece.

**Never send, post or publish anything.** Idan reads it first.

Report in chat, short:

- The settings used and the number of rounds. Say whether it reached Yes or hit the cap.
- One line per round on what changed.
- The cold reader's takeaway, word for word. Or say plainly that no cold read ran, or that the final changed after it.
- The `needs Idan` items, written as questions he can answer quickly.
- Where the final and the work folder are.

## Gotchas

- **Endless No.** Models always find something to tweak. Only material gaps count, and a round that would change only wording means you've converged.
- **Early Yes.** Models also like to be done. v1 is never accepted, and every score needs a quote.
- **Self-scoring is generous.** In testing, the self-critic scored a contradiction 5 for three rounds; the cold read caught it at once. Don't skip the cold read to save a subagent.
- **Leaky cold reads.** If the reader's prompt mentions the job or the rubric, the cold read is worthless. Give it the persona and the piece only.
- **Polish without improvement.** If you can't name what got better for the reader, the round didn't help.
- **Accuracy fixes turning into hedging.** Cut the unsupported claim, then rewrite the headline to be as strong as what's left honestly supports. In testing, a deck's titles drifted from claims the reader cares about ("You'll learn where your silicon disagrees") to defensive ones ("…against two stated bars"). A blind judge preferred the earlier, less accurate draft. Fix the fact and keep the punch.
- **Mid-loop questions.** Don't ask Idan during the loop. Collect `needs Idan` items and ask at the end. The one exception is the brief, when the reader or the job is unknown.
