---
name: use-case-refresh
description: Refresh Zerg AI's use cases and sales one-pagers. Research market updates per sector, audit every claim against internal evidence, update the use-case pages in the Obsidian vault, edit the LaTeX sheet sources, and rebuild and publish fresh one-pagers. Use when Idan asks to refresh or update the use cases, sectors, verticals, one-pagers or sales sheets, to pull fresh one-pagers "out of the oven", or to add a new use case or sheet.
---

# Use-case and one-pager refresh

Everything lives in the vault:

- **Home:** `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck/Epoch/Use Cases/`
  - `Use Cases.md` is the index: the use-case table, the process, global claim rules and the refresh log.
  - Each sector folder (`AI Silicon/`, `Security/`, `Agent Environments/`, `Hardware Operations/`, `Software Factory/`, `Company Overview/`, `Internal Field Guide/`) holds its use-case page `<Folder>.md` and the `.tex` source of its sheet(s).
  - `_shared/` holds `zergsheet.sty`, `zerglogo.tex` and `fonts/`. `_legacy/` and `_archive/` hold older material.
  - `build.sh` builds the sheets.
- **Shelf** (built PDFs that get sent): `Epoch/Sales/One-Pagers/`, with the index `One-Pagers.md`. Each published edition is copied to `Epoch/Sales/One-Pagers/archive/<YYYY-MM-DD>/`.

## Steps

1. **Read first.** Read `Use Cases.md`, every use-case page, and memory `reference_claims_to_stop_repeating.md`, `feedback_built_is_not_delivered.md` and `project_durable_case_study_clearance_gap.md`. Then read the vault `Epoch/Master Plans/Claims to stop repeating.md` and the latest daily notes. Note each page's last `### YYYY-MM-DD refresh` date; the research covers what changed since then.

2. **Research.** Run background agents in parallel, each writing a file to the scratchpad. Keep it to about five agents (weekly-limit lesson).
   - **One market agent per sector with a sheet.** Each reports: what changed (dated, sourced, tagged P/S), printable one-line facts with a "safe to print" flag, competitor moves, buyer-language shifts, suggested sheet edits (quote the exact `.tex` line and give the replacement), and new target accounts.
   - **One claim-audit agent, read-only.** It checks every Zerg claim on every sheet against the vault, the repos and memory, classifying each as supported / stale / unsupported / risky, and lists new proof points with a printability call. Tell it never to scan large run trees (`corsair/runs`, `/private/tmp`, `target/`).
   - Reuse research from the last few days instead of redoing it.
   - Verify surprising claims yourself with a quick search before you rely on them.

3. **Update the use-case pages.** For each page:
   - Add a `### YYYY-MM-DD refresh` block at the top of `## Market`, with sources.
   - Update the proof table (status, evidence, date checked), competitors and accounts.
   - Add a line to `## Refresh log`.
   - Save the full research files under `Epoch/Research/` and link them.

4. **Edit the sheets.** Edit the `.tex` in each folder.
   - Edit base files, not wrappers: `-finance` sets `\FinanceLead`, and `-proof-of-value` sets `\POVLead`.
   - Each sheet stays **one page**; the field guide is two. Prefer swapping lines to adding them.
   - Leave the `\newif` switches alone unless Idan says otherwise.
   - Bump the date in footers that print one.
   - Update the field guide's matching section.

5. **Build.**
   ```
   TMPDIR=<scratchpad> "<vault>/Epoch/Use Cases/build.sh" [sheet-name ...]
   ```
   - It compiles in a temp dir, using Tectonic if installed, otherwise XeLaTeX, and reports pages and overfull boxes per sheet.
   - Fix anything flagged `NOT ONE PAGE`.
   - Render the changed pages to PNG (PyMuPDF) and look at them before showing Idan.

6. **Review with Idan.** Give him a short change list per sheet (old line → new line, with why and the source) and the rendered PDFs. **Never publish external-facing sheets without his OK.**

7. **Publish.** Run `build.sh --publish [names]`. It copies the PDFs to the shelf, `archive/<date>/` and `~/Downloads/zerg-one-pagers-<date>/`. Then:
   - update `One-Pagers.md` (what each sheet says, and the edition date);
   - update the `Use Cases.md` refresh log;
   - log it in today's daily note `#log`.

## Claim rules (non-negotiable)

- **Never name d-Matrix** or its tools in any external sheet. Say "custom silicon" and "silicon model". Nothing derived from its SDK goes to another chip company.
- **Name no customer without written clearance.** Andesite and CesiumAstro are unnamed. Durable's quote is on, per Idan 10/4, but add no new naming.
- **AP is "in pilot". GovCloud is "staging".** Built is not delivered.
- **Every performance number carries its qualifiers.** Watch the KernelBench evaluator caveat and the bit-exact scope.
- **Synthetic data only.** Never customer data.
- **Say "Zerg AI"** (epoch.ai is a different company).
- With data vendors, **lead with help, not competition**.

## Adding a new use case

1. Create a folder `Epoch/Use Cases/<Name>/` with `<Name>.md`, following an existing page's sections.
2. Copy the closest `.tex` as the starting point.
3. Add the sheet to `SHEETS=(...)` in `build.sh`.
4. Add a row to `Use Cases.md` and to the shelf index.
