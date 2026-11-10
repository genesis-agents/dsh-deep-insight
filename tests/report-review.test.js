import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reportCriteria, validateReportReview, validateSectionReview, sectionReviewInstructions } from '../src/report-review.js'
import { researchPolicy } from '../src/research-policy.js'
import { editorialStandard } from '../src/editorial-standard.js'

test('research authors receive the professional editorial standard', t => {
  assert.equal(researchPolicy.editorialStandard, editorialStandard)
  t.assert.snapshot(editorialStandard)
})

test('chapter review must cite the current body and the chapter evidence, not generic approval', t => {
  const analysis={claims:[{claim_id:'c',evidence_links:[{evidence_id:'e'}]}],narrative:{sections:[{section_id:'mechanism',claim_ids:['c'],blocks:[{kind:'paragraph',text:'The measured result applies only to the stated setup.'}]}]}}
  const row={section_id:'mechanism',verdict:'passed',analysis_excerpt:'applies only to the stated setup',evidence_ids:['e'],rationale:'The chapter bounds the measurement to its setup.',required_changes:[]}
  assert.deepEqual(validateSectionReview([row],analysis),[row])
  for(const rows of [undefined,[],[row,row],[{...row,analysis_excerpt:'Invented passage'}],[{...row,evidence_ids:['unrelated']}],[{...row,analysis_excerpt:''}],[{...row,verdict:'failed'}]]){
    assert.throws(()=>validateSectionReview(rows,analysis),{code:'SECTION_REVIEW_INVALID'})
  }
  assert.equal(validateSectionReview([{...row,verdict:'failed',analysis_excerpt:'',evidence_ids:[],required_changes:['Compare the actual conditions.']}],analysis)[0].verdict,'failed')
  t.assert.snapshot(sectionReviewInstructions)
})

test('report rubric requires complete distinct criteria and actionable failed verdicts', () => {
  const rows = reportCriteria.map(criterion => ({criterion,verdict:'passed',rationale:'Specific chapter and evidence assessed',required_changes:[]}))
  assert.deepEqual(validateReportReview(rows),rows)
  for (const invalid of [undefined, [], rows.slice(1), [...rows.slice(1),rows[1]], [null,...rows.slice(1)]]) {
    assert.throws(() => validateReportReview(invalid), {code:'REPORT_REVIEW_INVALID'})
  }
  rows[0].verdict = 'unclear'
  assert.throws(() => validateReportReview(rows), {code:'REPORT_REVIEW_INVALID'})
  rows[0].required_changes = ['Answer the missing scope question with evidence']
  assert.equal(validateReportReview(rows)[0].verdict,'unclear')
})
