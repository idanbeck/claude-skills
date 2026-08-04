---
name: reflection
description: Build a candid, evidence-grounded self-portrait from the user's own corpus — Claude Code transcripts plus their Obsidian vault. Answers 22 questions about blind spots, contradictions, expensive habits, and trajectory, each with cited evidence, a confidence score, and one concrete action. Use when the user asks for a reflection, a read on themselves, a self-portrait, "what am I missing", or invokes the reflection engine.
allowed-tools: Bash, Read, Write
---

# Reflection

Turns the corpus an assistant can actually see into a frank self-portrait: 22 questions, each with
cited evidence, a self-scored confidence number, and one concrete thing to try this week.

Adapted from [Reflection Engine v1.3](https://github.com/kropdx/reflection-engine) by Kevin Rose.
The method lives in `METHOD.md` — **read it in full before analysing anything.**

## ⚠️ The output is sensitive

It is a blunt read on someone, drawn from their most personal material.

- Write it somewhere **private** — the vault, or `~/Desktop`. Never into a shared or public repo.
- This skill's directory is gitignored for `out/` and `*-portrait.md` precisely so a portrait
  cannot be committed by accident.
- Do not paste it into team chat, an issue, a PR, or an artifact without the user explicitly
  asking for that.
- Do not run this on a third party. It is for the person who asked for it, about themselves.

## Run it

### 1. See what corpus exists

```bash
python3 ~/.claude/skills/reflection/reflection_corpus.py --inventory
```

Reports transcript months and volume, vault span, and memory-file count. If the corpus covers only
a few weeks or one domain, say so up front — a thin corpus produces a horoscope, and the honest
move is to lower confidence, not to write more confidently.

### 2. Build the digest

```bash
python3 ~/.claude/skills/reflection/reflection_corpus.py --out /tmp/reflection-corpus.md
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--sources claude,vault,memory` | Which sources to include (default: all three) |
| `--vault PATH` | Obsidian vault root (defaults to the local iCloud vault) |
| `--budget 600000` | Approx max characters; spread **evenly across months** so recent material cannot dominate |
| `--per-month 40` | Max items kept per month per source |
| `--min-chars 120` | Ignore fragments shorter than this |

The digest buckets material by month and labels every entry with its source, so the analysis can
sample across time and distinguish the person's own words from assistant summaries.

### 3. Read the digest and write the portrait

Read `/tmp/reflection-corpus.md`, follow `METHOD.md` exactly, and write the result to a private
path — e.g. `<vault>/Personal/Reflection Portrait YYYY-MM-DD.md`.

For a corpus of any real size, do the reading in parallel: assign agents to different months or
domains to build the evidence base, then answer the questions from the pooled evidence. The
questions are not independent — 20, 21 and 22 synthesise the rest, so answer them last and give
them the most care.

## What makes an answer good here

- **Two independent anchors** from different months or domains for anything scored 7+.
- **Their words, not memory files.** Memory is the assistant's own prior summary; use it to find
  evidence, never as proof. `METHOD.md` is strict about this and it matters — otherwise the model
  grades its own homework.
- **Correct for the corpus shape.** A coding-assistant transcript is work-heavy because that is
  what the tool is for. Concluding "work dominates their life" from it is a measurement artifact.
- **Absence of a decision is weak evidence.** People decide off-channel and never report back.
  Requires positive evidence before calling something avoidance; cap at 6 otherwise.
- **Say "insufficient evidence"** rather than writing fluent filler. A 3/10 honestly marked is
  worth more than an 8/10 invented.

## Files

| File | Role |
|---|---|
| `METHOD.md` | The full protocol, corpus rules, metadata format, and the 22 questions |
| `reflection_corpus.py` | Corpus harvester (stdlib only) — transcripts + vault + memory, bucketed by month |
