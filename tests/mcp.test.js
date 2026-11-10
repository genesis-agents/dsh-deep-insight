import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { once } from 'node:events'
import { openMcp } from '../src/mcp.js'

test('native stdio MCP exposes tools, preserves host session identity, and revokes its subprocess connection', async () => {
  const controller = new AbortController()
  const calls = []
  const connection = await openMcp({ sessionId: 'session-test', cwd: '/fixture', preset: 'read-only', model: 'fixture', signal: controller.signal }, async (actor, args) => {
    calls.push({ actor, args }); return { boundSession: actor.sessionId }
  }, controller.signal, [{ name: 'quant_sma', description: 'Bridge fixture', inputSchema: { type: 'object' }, call: async (_actor, _args, signal) => {
    assert.equal(signal.aborted, false)
    return { values: [null, 1.5, 2.5] }
  } }])
  const config = connection.servers[0]
  const child = spawn(config.command, config.args, { env: { ...process.env, ...Object.fromEntries(config.env.map(entry => [entry.name, entry.value])) }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true })
  const lines = createInterface({ input: child.stdout })
  let counter = 0
  const request = async (method, params) => {
    const response = once(lines, 'line')
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: ++counter, method, params }) + '\n')
    return JSON.parse((await response)[0]).result
  }
  try {
    assert.equal((await request('initialize', {})).serverInfo.name, 'pies-deep-insight')
    assert.equal((await request('tools/list')).tools[0].name, 'deep_insight')
    const actions = (await request('tools/list')).tools[0].inputSchema.properties.action.enum
    for (const action of ['collectors', 'collector-preflight', 'collector-probe']) assert.ok(actions.includes(action))
    assert.equal((await request('tools/list')).tools[1].name, 'quant_sma')
    assert.match(connection.instructions, /Quant does NOT require Orca/)
    const quant = await request('tools/call', { name: 'quant_sma', arguments: {} })
    assert.deepEqual(JSON.parse(quant.content[0].text).values, [null, 1.5, 2.5])
    const result = await request('tools/call', { name: 'deep_insight', arguments: { action: 'status', sessionId: 'forged' } })
    assert.equal(JSON.parse(result.content[0].text).boundSession, 'session-test')
    assert.equal(calls[0].actor.preset, 'read-only')
  } finally {
    const exit = once(child, 'exit')
    await connection.dispose()
    await exit
    lines.close()
  }
})
