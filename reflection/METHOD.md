# Reflection Method

An evidence-grounded self-portrait built from the corpus an assistant can actually see.

## Attribution

This method is adapted from **Reflection Engine v1.3** by Kevin Rose —
<https://github.com/kropdx/reflection-engine>. The question set and the confidence-scored,
evidence-anchored structure are his design. This file is a re-implementation for a Claude Code
environment, where the corpus is local transcripts and an Obsidian vault rather than a hosted
chat history, and it adds corpus corrections specific to that setting. Credit for the underlying
idea belongs upstream; read the original if you want the canonical prompt.

## What this is

Twenty-two direct questions about the person running it. Every answer cites its evidence, scores
its own confidence, and ends with one concrete thing to try this week. It should be uncomfortable
in a useful way, never cruel, and never falsely certain.

## The template is not evidence

The person did not write these questions and did not choose them. The example options listed
inside a question ("novelty, control, optionality…") are the template author's generic menu, not
hints about this person. That someone ran this tool tells you only that they were curious.

Ground every claim in the corpus: their own words, their own choices, their own material.

## Corpus rules for this environment

**Primary evidence** — things the person actually wrote or did:

- User turns in Claude Code transcripts (`claude:` entries in the digest)
- Notes they authored in the vault (`vault:` entries — daily notes, personal notes, writing)
- Decisions they made, corrections they issued, things they rejected or insisted on

**Pointers, not proof** — assistant-authored material:

- Memory files. These are the assistant's own prior summaries. Use them to locate evidence,
  never to support a conclusion on their own. If a memory claims a pattern, go find the
  underlying turns before you believe it.
- Prior assistant analysis inside transcripts. Same rule.

**Four corrections this corpus specifically requires:**

1. **Work over-representation.** A coding-assistant corpus is dominated by technical work because
   that is what the tool is for, not because that is what the person's life is. Do not conclude
   "work consumes everything" from a work tool. Weight the vault's personal material and any
   personal threads in the transcripts far more heavily than their raw volume suggests.
2. **Deliberation over commitment.** People bring open questions to an assistant and then go
   decide elsewhere without reporting back. Absence of a recorded decision is weak evidence of
   avoidance. Before calling something unresolved, require positive evidence: the topic recurs
   with the same open framing after enough time to have acted, or they explicitly restate it as
   still open. Treat as counterevidence the shape where something is raised, goes quiet, and later
   gets referenced as settled. If the only evidence is recurrence with no visible resolution, cap
   confidence at 6.
3. **Template scaffolding is not behavior.** Vault notes follow templates. Empty or boilerplate
   sections reflect the template, not the person. Only populated, authored content counts.
4. **Requests are not confessions.** Asking about a topic, tool, diagnosis, or hypothetical is not
   evidence that it applies to them or that they acted on it.

## Analysis protocol

Build an evidence map before writing anything. Do not expose scratch work; do expose the evidence,
counterevidence, and uncertainty needed to judge each claim.

1. **Sample the whole timeline.** Early, middle, and recent. Do not let the most recent or most
   dramatic material dominate.
2. **Sample across domains.** Work, family, kids, health, money, home, creative projects,
   decision-making, aesthetics, ordinary logistics.
3. **Require independent recurrence.** A pattern repeated ten times inside one session is one
   episode. Weight patterns that recur across different months and different domains.
4. **Distinguish** a stable trait from a temporary state, a one-off event, a stated aspiration,
   an idea explored once, a behavior repeatedly enacted, and a transcription artifact.
5. **Seek counterevidence** for every major conclusion — moments they acted otherwise, held the
   opposing value, or changed course.
6. **Track corrections and resistance.** What they correct, refine, reject, or demand be made
   more precise reveals standards, needs, and sensitivities. This is unusually high-signal.
7. **Treat their accounts of other people** as evidence of their experience and framing, not as
   proof of anyone else's motives.
8. **Do not diagnose.** Describe observable dynamics. No clinical labels, for them or anyone else.
9. **Do not recycle one master theory** across multiple answers in different words.

## Required metadata

Directly under each question heading, before any prose, two plain Markdown lines exactly like this:

```
**Confidence:** 8/10 · **Evidence:** broad · **Status:** observed pattern + inference
**Basis:** Recurs across several months and domains, with limited counterevidence.
```

Not YAML, not a code block, and never a `---` rule directly beneath text (it renders the line
above as a giant heading).

**Evidence:** `broad` | `moderate` | `narrow`
**Status:** `observed pattern` | `observed pattern + inference` | `inference` | `tentative hypothesis` | `insufficient evidence`

Commit to the number before writing the answer. If drafting changes your view, change the number,
not the argument.

### Confidence rubric

- **9–10** — repeated, specific, consistent across multiple months and domains; little counterevidence
- **7–8** — a clear recurring pattern, several independent examples, some ambiguity or narrower coverage
- **4–6** — plausible, partially supported, but limited, mixed, or concentrated in one period
- **1–3** — mostly speculative or not answerable from this corpus

## How to write each answer

One to three substantive paragraphs, then the required advice paragraph. Lead with the conclusion.

Cover: the observation; the specific evidence; what it may mean; what it costs or enables; where
it is heading.

- Answers scored **7+** need at least two independent evidence anchors from different months or domains.
- Include real counterevidence or a plausible alternative when one exists.
- Prefer several small concrete anchors over one dramatic anecdote.
- Name real specifics: dates, recurring phrases, actual decisions, actual projects.
- Quote only when confident the quote is accurate; otherwise paraphrase.
- Say plainly when you are speculating, and say "insufficient evidence" rather than writing
  plausible filler.

### Required ending

Every answer ends with exactly one paragraph under:

```
### What you can do
```

Concrete enough to try this week. One or two high-leverage actions, not a list. If the pattern is
a strength, say how to protect and double down on it. Name the most likely way *this specific*
pattern gets resisted, intellectualized, or over-optimized — but only when that failure mode is
specific to this pattern, not as a repeated tic. Where possible give an observable sign it is working.

## Output

A single Markdown document. Begin with one YAML frontmatter block and use YAML nowhere else:

```yaml
---
title: Reflection Portrait
method: Reflection Engine v1.3 (adapted)
questions: 22
---
```

Open with `## Corpus Coverage Note` — earliest and latest material actually reviewed, domains
represented, gaps and access limits, and whether evidence concentrates in one period or kind of
conversation. Claim only what you actually read.

Then `## Recurring Threads` — five to eight patterns, one line each, each supportable from more
than one month or domain, naming where the evidence comes from. Write this before answering
question 1 and treat it as the evidence base. If your answer to question 1 is not on this list,
you have reached for a theory the evidence does not carry.

Questions 20, 21, and 22 are the synthesis and carry the most weight. Give them at least as much
care as question 1. If running out of room, say so and continue rather than compressing them.

# The 22 Questions

1. **The one blind spot that would change the most.** Not the most obvious flaw — the one with the
   greatest explanatory and practical leverage. How it shows up, why it is hard to see, what it
   protects against, what it costs, and one concrete way to test whether this reading is right.
2. **The truth they would most resist hearing.** Supported by repeated evidence. Explain how they
   would likely reject, reframe, or argue with it.
3. **What they are pretending not to know.** Something their behaviour suggests they already
   understand while continuing to circle it. Separate genuine uncertainty from avoidance.
4. **What they are making harder than it needs to be.** Name which part of the complexity is
   genuinely warranted before naming the part that is not.
5. **Their most expensive emotional habit.** Expensive in time, peace, energy, intimacy,
   opportunity, or self-respect. Trigger, short-term payoff, accumulating bill.
6. **Where motion is being mistaken for progress.** Show why this particular case crossed the line
   from legitimate exploration into substitution for deciding.
7. **What they keep trying to earn and may never feel they have enough of.** Ground it in
   recurrence, not in whichever option sounds most dramatic.
8. **What they use their intelligence to avoid.** Also say where those same abilities are genuinely
   load-bearing and adaptive.
9. **Which part of their personality is quietly running the show.** The motive, fear, need, or
   protective impulse driving more choices than they consciously credit. No clinical language.
10. **What they are addicted to that is not a substance.** Novelty, optionality, control,
    reassurance, intensity, starting things. Metaphor, not diagnosis — and say if it does not fit.
11. **The contradiction that explains the most.** One central tension across several domains. How
    both sides are real and what each is trying to preserve.
12. **What people probably misunderstand about them.** The impression created, why it forms, what
    is underneath, and whether their own behaviour feeds the misreading.
13. **Who is genuinely a good match for them.** Distinguish what they say they want, what their
    behaviour suggests they need, what feels exciting initially, and what stays healthy. Include
    what *they* would need to contribute or tolerate. If the corpus holds little evidence about how
    specific people actually affect them, say so in the first line and set Evidence: narrow.
14. **What kind of person brings out their worst.** Traits and dynamics, not individuals. What gets
    activated, how they respond, whether the response worsens it.
15. **What kind of person brings out their best.** What those people do differently, and what
    becomes possible in them.
16. **What they will regret in five years on the current trajectory.** What is already compounding
    and why it gets harder to reverse.
17. **What future them will be grateful for.** Something already compounding that they may
    undervalue. How to protect it from neglect or over-optimization.
18. **What they should stop apologizing for.** Plus the responsibility that comes with owning it,
    so it does not become licence to ignore their impact.
19. **What they should be more embarrassed about than they are.** Constructive, not humiliating,
    and only if the evidence genuinely supports it.
20. **The biggest bet they appear to be making with their life.** Infer it from repeated choices,
    not from stated intentions. What must be true for it to pay, and what is at risk if it does not.
21. **What they are trying to solve that may instead need to be accepted, grieved, or chosen
    through.** Do not force this. If supported, say what acceptance would look like behaviourally,
    not poetically.
22. **What it all adds up to.** Three to six sentences: the central tension, the central strength
    available to meet it, the direction of travel, and the choice most likely to determine whether
    that becomes growth or repetition. Then one closing `### What you can do` paragraph selecting
    the single action from above that would make most of the others unnecessary. Introduce nothing new.

## Final check

- Did I sample the whole timeline, not just recent material?
- Did I correct for a work-heavy corpus rather than concluding from its shape?
- Did I use their words and choices as primary evidence, and treat memory files as pointers only?
- Did I test the major conclusions against counterexamples?
- Did I avoid treating curiosity as conduct?
- Did I distinguish genuinely unresolved from resolved-off-channel?
- Is confidence calibrated to breadth and quality, not to how good the sentence sounds?
- Did I avoid both flattery and performative harshness?
- Is every answer specific enough that it could only be about this person?
- Does every answer end with a concrete `### What you can do`?
