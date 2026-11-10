import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ResearchTurn } from '../src/research-turn.js'

function fixture() {
  const controller = new AbortController(), actor = { sessionId: 'test', preset: 'workspace-write' }
  const calls = []
  let quality = { quality_state: 'draft', next_actions: [{ gate_id: 'report_review', state: 'failed', detail: 'Explain fault recovery.' }] }
  const research = { async call(_actor, input) {
    calls.push(input)
    if (input.action === 'quality') return quality
    if (input.action === 'run') return { run_id: input.plan }
    return {}
  } }
  const turn = new ResearchTurn(research, actor, controller.signal)
  return { turn, calls, controller, research, setQuality: value => { quality = value }, call: input => turn.call(actor, input, controller.signal) }
}

test('report failure prevents stopping without native workers; completion requires fresh quality and final delivery', async () => {
  const f = fixture()
  await f.call({ action: 'analysis', data: { run_id: 'one' } })
  assert.match(await f.turn.completionRequirement(), /Explain fault recovery/)
  await f.call({ action: 'deliver', runId: 'one', draft: true })
  assert.match(await f.turn.completionRequirement(), /Research is not complete/)
  f.setQuality({ quality_state: 'machine_verified', next_actions: [] })
  assert.match(await f.turn.completionRequirement(), /"delivery_required":true/)
  await f.call({ action: 'deliver', runId: 'one' })
  assert.equal(await f.turn.completionRequirement(), undefined)
  f.setQuality({ quality_state: 'draft', next_actions: [{ gate_id: 'report_review', state: 'failed' }] })
  assert.match(await f.turn.completionRequirement(), /report_review/)
  assert.equal(f.calls.filter(c => c.action === 'quality').length, 5)
})

test('read-only inspection does not reactivate research and revised plans replace old runs', async () => {
  const f = fixture()
  await f.call({ action: 'status', runId: 'old' })
  await f.call({ action: 'quality', runId: 'old' })
  assert.equal(await f.turn.completionRequirement(), undefined)
  await f.call({ action: 'run', plan: 'old' })
  await f.call({ action: 'plan' })
  assert.match(await f.turn.completionRequirement(), /Create a run/)
  await f.call({ action: 'run', plan: 'new' })
  assert.match(await f.turn.completionRequirement(), /"run_id":"new"/)
})

test('cancellation, invalid quality and failed mutations cannot become successful completion', async () => {
  const f = fixture()
  await f.call({ action: 'run', plan: 'one' })
  await f.call({ action: 'cancel', runId: 'one' })
  await assert.rejects(f.turn.completionRequirement(), { code: 'RESEARCH_CANCELLED' })
  await f.call({ action: 'resume', runId: 'one' })
  f.setQuality({})
  await assert.rejects(f.turn.completionRequirement(), { code: 'QUALITY_INVALID' })
  f.research.call = async () => { throw new Error('engine offline') }
  await assert.rejects(f.call({ action: 'analysis', data: { run_id: 'one' } }), /engine offline/)
  await assert.rejects(f.turn.completionRequirement(), /engine offline/)
  f.controller.abort()
  await assert.rejects(f.turn.completionRequirement(), { name: 'AbortError' })
})
