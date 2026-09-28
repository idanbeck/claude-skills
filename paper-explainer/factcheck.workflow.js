export const meta = {
  name: 'paper-factcheck',
  description: 'Adversarially fact-check a paper note, video script, and podcast dialogue against the source text + figures before narration',
  whenToUse: 'paper-explainer step 2.5: after writing the vault note, script.json and dialogue.json, before any TTS spend',
  phases: [
    { title: 'Check', detail: 'each artifact x 2 lenses (numbers, framing), independent checkers' },
    { title: 'Confirm', detail: 'a second verifier tries to refute each reported issue against the source' },
  ],
}

// args: {
//   sources: ["/abs/path/page.txt or paper.pdf", ...],          // primary text
//   figures: ["/abs/path/fig1.png", ...],                        // optional: figures/tables (read as images)
//   quirks: "known source inconsistencies (optional)",
//   artifacts: [{ key: "note"|"script"|"dialogue", path: "/abs/path", kind: "description" }]
// }
const A = args || {}
if (!A.sources || !A.artifacts) throw new Error('args.sources and args.artifacts are required')

const SRC = `SOURCE OF TRUTH (read these yourself, do not rely on memory):
- Text: ${A.sources.join(', ')}
${A.figures && A.figures.length ? `- Figures/tables (open each PNG with the Read tool; they hold numbers not in the text): ${A.figures.join(', ')}` : ''}
${A.quirks ? `Known source quirk: ${A.quirks}` : ''}`

const LENSES = [
  { key: 'numbers', prompt: 'NUMBERS & FACTS lens. Extract EVERY quantitative or factual claim in the artifact: every number, percentage, model name, dataset size, count, ordering ("ahead of every X", "crosses zero at iteration 4"), and who evaluated what with which model. For each, find the supporting text or figure value in the source. Report only claims that are WRONG, UNSUPPORTED, or MIS-ATTRIBUTED (the number belongs to another model/setting/iteration, rounding that changes meaning, a claim the source never makes, a hedge dropped). Check spelled-out numbers too.' },
  { key: 'framing', prompt: 'FRAMING & ATTRIBUTION lens. Look for: overclaiming relative to the source (stating as established what the source hedges or only argues); conclusions the source does not support; the artifact\'s OWN critiques or skeptical takes that the numbers do not actually support; misdescribed methodology (who wrote what, which model was writer/judge/optimizer/trainer where, what was trained or evaluated on what); caveats the artifact applies to one result but not to an equally exposed one. Opinions are fine if the facts under them are right.' },
]

const ISSUES = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: {
      quote: { type: 'string', description: 'exact text from the artifact' },
      problem: { type: 'string' },
      source_evidence: { type: 'string', description: 'what the source actually says, with file/line or figure' },
      fix: { type: 'string', description: 'replacement text' },
      severity: { type: 'string', enum: ['wrong', 'unsupported', 'misleading', 'minor'] },
    }, required: ['quote', 'problem', 'source_evidence', 'fix', 'severity'] } },
    checked_claims: { type: 'integer' },
  },
  required: ['issues', 'checked_claims'],
}
const VERDICT = {
  type: 'object',
  properties: {
    real: { type: 'boolean', description: 'true only if, after reading the source yourself, the artifact text really is wrong/unsupported/misleading' },
    reason: { type: 'string' },
    corrected_fix: { type: 'string' },
  },
  required: ['real', 'reason', 'corrected_fix'],
}

const jobs = []
for (const a of A.artifacts) for (const l of LENSES) jobs.push({ a, l })

const results = await pipeline(
  jobs,
  j => agent(`You are an adversarial fact-checker. Artifact: ${j.a.path}. ${j.a.kind || ''}\n\n${SRC}\n\n${j.l.prompt}\n\nRead the artifact and the source yourself. Be exhaustive; missing a wrong number is a failure. No stylistic preferences. Do not list correct claims.`,
    { label: `check:${j.a.key}:${j.l.key}`, phase: 'Check', schema: ISSUES }),
  (r, j) => r ? parallel(r.issues.map(iss => () =>
    agent(`A fact-checker claims this text in ${j.a.path} is ${iss.severity}:\nQUOTE: ${iss.quote}\nPROBLEM: ${iss.problem}\nCLAIMED EVIDENCE: ${iss.source_evidence}\nPROPOSED FIX: ${iss.fix}\n\n${SRC}\n\nVerify independently against the source (read it yourself). Try to REFUTE the fact-checker: maybe the artifact is right, or the fix is itself wrong. real=true only if the artifact text is genuinely wrong/unsupported/misleading. If real, give the best corrected replacement (keep numbers spelled out for speech in scripts/dialogues).`,
      { label: `confirm:${j.a.key}`, phase: 'Confirm', schema: VERDICT })
      .then(v => v ? ({ artifact: j.a.key, lens: j.l.key, ...iss, verdict: v }) : null))) : [],
)

const all = results.flat().filter(Boolean)
const confirmed = all.filter(x => x.verdict.real)
log(`${all.length} issues reported, ${confirmed.length} confirmed by independent re-check`)
return {
  confirmed: confirmed.map(x => ({ artifact: x.artifact, lens: x.lens, severity: x.severity, quote: x.quote, problem: x.problem, fix: x.verdict.corrected_fix })),
  rejected: all.filter(x => !x.verdict.real).map(x => ({ artifact: x.artifact, quote: x.quote, why: x.verdict.reason })),
}
