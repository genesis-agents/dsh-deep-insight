/** Revocable per-turn MCP endpoint, with permissions bound by the host, never tool arguments. */
import { createServer } from 'node:net'
import { randomBytes } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { unlink } from 'node:fs/promises'
import {researchTool} from './research-tool.js'

export async function openMcp(input, call, lifecycleSignal, extensions = []) {
  const token = randomBytes(32).toString('hex')
  const pipe = process.platform === 'win32' ? `\\\\.\\pipe\\pies-insight-${token}` : join(tmpdir(), `pies-insight-${token}.sock`)
  const sockets = new Set(), pending = new Set()
  const controller = new AbortController()
  const signal = AbortSignal.any([input.signal, lifecycleSignal, controller.signal])
  let closed = false
  const tools = [researchTool]
  const extensionCalls = new Map(extensions.map(tool => [tool.name, tool.call]))
  if (extensionCalls.size !== extensions.length || extensionCalls.has('deep_insight')) throw new Error('Duplicate MCP tool name')
  tools.push(...extensions.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })))
  async function handle(message) {
    if (message.method === 'initialize') return { protocolVersion: '2024-11-05', capabilities: { tools: {} }, serverInfo: { name: 'pies-deep-insight', version: '0.2.0' } }
    if (message.method === 'ping') return {}
    if (message.method === 'tools/list') return { tools }
    const execute = message.params?.name === 'deep_insight' ? call : extensionCalls.get(message.params?.name)
    if (message.method !== 'tools/call' || !execute) throw new Error('Unsupported MCP request')
    try {
      signal.throwIfAborted()
      const result = await execute(input, message.params.arguments, signal)
      return { content: [{ type: 'text', text: JSON.stringify(result) }] }
    } catch (error) { return { isError: true, content: [{ type: 'text', text: JSON.stringify({ error: error.code ?? 'RESEARCH_FAILED', message: error.message }) }] } }
  }
  const server = createServer(socket => {
    sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {})
    let authenticated = false, buffer = ''
    socket.setEncoding('utf8')
    socket.on('data', chunk => {
      buffer += chunk
      if (buffer.length > 1048576) { socket.destroy(); return }
      let newline
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1)
        let message
        try { message = JSON.parse(line) } catch { socket.destroy(); return }
        if (!authenticated) { if (message.token !== token) { socket.destroy(); return }; authenticated = true; continue }
        if (closed || message.id === undefined) continue
        const operation = handle(message).then(result => ({ jsonrpc: '2.0', id: message.id, result }),
          error => ({ jsonrpc: '2.0', id: message.id, error: { code: -32603, message: error.message } }))
          .then(response => { if (!socket.destroyed) socket.write(JSON.stringify(response) + '\n') })
        pending.add(operation); void operation.finally(() => pending.delete(operation))
      }
    })
  })
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(pipe, resolve) })
  let disposing
  const dispose = () => disposing ??= (async () => {
    closed = true; controller.abort(); signal.removeEventListener('abort', onAbort)
    for (const socket of sockets) socket.destroy()
    await new Promise(resolve => server.close(resolve))
    await Promise.allSettled([...pending])
    if (process.platform !== 'win32') await unlink(pipe).catch(error => { if (error.code !== 'ENOENT') throw error })
  })()
  const onAbort = () => { void dispose() }
  signal.addEventListener('abort', onAbort, { once: true })
  if (signal.aborted) { await dispose(); throw new Error('Research connection cancelled') }
  return { servers: [{ name: 'deep-insight', command: process.execPath, args: [fileURLToPath(new URL('./mcp-stdio.js', import.meta.url))],
    env: [{ name: 'PIES_INSIGHT_PIPE', value: pipe }, { name: 'PIES_INSIGHT_TOKEN', value: token }, { name: 'ELECTRON_RUN_AS_NODE', value: '1' }] }], dispose,
    instructions: 'For deep research, use the deep-insight MCP deep_insight tool. Begin with guide. It binds to this PIES conversation and its workspace automatically. Use real sources and exact evidence; do not claim human review. Call status to confirm actual progress. Tell the user the Deep insight TAB shows the same task. Do not launch another app, server, or ask for engine paths.'
      + (extensions.length ? ' DSH Quant is also connected: call the listed quant_* MCP tools directly for quantitative calculations, simulations and data discovery. Quant does NOT require Orca, a terminal CLI, or the deep_insight guide. Inputs, execution status and results are automatically saved to the current conversation Quant research TAB. Use quant_data_guide / quant_channel_guide for data access questions; use the matching quant_* calculation tool for supplied data. Simulation results are not live trades. Only combine Deep Insight with Quant when the user actually requests a research workflow.' : '') }
}
