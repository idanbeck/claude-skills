export const meta = {
  name: 'paper-factcheck',
  description: 'Adversarially fact-check a paper note, video script and podcast dialogue against the source text + figures before narration (fail-closed: lost agents are reported in dropped[])',
  whenToUse: 'paper-explainer step 2.5: after writing the vault note, script.json and dialogue.json, before any TTS spend. A non-empty dropped[] means the gate did NOT pass.',
  phases: [
    { title: 'Check', detail: '3 artifacts x 2 lenses (numbers, framing)' },
    { title: 'Confirm', detail: 'independent refuter per reported issue' },
  ],
}
// args: {
//   sources: ["/abs/path/paper.txt", ...],                 // primary text ('=== PAGE n ===' markers help)
//   figures: ["/abs/path/pages/p-05.png (Fig 2)", ...],     // page images / figures (charts hold numbers the text omits)
//   quirks: "known source self-contradictions",
//   artifacts: [{ key: "note"|"script"|"dialogue", path: "/abs/path", kind: "description" }]
// }
// Returns {confirmed[], rejected[], dropped[], checked{}}. FAIL-CLOSED: a lost checker or refuter lands in dropped[]
// (never counted as "no issues"); re-run (resumeFromRunId) until dropped[] is empty before any TTS.
const A = args
const SRC = `SOURCE OF TRUTH (read these yourself, do not rely on memory):
- Text (per-page, '=== PAGE n ===' markers): ${A.sources.join(', ')}
- Page images holding figures/tables (open each PNG with the Read tool; charts hold numbers not in the text; values marked "traced" in the artifacts were read off these charts by eye, so judge them as approximate readings, not exact data): ${A.figures.join(', ')}
Known source quirks (the paper contradicts itself here; an artifact may cite either value if it says which): ${A.quirks}`

const LENSES = [
  { key: 'numbers', prompt: 'NUMBERS & FACTS lens. Extract EVERY quantitative or factual claim in the artifact: every number, percentage, model name, dataset size, count, ordering ("third", "leads every baseline"), and who evaluated what with which model. For each, find the supporting text or figure value in the source. Report only claims that are WRONG, UNSUPPORTED, or MIS-ATTRIBUTED (the number belongs to another model/setting/scale, rounding that changes meaning, a claim the source never makes, a hedge dropped). Check spelled-out numbers too.' },
  { key: 'framing', prompt: 'FRAMING & ATTRIBUTION lens. Look for: overclaiming relative to the source; conclusions the source does not support; the artifact\'s OWN critiques or skeptical takes that the source numbers do not actually support (this artifact is deliberately skeptical of a vendor report, so check every criticism is fair and factually grounded, e.g. "the report never says X" must really be absent from all 40 pages); misdescribed methodology (who judged what, with which model, which setting, which scale); caveats applied to one result but not to an equally exposed one. Opinions are fine if the facts under them are right.' },
]
const ISSUES = { type: 'object', properties: { issues: { type: 'array', items: { type: 'object', properties: {
  quote: { type: 'string', description: 'exact text from the artifact' }, problem: { type: 'string' },
  source_evidence: { type: 'string', description: 'what the source says, with page / figure / table' },
  fix: { type: 'string', description: 'replacement text' },
  severity: { type: 'string', enum: ['wrong', 'unsupported', 'misleading', 'minor'] } },
  required: ['quote', 'problem', 'source_evidence', 'fix', 'severity'] } }, checked_claims: { type: 'integer' } },
  required: ['issues', 'checked_claims'] }
const VERDICT = { type: 'object', properties: { real: { type: 'boolean' }, reason: { type: 'string' }, corrected_fix: { type: 'string' } }, required: ['real', 'reason', 'corrected_fix'] }

const jobs = []
for (const a of A.artifacts) for (const l of LENSES) jobs.push({ a, l })
const dropped = []
const checked = {}
const results = await pipeline(
  jobs,
  j => agent(`You are an adversarial fact-checker. Artifact: ${j.a.path}. ${j.a.kind}\n\n${SRC}\n\n${j.l.prompt}\n\nRead the artifact and the source yourself. Be exhaustive; missing a wrong number is a failure. No stylistic preferences. Do not list correct claims.`,
    { label: `check:${j.a.key}:${j.l.key}`, phase: 'Check', schema: ISSUES }),
  (r, j) => {
    if (!r) { dropped.push({ artifact: j.a.key, lens: j.l.key, stage: 'check' }); return [] }
    checked[`${j.a.key}:${j.l.key}`] = r.checked_claims
    return parallel(r.issues.map(iss => () =>
      agent(`A fact-checker claims this text in ${j.a.path} is ${iss.severity}:\nQUOTE: ${iss.quote}\nPROBLEM: ${iss.problem}\nCLAIMED EVIDENCE: ${iss.source_evidence}\nPROPOSED FIX: ${iss.fix}\n\n${SRC}\n\nVerify independently against the source (read it yourself). Try to REFUTE the fact-checker: maybe the artifact is right, or the fix is itself wrong. real=true only if the artifact text is genuinely wrong/unsupported/misleading. If real, give the best corrected replacement (in script/dialogue artifacts keep numbers spelled out in words for speech).`,
        { label: `confirm:${j.a.key}`, phase: 'Confirm', schema: VERDICT })
        .then(v => {
          if (!v) { dropped.push({ artifact: j.a.key, lens: j.l.key, stage: 'confirm', quote: iss.quote }); return null }
          return { artifact: j.a.key, lens: j.l.key, ...iss, verdict: v }
        })))
  },
)
const all = results.flat().filter(Boolean)
const confirmed = all.filter(x => x.verdict.real)
log(`${all.length} issues judged, ${confirmed.length} confirmed, ${dropped.length} agents lost`)
return {
  confirmed: confirmed.map(x => ({ artifact: x.artifact, lens: x.lens, severity: x.severity, quote: x.quote, problem: x.problem, source_evidence: x.source_evidence, checker_fix: x.fix, fix: x.verdict.corrected_fix, refuter_reason: x.verdict.reason })),
  rejected: all.filter(x => !x.verdict.real).map(x => ({ artifact: x.artifact, lens: x.lens, quote: x.quote, problem: x.problem, why: x.verdict.reason })),
  dropped, checked,
}
