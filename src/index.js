/** Profile-scoped plugin API; no separate HTTP listener or desktop application. */
import { readFile, writeFile, rename, access } from 'node:fs/promises'
import { join } from 'node:path'
import { InsightEngine, InsightError, validateSettings, reportFile } from './engine.js'
import { Research } from './research.js'
import { openMcp } from './mcp.js'
import { quantTools } from './quant-tools.js'
import { QuantJournal } from './quant-journal.js'
import { researchExecution } from './research-execution.js'
import { ResearchTurn } from './research-turn.js'
import {Config,resolveCapabilityConfig} from './capability-config.js'
import {ResearchCapabilities} from './capabilities.js'
import {capabilityPorts,capabilityActor} from './capability-ports.js'
import {managedResearchTool} from './managed-tool.js'
export {Config}

export const name = 'deep-insight'
export const inject = ['webServer', 'profileContext', 'subprocess', 'tools', 'llm', 'web']

export function apply(ctx,config) {
  const lifetime = new AbortController()
  const engine = new InsightEngine(ctx.subprocess, lifetime.signal)
  const research = new Research(ctx.profileContext, engine, researchExecution(ctx))
  const enrichment=resolveCapabilityConfig(config)
  research.capabilities=new ResearchCapabilities(research,enrichment,capabilityPorts(ctx,enrichment,lifetime.signal))
  ctx.effect(()=>ctx.tools.register(managedResearchTool(ctx,research,lifetime.signal)),'deep-insight: standard research tool')
  const quant = new QuantJournal(ctx.profileContext.dir)
  const connections = new Set()
  ctx.effect(function* () {
    yield ctx.effect(() => async () => {
      lifetime.abort()
      await Promise.allSettled([...connections].map(connection => connection.dispose()))
      await Promise.allSettled([...research.running.values()].map(operation => operation.done))
      await Promise.allSettled([...research.snapshots.values()].map(snapshot => snapshot.promise))
      await Promise.allSettled([...research.previews.values()])
    }, 'deep-insight: drain research operations')
    yield ctx.provide('localAgentMcp', {
      async open(input) {
        if (lifetime.signal.aborted) throw new Error('Research plugin is stopping')
        const turn = new ResearchTurn(research, input, AbortSignal.any([input.signal, lifetime.signal]))
        const connection = await openMcp(input, (actor, args, signal) => turn.call(actor, args, signal), lifetime.signal, quantTools(ctx, quant))
        connections.add(connection)
        return { ...connection, completionRequirement: () => turn.completionRequirement(), dispose: async () => { try { await connection.dispose() } finally { connections.delete(connection) } } }
      },
    })
  })
  const configPath = join(ctx.profileContext.dir, 'deep-insight.json')
  let busy = false
  const settings = async () => {
    try { return JSON.parse(await readFile(configPath, 'utf8')) }
    catch (error) { if (error.code === 'ENOENT') return null; throw error }
  }
  const configured = async () => {
    const value = await settings()
    if (!value) throw new InsightError('NOT_CONFIGURED', '请先连接研究内核和工作区')
    return validateSettings(value, ctx.profileContext.cwd)
  }
  const send = (res, status, data) => {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
    res.end(JSON.stringify(data))
  }
  const route = (path, handler, kind = 'exact') => ctx.effect(() => ctx.webServer.register({ kind, path,
    handler: async (req, res) => {
      try { await handler(req, res) }
      catch (error) { send(res, error instanceof InsightError ? error.status : 500,
        { error: { code: error.code ?? 'INTERNAL_ERROR', message: error.message } }) }
    },
  }), `deep-insight: ${path}`)
  route('/deep-insight/api', async (req, res) => {
    const sessionId = new URL(req.url, 'http://localhost').searchParams.get('session')
    if (req.method === 'GET') {
      if (sessionId) { send(res, 200, await research.snapshot(sessionId, lifetime.signal)); return }
      const config = await settings()
      send(res, 200, { config, busy, host: { profile: ctx.profileContext.name }, capabilities: { quantTools: quantTools(ctx).map(tool => tool.name) },
        readingRoom: config ? await access(join(config.workspace, '00-开始阅读.html')).then(() => true, () => false) : false })
      return
    }
    if (req.method !== 'POST') { send(res, 405, { error: { message: 'Method not allowed' } }); return }
    // The authenticated Desktop forwarder strips Origin; a custom header requires
    // preflight from foreign browser pages and is retained by that forwarder.
    const origin=req.headers.origin
    let sameOrigin=false
    if(typeof origin==='string'){
      try{const parsed=new URL(origin);sameOrigin=['http:','https:'].includes(parsed.protocol)&&parsed.host===req.headers.host}catch{sameOrigin=false}
    }else sameOrigin=req.headers['x-deep-insight-client']==='1'&&req.headers['content-type']==='application/json'
    if (!sameOrigin||req.headers['sec-fetch-site']==='cross-site') {
      throw new InsightError('ORIGIN_REJECTED', '请从当前 PIES 页面执行操作', 403)
    }
    let ownsLock = false
    try {
      const chunks = []
      let size = 0
      for await (const chunk of req) {
        chunks.push(Buffer.from(chunk)); size += chunk.length
        if (size > 32768) throw new InsightError('REQUEST_TOO_LARGE', '请求过大', 413)
      }
      const body = Buffer.concat(chunks).toString('utf8')
      let input
      try { input = JSON.parse(body) } catch { throw new InsightError('INVALID_JSON', '请求格式无效') }
      if (!input || typeof input !== 'object' || Array.isArray(input)) throw new InsightError('INVALID_JSON', '请求格式无效')
      if (!sessionId) {
        if (busy) throw new InsightError('BUSY', '已有研究操作正在执行，请稍后重试', 409)
        busy = true
        ownsLock = true
      }
      if (sessionId) {
        if(input.action==='enrich'||input.action==='reading-room'){
          const actor=capabilityActor(ctx,sessionId)
          send(res,200,{result:await research.call(actor,input,lifetime.signal)})
          return
        }
        if (input.action === 'illustrations') { send(res, 200, await research.illustrations(sessionId, input.runId, lifetime.signal)); return }
        if (input.action !== 'cancel') throw new InsightError('UNSUPPORTED_OPERATION', '请在对话中启动或继续研究')
        send(res, 200, { result: await research.cancel(sessionId) })
      } else if (input.action === 'configure') {
        const value = await validateSettings(input.config, ctx.profileContext.cwd)
        await writeFile(`${configPath}.tmp`, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 })
        await rename(`${configPath}.tmp`, configPath)
        send(res, 200, { saved: true })
      } else {
        const config = await configured()
        const result = input.action === 'setup' ? await engine.setup(config)
          : await engine.execute(config, input.action, input.runId)
        send(res, 200, { result })
      }
    } finally { if (ownsLock) busy = false }
  })
  route('/deep-insight/activity', async (req, res) => {
    if (req.method !== 'GET') throw new InsightError('METHOD_NOT_ALLOWED', '只支持读取执行记录', 405)
    const url = new URL(req.url, 'http://localhost')
    if (url.searchParams.has('run')) {
      send(res, 200, await research.engineEvent(url.searchParams.get('session'), url.searchParams.get('run'), url.searchParams.get('sequence'), lifetime.signal))
      return
    }
    send(res, 200, await research.activityRecord(url.searchParams.get('session'), url.searchParams.get('id')))
  })
  route('/deep-insight/document', async (req, res) => {
    if (req.method !== 'GET') throw new InsightError('METHOD_NOT_ALLOWED', '只支持读取资料正文', 405)
    const url = new URL(req.url, 'http://localhost'), sessionId = url.searchParams.get('session')
    const runId = url.searchParams.get('run'), version = url.searchParams.get('version')
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(runId ?? '') || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(version ?? '')) throw new InsightError('INVALID_ID', '资料标识无效', 400)
    const settings = await research.settings(sessionId)
    send(res, 200, await research.invoke(settings, ['document', '--run', runId, '--version', version], lifetime.signal))
  })
  route('/deep-insight/page',async(req,res)=>{
    if(req.method!=='GET')throw new InsightError('METHOD_NOT_ALLOWED','只支持读取原页',405)
    const url=new URL(req.url,'http://localhost'),page=Number(url.searchParams.get('unit'))
    const image=await research.sourcePage(url.searchParams.get('session'),url.searchParams.get('run'),url.searchParams.get('version'),page,lifetime.signal)
    res.writeHead(200,{'content-type':'image/png','cache-control':'private, max-age=3600'})
    res.end(image)
  })
  route('/deep-insight/capability',async(req,res)=>{
    if(req.method!=='GET')throw new InsightError('METHOD_NOT_ALLOWED','只支持读取能力记录',405)
    const url=new URL(req.url,'http://localhost')
    send(res,200,await research.capabilities.record(url.searchParams.get('session'),url.searchParams.get('run'),url.searchParams.get('id')))
  })
  route('/deep-insight/knowledge',async(req,res)=>{
    if(req.method!=='GET')throw new InsightError('METHOD_NOT_ALLOWED','只支持导出知识资产',405)
    const url=new URL(req.url,'http://localhost')
    const value=await research.capabilities.exportKnowledge(url.searchParams.get('session'),url.searchParams.get('run'),url.searchParams.get('id'))
    res.writeHead(200,{'content-type':'application/json; charset=utf-8','content-disposition':'attachment; filename="research-knowledge.json"','cache-control':'no-store'})
    res.end(JSON.stringify(value,null,2))
  })
  route('/deep-insight/interpretation',async(req,res)=>{
    if(req.method!=='GET')throw new InsightError('METHOD_NOT_ALLOWED','只支持读取译读记录',405)
    const url=new URL(req.url,'http://localhost'),sessionId=url.searchParams.get('session'),runId=url.searchParams.get('run')
    const data={version:url.searchParams.get('version'),...url.searchParams.has('unit')?{unit:Number(url.searchParams.get('unit'))}:{evidence_ids:url.searchParams.getAll('evidence')}}
    const detail=await research.capabilities.detail(sessionId,runId,lifetime.signal)
    const record=await research.capabilities.interpretation(sessionId,detail,data)
    send(res,200,{record:record?{id:record.id,result:record.result}:null})
  })
  route('/deep-insight/quant', async (req, res) => {
    if (req.method !== 'GET') { send(res, 405, { error: { message: 'Method not allowed' } }); return }
    const sessionId = new URL(req.url, 'http://localhost').searchParams.get('session')
    if (!sessionId) throw new InsightError('SESSION_REQUIRED', '请选择一个对话', 400)
    send(res, 200, await quant.snapshot(sessionId))
  })
  route('/deep-insight/reports', async (req, res) => {
    if (req.method !== 'GET') throw new InsightError('METHOD_NOT_ALLOWED', '只支持读取报告', 405)
    const url = new URL(req.url, 'http://localhost')
    const parts = url.pathname.slice('/deep-insight/reports/'.length).split('/')
    const sessionId = parts[0] === 'session' ? decodeURIComponent(parts[1] ?? '') : url.searchParams.get('session')
    const config = sessionId ? await research.settings(sessionId) : await configured()
    const path = decodeURIComponent((parts[0] === 'session' ? parts.slice(2) : parts).join('/'))
    const file = await reportFile(config.workspace, path)
    res.writeHead(200, { 'content-type': file.type, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff',
      'content-security-policy': "sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'" })
    res.end(file.content)
  }, 'prefix')
}
