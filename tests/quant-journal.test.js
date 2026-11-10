import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, relative } from 'node:path'
import { QuantJournal } from '../src/quant-journal.js'

test('Quant records are session-bound, survive restart, and retain real failure state', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pies-quant-'))
  try {
    const journal = new QuantJournal(root), actor = { sessionId: '../../session-a' }
    let release
    const started = new Promise(resolve => { release = resolve })
    let finish
    const pending = journal.record(actor, 'batch-a', 'quant_sma', { values: [1, 2] }, async () => { release(); return new Promise(resolve => { finish = resolve }) })
    await started
    const running = await journal.snapshot(actor.sessionId)
    assert.equal(running.calls[0].status, 'running')
    assert.equal(relative(root, running.directory).startsWith('..'), false)
    assert.equal((await new QuantJournal(root).snapshot(actor.sessionId)).calls[0].status, 'interrupted')
    finish({ values: [null, 1.5] }); await pending
    await assert.rejects(journal.record(actor, 'batch-a', 'quant_market_fetch', {}, async () => { throw new Error('Fixture data provider unavailable') }))
    const persisted = await new QuantJournal(root).snapshot(actor.sessionId)
    assert.equal(persisted.calls.length, 2)
    assert.deepEqual(persisted.calls.find(c => c.tool === 'quant_sma').result, { values: [null, 1.5] })
    assert.equal(persisted.calls.find(c => c.tool === 'quant_market_fetch').status, 'failed')
    assert.deepEqual((await journal.snapshot('session-b')).calls, [])
  } finally { await rm(root, { recursive: true, force: true }) }
})
