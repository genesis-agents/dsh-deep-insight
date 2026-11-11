import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile, access } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { Research } from '../src/research.js'
import { researchChannels, researchPolicy } from '../src/research-policy.js'

test('project execution rejects silently omitted social channels and accepts justified exclusions', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'insight-channels-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  const research = new Research({ dir: workspace, cwd: workspace }, {})
  research.settings = async () => ({ workspace })
  const commands = []
  research.invoke = async (_settings, args) => { commands.push(args[0]); return { saved: true } }
  const actor = { sessionId: 'channels', preset: 'workspace-write', cwd: workspace }
  const signal = new AbortController().signal
  const data = { quality_standard: {}, collection_requirements: [{ channel: 'local', disposition: 'required', rationale: 'Review supplied document' }] }
  await assert.rejects(research.call(actor, { action: 'project', data }, signal), error => error.code === 'CHANNEL_PLAN_REQUIRED' && error.message.includes('youtube, x'))
  assert.deepEqual(commands, [])
  data.collection_requirements = researchChannels.map(channel => ({ channel, disposition: channel === 'local' ? 'required' : 'excluded', rationale: 'User requested only a review of the supplied document' }))
  await assert.rejects(research.call(actor, {action:'project',data}, signal), {code:'RESEARCH_DESIGN_REQUIRED'})
  data.research_design = []
  assert.deepEqual(await research.call(actor, { action: 'project', data }, signal), { saved: true })
  assert.deepEqual(commands, ['init', 'project'])
  t.assert.snapshot(researchPolicy.channelPlanning)
})

test('MCP collection diagnostics reach native collectors and validate identifiers and write permissions', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'insight-existing-catalog-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  await writeFile(join(workspace, 'workspace.toml'), '')
  const research = new Research({ dir: '/fixture', cwd: '/fixture' }, {})
  research.settings = async () => ({ workspace })
  const commands = []
  research.invoke = async (_settings, args) => { commands.push(args); return { available: true } }
  const signal = new AbortController().signal, actor = { sessionId: 'channels', preset: 'read-only' }
  research.record = async () => {}
  await research.call(actor, { action: 'collectors' }, signal)
  await research.call(actor, { action: 'collector-preflight', plan: 'plan' }, signal)
  await assert.rejects(research.call(actor, { action: 'collector-probe', runId: 'run', data: { source_id: 'video' } }, signal), { code: 'READ_ONLY' })
  actor.preset = 'workspace-write'
  await research.call(actor, { action: 'collector-probe', runId: 'run', data: { source_id: 'video' } }, signal)
  await assert.rejects(research.call(actor, { action: 'collector-probe', runId: 'run', data: { source_id: '../secret' } }, signal), { code: 'INVALID_ID' })
  assert.deepEqual(commands, [['collectors'], ['collector-preflight', '--plan', 'plan'], ['collector-probe', '--run', 'run', '--source', 'video']])
})

test('collector discovery before project creation uses disposable state even in read-only mode', async t => {
  const root = await mkdtemp(join(tmpdir(), 'insight-new-catalog-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const workspace = join(root, 'not-created')
  const research = new Research({ dir: root, cwd: root }, {})
  research.settings = async () => ({ workspace, engineRoot: '/engine' })
  const commands = []
  let temporary
  research.invoke = async (settings, args) => {
    temporary = settings.workspace
    assert.notEqual(temporary, workspace)
    commands.push(args[0])
    return { local: { capabilities: ['document_text'] } }
  }
  const actor = { sessionId: 'new-catalog', preset: 'read-only' }
  assert.deepEqual(await research.call(actor, { action: 'collectors' }, new AbortController().signal), { local: { capabilities: ['document_text'] } })
  assert.deepEqual(commands, ['init', 'collectors'])
  await assert.rejects(access(workspace), { code: 'ENOENT' })
  await assert.rejects(access(temporary), { code: 'ENOENT' })
  commands.length = 0
  research.invoke = async (settings, args) => { temporary = settings.workspace; commands.push(args[0]); throw new Error('init failed') }
  await assert.rejects(research.call(actor, { action: 'collectors' }, new AbortController().signal), /init failed/)
  assert.deepEqual(commands, ['init'])
  await assert.rejects(access(temporary), { code: 'ENOENT' })
})
