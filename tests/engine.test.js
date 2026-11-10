import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { InsightEngine, reportFile, validateSettings } from '../src/engine.js'

test('configured workspace cannot be inside host source', async t => {
  const root = await mkdtemp(join(tmpdir(), 'insight-settings-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'engine')); await mkdir(join(root, 'workspace'))
  await assert.rejects(validateSettings({ engineRoot: join(root, 'engine'), workspace: join(root, 'workspace') }, root), { code: 'WORKSPACE_IN_CODE' })
})

test('report access rejects traversal, symlink escapes, and database files', async t => {
  const root = await mkdtemp(join(tmpdir(), 'insight-reports-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const workspace = join(root, 'workspace'), outside = join(root, 'outside')
  await mkdir(workspace); await mkdir(outside)
  await writeFile(join(outside, 'private.html'), 'private')
  await writeFile(join(workspace, 'report.html'), '<h1>Report</h1>')
  await writeFile(join(workspace, 'insight.db'), 'private')
  await symlink(outside, join(workspace, 'linked'), process.platform === 'win32' ? 'junction' : 'dir')
  await assert.rejects(reportFile(workspace, '../outside/private.html'), { code: 'OUTSIDE_WORKSPACE' })
  await assert.rejects(reportFile(workspace, 'linked/private.html'), { code: 'OUTSIDE_WORKSPACE' })
  await assert.rejects(reportFile(workspace, 'insight.db'), { code: 'UNSUPPORTED_FILE' })
  assert.equal((await reportFile(workspace, 'report.html')).type, 'text/html; charset=utf-8')
})

test('unknown operations never execute and engine failures retain their structured code', async () => {
  let calls = 0, disposed = 0
  const subprocess = { spawn(spec) {
    calls++
    assert.equal(spec.argv.includes('--no-sync'), true)
    return { done: Promise.resolve({ exitCode: 2 }), collected: { stdout: { readFrom: () => ({ text: JSON.stringify({ error: { code: 'WORKSPACE_NOT_INITIALIZED', detail: 'Run init first' } }), lossy: false }) } },
      terminate: () => { disposed++ }, waitForExit: async () => {} }
  } }
  const engine = new InsightEngine(subprocess, new AbortController().signal)
  const settings = { engineRoot: '/engine', workspace: '/data' }
  await assert.rejects(engine.execute(settings, 'shell'), { code: 'UNSUPPORTED_OPERATION' })
  assert.equal(calls, 0)
  await assert.rejects(engine.execute(settings, 'status'), { code: 'WORKSPACE_NOT_INITIALIZED' })
  assert.equal(disposed, 1)
})

test('truncated results are never presented as complete research data', async () => {
  const subprocess = { spawn: () => ({ done: Promise.resolve({ exitCode: 0 }),
    collected: { stdout: { readFrom: () => ({ text: '[]', lossy: true }) } }, terminate() {}, waitForExit: async () => {} }) }
  await assert.rejects(new InsightEngine(subprocess, new AbortController().signal).execute({ engineRoot: '/engine', workspace: '/data' }, 'status'), { code: 'OUTPUT_TOO_LARGE' })
})
