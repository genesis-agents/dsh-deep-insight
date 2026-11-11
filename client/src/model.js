/** Read-only view models; readiness always comes from engine assessment, never UI guesses. */
export const assetUrl = (sessionId, path) => '/deep-insight/reports/session/' + encodeURIComponent(sessionId) + '/' + path.split('/').map(encodeURIComponent).join('/')
export const webLink = value => /^https?:\/\//i.test(value ?? '') ? value : null
export const sourceTitle = source => source?.title || (source?.canonical_identity && !webLink(source.canonical_identity) && !/^(user-file|inbox|sha256):/.test(source.canonical_identity) ? source.canonical_identity : source?.publisher) || source?.resource_uri || '—'
export const dateText = value => value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0,10) : null
export function references(detail) {
  return (detail?.input_snapshot?.sources ?? []).map((source, index) => {
    const versions = (detail.source_versions ?? []).filter(v => v.source_id === source.source_id)
    return { source, number:index+1, versions, evidence:(detail.evidence ?? []).filter(e => versions.some(v => v.version_id === e.source_version_id)) }
  })
}
/** Resolve only this question's distinct references; absent records remain visible. */
export function questionEvidence(ids, detail) {
  const refs = references(detail)
  return [...new Set(ids ?? [])].map(id => ({
    id,
    evidence: (detail.evidence ?? []).find(item => item.evidence_id === id),
    reference: refs.find(row => row.evidence.some(item => item.evidence_id === id)),
  }))
}
export function currentGates(detail) {
  if (!detail?.assessment) return []
  const byId = new Map((detail.run.gates ?? []).map(g => [g.gate_id,g]))
  for (const gate of detail.assessment) byId.set(gate.gate_id,gate)
  return [...byId.values()].filter(g => g.gate_id !== 'research_review')
}
export function readiness(detail) {
  const gates = currentGates(detail)
  if (!gates.length) return 'draft'
  if (gates.some(g => g.state !== 'passed')) return 'incomplete'
  return detail.verification_status === 'current' && detail.verification?.checks?.length && detail.verification.checks.every(c => c.verdict === 'supported') ? 'verified' : 'draft'
}
/** Stage checks are independent of whether an intermediate artifact exists. */
export function researchStages(detail) {
  const gates = new Map(currentGates(detail).map(g => [g.gate_id, g.state]))
  const stage = (key, recorded, checks, freshness = 'current') => {
    const states = checks.map(id => gates.get(id))
    const status = !recorded ? 'waiting'
      : freshness === 'stale' ? 'stale'
      : freshness !== 'current' ? 'recordedUnchecked'
      : states.some(state => state === 'failed') ? 'needsWork'
      : states.every(state => state === 'passed') ? 'passed'
      : 'recordedUnchecked'
    return { key, status }
  }
  return [
    stage('stageAcquire', detail.source_versions?.length, ['collection_coverage', 'source_coverage', 'temporal_coverage', 'search_record']),
    stage('stageEvidence', detail.evidence?.length, ['question_coverage', 'exact_citations']),
    stage('stageAnalysis', detail.analysis, ['report_composition', 'independent_support', ...(detail.input_snapshot?.project?.research_design ? ['question_analysis'] : [])]),
    stage('stageReview', detail.verification?.checks?.length || detail.verification_status === 'stale', ['semantic_verification', 'isolated_review', 'report_review'], detail.verification_status ?? 'missing'),
  ]
}
/** Only the current isolated execution may supply report-level verdicts. */
export function reportRubric(detail) {
  const receipt = detail.verification_status === 'current' && (detail.events ?? []).findLast(event =>
    event.kind === 'review_completed' && event.payload?.analysis_fingerprint === detail.analysis_fingerprint
    && event.payload?.report_review_standard === 'professional-report@1'
    && event.payload?.execution_ref === detail.verification?.execution_ref)
  return ['question_coverage','analytical_depth','synthesis','visual_integrity','limitations'].map(criterion => ({
    criterion, ...(receipt?.payload?.report_checks?.find(row => row.criterion === criterion) ?? {verdict:'not_performed',required_changes:[]}),
  }))
}
export function sectionEvidence(section, detail) {
  const ids = new Set([...(section.claim_ids ?? []), ...(section.blocks ?? []).flatMap(b => b.claim_ids ?? b.rows?.flatMap(r => r.claim_ids) ?? [])])
  const linked = new Set((detail.analysis?.claims ?? []).filter(c => ids.has(c.claim_id)).flatMap(c => c.evidence_links.map(e => e.evidence_id)))
  return (detail.evidence ?? []).filter(e => linked.has(e.evidence_id))
}
