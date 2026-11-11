/** Select the next research operation from saved facts; counts never certify an answer.
 * @param detail - Current run, frozen project and saved research records.
 * @param quality - Fresh engine evaluation, including next_actions.
 * @returns Question assessments, blockers and the first operation to resolve.
 */
export function researchCheckpoint(detail, quality) {
  const project = detail.input_snapshot.project
  const coverage = detail.context?.coverage ?? detail.analysis?.coverage ?? []
  const questions = project.subquestions.map(subquestion => {
    const design = project.research_design?.find(item => item.subquestion === subquestion)
    const saved = coverage.find(item => item.subquestion === subquestion)
    return { subquestion, design: design ?? null, evidence_ids: saved?.evidence_ids ?? [],
      assessment: saved?.assessment ?? null, unresolved: saved?.unresolved ?? null }
  })
  const blockers = quality.next_actions
  const search = blockers.find(item => item.gate_id === 'search_record')
  const acquisition = blockers.find(item => ['source_coverage', 'collection_coverage'].includes(item.gate_id))
  const evidence = blockers.find(item => ['question_coverage', 'temporal_coverage', 'independent_support'].includes(item.gate_id))
  const analysis = blockers.find(item => ['question_analysis', 'report_composition'].includes(item.gate_id))
  const review = blockers.find(item => ['isolated_review', 'semantic_verification', 'report_review'].includes(item.gate_id))
  const reviewResult = [...(detail.events ?? [])].reverse().find(event => event.kind === 'review_completed' && event.payload.analysis_fingerprint === detail.analysis_fingerprint)
  const failedSearch = [...(detail.events ?? [])].reverse().find(event => ['search_completed', 'search_failed'].includes(event.kind))
  const next = search ? { action: failedSearch?.kind === 'search_failed' ? 'repair_search_service' : 'search', reason: search.detail }
    : acquisition ? { action: 'collector-probe', reason: acquisition.detail }
    : evidence ? { action: 'evidence', reason: evidence.detail }
    : analysis ? { action: 'context', reason: analysis.detail }
    : review ? { action: reviewResult ? 'analysis' : 'review', reason: review.detail }
    : blockers.length ? { action: 'quality', reason: blockers[0].detail }
    : { action: 'deliver', reason: 'Current checks pass. Export the reviewed analysis; machine checks do not imply human acceptance.' }
  return { run_id: detail.run.run_id, quality_state: quality.quality_state, questions, blockers, next,
    review_findings: reviewResult ? {report_checks:reviewResult.payload.report_checks, section_checks:reviewResult.payload.section_checks, checks:reviewResult.payload.checks} : null,
    search_failure: failedSearch?.kind === 'search_failed' ? failedSearch.payload : null,
    revision_rule: 'Keep scope and quality requirements fixed. Revise the source plan when evidence is missing; revise the project only when the research question or agreed scope changes.' }
}
