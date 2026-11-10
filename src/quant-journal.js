/** Durable, session-bound Quant inputs and results shared by MCP and the conversation tab. */
import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

export class QuantJournal {
  constructor(profileDirectory) {
    this.packagePath = join(profileDirectory, 'node_modules', 'dsh-quant', 'package.json')
    this.root = join(profileDirectory, 'quant-results')
    this.active = new Set()
  }
  directory(sessionId) {
    if (typeof sessionId !== 'string' || !sessionId) throw new Error('Quant requires a conversation')
    return join(this.root, createHash('sha256').update(sessionId).digest('hex'))
  }
  async record(actor, batchId, name, args, execute) {
    const directory = this.directory(actor.sessionId)
    await mkdir(directory, { recursive: true })
    const id = randomUUID(), startedAt = new Date().toISOString()
    const path = join(directory, id + '.json')
    let engineVersion = 'unknown'
    try { engineVersion = JSON.parse(await readFile(this.packagePath, 'utf8')).version } catch (error) { if (error.code !== 'ENOENT') throw error }
    const entry = { engineVersion, schema: 1, id, batchId, sessionId: actor.sessionId, tool: name, startedAt, status: 'running', args }
    const save = async () => {
      await writeFile(path + '.tmp', JSON.stringify(entry), { mode: 0o600 })
      await rename(path + '.tmp', path)
    }
    this.active.add(id)
    try {
      await save()
      try {
        entry.result = await execute()
        entry.status = 'completed'
      } catch (error) {
        entry.status = error.name === 'AbortError' ? 'cancelled' : 'failed'
        entry.error = { code: error.code ?? 'QUANT_FAILED', message: error.message }
        throw error
      } finally { entry.finishedAt = new Date().toISOString(); await save() }
      return entry.result
    } finally { this.active.delete(id) }
  }
  async snapshot(sessionId) {
    const directory = this.directory(sessionId)
    let files
    try { files = await readdir(directory) } catch (error) { if (error.code === 'ENOENT') return { calls: [], directory }; throw error }
    const calls = await Promise.all(files.filter(file => /^[0-9a-f-]+\.json$/.test(file)).map(async file => {
      const entry = JSON.parse(await readFile(join(directory, file), 'utf8'))
      if (entry.status === 'running' && !this.active.has(entry.id)) return { ...entry, status: 'interrupted' }
      return entry
    }))
    return { directory, calls: calls.sort((a, b) => a.startedAt.localeCompare(b.startedAt) || a.id.localeCompare(b.id)) }
  }
}
