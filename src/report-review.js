/** Report-level review complements exact claim verification; neither guarantees factual truth. */
import { InsightError } from './engine.js'

export const reportCriteria = ['question_coverage', 'analytical_depth', 'synthesis', 'visual_integrity', 'limitations']
export const reportReviewStandard = 'professional-report@1'
export const sectionReviewInstructions = 'For failed or unclear findings you may cite any saved evidence in the supplied run, including evidence the author omitted from this chapter. For passed findings cite evidence already linked to the chapter. Return section_checks with exactly one entry for every narrative section: {"section_id":"exact ID","verdict":"passed|failed|unclear","analysis_excerpt":"exact nonempty quotation from a body paragraph in this section, or empty only when failing","evidence_ids":["IDs supporting the section"],"rationale":"specific editorial and evidentiary assessment","required_changes":["concrete revision"]}. Read the full report as a professional analysis, not a discussion draft. For every section assess whether named actors, dated developments and explicit operating or experimental conditions establish concrete findings; whether comparable alternatives are assessed on stated dimensions (or their non-comparability is explained); whether the reasoning from cited observations to the conclusion is explicit; and whether counterevidence, scope and decision implications are addressed where relevant. Generic advice, slogans, first-person assertions, paraphrased chapter answers and lists of source titles do not establish analytical depth. Do not demand invented numbers or mechanically require every dimension in every section. A passing section needs an exact body excerpt and relevant evidence IDs; explain what the excerpt establishes and where the cited evidence supports or limits it. Failed or unclear sections require concrete changes and must also fail or make unclear the corresponding report_checks criterion. Useful relationships must be explained in the body; redundant relationship diagrams must be removed. Check exact evidence citations beside the statements they support. Never reward a report for adding repetitive text, figures or headings.'
export const reportReviewInstructions = 'Also return report_checks, exactly one object per criterion: {"criterion":"question_coverage|analytical_depth|synthesis|visual_integrity|limitations","verdict":"passed|failed|unclear","rationale":"Specific explanation in the report language","required_changes":["Concrete revision"]}. Evaluate question_coverage against every requested question and scope; analytical_depth against explained evidence, comparisons, mechanisms and implications rather than restated claims; synthesis against a distinct executive answer and supported final conclusion and recommendations; visual_integrity against useful evidence-linked tables, sourced charts and original figures with honest units and comparability, never decorative or invented data; limitations against contradictions, temporal limits, source dependence and unresolved gaps. Do not require an illustration quota. Require useful relationships in developed prose, remove redundant relationship diagrams, and inspect relevant original figures or sourced charts beside their explanatory text. Exact original evidence belongs in inline superscript links at the relevant sentence. Check whether each requested question receives concrete mechanisms, examples, alternatives and decision implications rather than only a brief answer. Do not award a pass for length, headings, paragraph counts or the mere presence of a chart. Cite the affected chapter or question in each rationale. Failed or unclear criteria require specific required_changes. Treat an absent narrative as failed, not as an exemption. Evaluate research_design and saved question assessments: do the observations distinguish the stated alternatives and meet the bounded stopping condition? Attribution proves what a source said, not its real-world truth. An internal check may establish an inconsistency within one original; independent-source quotas do not apply to that limited observation. Generalizations still need corroboration. Check whether paragraphs, table cells and captions introduce factual statements absent from the verified claims. When visual_scope.available is false and originals are required, mark visual_integrity unclear with the capability needed; never request another text-only retry as if it could inspect pixels. Separate research defects from editorial changes and request the smallest evidence acquisition that could change the conclusion.'

/** Validate a complete rubric response before recording any successful review receipt. */
export function validateReportReview(value) {
  if (!Array.isArray(value) || value.length !== reportCriteria.length
    || new Set(value.map(row => row?.criterion)).size !== reportCriteria.length
    || value.some(row => !row || !reportCriteria.includes(row.criterion)
      || !['passed', 'failed', 'unclear'].includes(row.verdict)
      || typeof row.rationale !== 'string' || !row.rationale.trim()
      || !Array.isArray(row.required_changes)
      || row.required_changes.some(change => typeof change !== 'string' || !change.trim())
      || (row.verdict === 'passed' && row.required_changes.length > 0)
      || (row.verdict !== 'passed' && !row.required_changes.length))) {
    throw new InsightError('REPORT_REVIEW_INVALID', '报告复核未完整覆盖研究问题、分析深度、综合结论、图文依据和限制，未登记为通过')
  }
  return value.map(({criterion,verdict,rationale,required_changes}) => ({criterion,verdict,rationale,required_changes}))
}

/** Bind each editorial verdict to the current chapter and its cited evidence before recording it. */
export function validateSectionReview(value, analysis, evidence = []) {
  const sections = analysis.narrative?.sections ?? []
  const invalid = () => { throw new InsightError('SECTION_REVIEW_INVALID', '逐章复核缺失、引文不属于当前正文或证据不属于该章节，未登记为通过') }
  if (!Array.isArray(value) || value.length !== sections.length || new Set(value.map(row => row?.section_id)).size !== sections.length) invalid()
  return value.map(row => {
    const section = sections.find(section => section.section_id === row?.section_id)
    if (!section || !['passed','failed','unclear'].includes(row.verdict)
      || typeof row.rationale !== 'string' || !row.rationale.trim()
      || typeof row.analysis_excerpt !== 'string' || !Array.isArray(row.evidence_ids)
      || !Array.isArray(row.required_changes) || row.required_changes.some(change => typeof change !== 'string' || !change.trim())
      || (row.verdict === 'passed' && row.required_changes.length > 0)
      || (row.verdict !== 'passed' && !row.required_changes.length)) invalid()
    const claimIds = new Set([...(section.claim_ids ?? []), ...section.blocks.flatMap(block => [...(block.claim_ids ?? []), ...(block.rows ?? []).flatMap(row => row.claim_ids ?? [])])])
    const evidenceIds = new Set(analysis.claims.filter(claim => claimIds.has(claim.claim_id)).flatMap(claim => claim.evidence_links.map(link => link.evidence_id)))
    const allowed = row.verdict === 'passed' ? evidenceIds : new Set([...evidenceIds, ...evidence.map(item => item.evidence_id)])
    if (row.evidence_ids.some(id => typeof id !== 'string' || !allowed.has(id))
      || (row.analysis_excerpt && !section.blocks.some(block => block.kind === 'paragraph' && block.text.includes(row.analysis_excerpt)))
      || (row.verdict === 'passed' && (!row.analysis_excerpt.trim() || !row.evidence_ids.length))) invalid()
    return { section_id: row.section_id, verdict: row.verdict, analysis_excerpt: row.analysis_excerpt, evidence_ids: row.evidence_ids, rationale: row.rationale, required_changes: row.required_changes }
  })
}
