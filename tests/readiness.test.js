import { test } from 'node:test'
import assert from 'node:assert/strict'
import { researchStages, reportRubric, questionEvidence } from '../client/src/model.js'

test('question references deduplicate IDs without inventing links or concealing missing records', () => {
  const detail={input_snapshot:{sources:[{source_id:'s',title:'Original source'}]},source_versions:[{version_id:'v',source_id:'s'}],evidence:[{evidence_id:'e',source_version_id:'v',quote:'Original quote'}]}
  const rows=questionEvidence(['e','e','missing'],detail)
  assert.deepEqual(rows.map(row=>row.id),['e','missing'])
  assert.equal(rows[0].reference.source.title,'Original source')
  assert.equal(rows[1].evidence,undefined)
  assert.deepEqual(questionEvidence([],detail),[])
})

test('saved artifacts do not imply completed research stages', () => {
  const detail = { run: {}, source_versions: [{}], evidence: [{}], analysis: {}, verification: {checks: [{}]}, verification_status: 'current' }
  assert.deepEqual(researchStages(detail).map(s => s.status), Array(4).fill('recordedUnchecked'))
  detail.assessment = [{gate_id:'temporal_coverage',state:'failed'}, {gate_id:'report_composition',state:'failed'}]
  assert.deepEqual(researchStages(detail).map(s => s.status), ['needsWork','recordedUnchecked','needsWork','recordedUnchecked'])
  detail.verification_status = 'stale'
  assert.equal(researchStages(detail)[3].status, 'stale')
  detail.verification_status = 'missing'
  detail.verification.checks = []
  assert.equal(researchStages(detail)[3].status, 'waiting')
})

test('each stage requires all its checks and an artifact', () => {
  const detail = { run: {}, assessment: ['collection_coverage','source_coverage','temporal_coverage','search_record'].map(gate_id => ({gate_id,state:'passed'})) }
  assert.equal(researchStages(detail)[0].status, 'waiting')
  detail.source_versions = [{}]
  assert.equal(researchStages(detail)[0].status, 'passed')
  detail.assessment.pop()
  assert.equal(researchStages(detail)[0].status, 'recordedUnchecked')
})

test('report rubric ignores prior analyses and prior review executions', () => {
  const detail = {analysis_fingerprint:'now',verification_status:'current',verification:{execution_ref:'review'},events:[
    {kind:'review_completed',payload:{analysis_fingerprint:'old',execution_ref:'review',report_checks:[{criterion:'synthesis',verdict:'passed'}]}}
  ]}
  assert.ok(reportRubric(detail).every(row=>row.verdict==='not_performed'))
  detail.events[0].payload.analysis_fingerprint = 'now'
  assert.ok(reportRubric(detail).every(row=>row.verdict==='not_performed'))
  detail.events[0].payload.report_review_standard = 'professional-report@1'
  assert.equal(reportRubric(detail).find(row=>row.criterion==='synthesis').verdict,'passed')
  detail.verification.execution_ref = 'new'
  assert.ok(reportRubric(detail).every(row=>row.verdict==='not_performed'))
})
