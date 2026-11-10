/** Bind enrichment to the Host's model, scheduler, web policy and supervised subprocesses. */
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises'
import {join} from 'node:path'
import {tmpdir} from 'node:os'
import {fileURLToPath} from 'node:url'
import {InsightError} from './engine.js'

/** Resolve current permissions and model without accepting browser-supplied authority. */
export function capabilityActor(ctx,sessionId){
 const agent=ctx.get('agents')?.get(sessionId)
 if(!agent)throw new InsightError('AGENT_REQUIRED','请先在当前对话发送消息以连接 Agent')
 return researchActor(ctx,sessionId,agent)
}

/** Resolve the protected session identity, current model and permission preset from its agent. */
export function researchActor(ctx,sessionId,agent){
 const permissions=agent.ctx.get('permissionPresets'),selection=agent.model.current()
 if(!permissions||!selection)throw new InsightError('AGENT_STATE_UNAVAILABLE','当前会话的权限或模型尚未就绪，请重新连接 Agent')
 return {sessionId,cwd:ctx.get('workingDirectory').get(agent.session),preset:permissions.current(agent.session),provider:selection.provider,model:selection.model}
}

/** Expose only explicit effects; callers retain complete execution receipts. */
export function capabilityPorts(ctx,config,lifetime){
 const scheduler=()=>{const value=ctx.get('schedule');if(!value)throw new InsightError('SCHEDULE_UNAVAILABLE','当前宿主没有启用自动化调度，请启用后再创建订阅');return value}
 const edit=async(id,patch,actor,signal)=>{
  const service=scheduler(),current=await service.view({id})
  if(current.code==='schedule_not_found')throw new InsightError('SCHEDULE_NOT_FOUND','关联的订阅任务已不存在')
  const result=await service.edit({id,action:'update',patch,expectedUpdatedAt:current.updatedAt},actor.sessionId,signal)
  if(result.code)throw new InsightError('SCHEDULE_CONFLICT','订阅已发生变化，请刷新后重试')
  return service.view({id})
 }
 return {
  async embed(texts,signal){
   const directory=await mkdtemp(join(tmpdir(),'pies-embedding-'))
   let child
   try{
    const request=join(directory,'request.json'),output=join(directory,'result.json')
    await writeFile(request,JSON.stringify({texts,model:config.embeddingModel,dtype:config.embeddingDtype,batchSize:config.embeddingBatchSize,cacheDirectory:config.embeddingCache??join(ctx.profileContext.dir,'.models')}),{mode:0o600})
    child=ctx.subprocess.spawn({argv:[process.execPath,fileURLToPath(new URL('./embedding-worker.mjs',import.meta.url)),request,output],cwd:ctx.profileContext.cwd,env:{ELECTRON_RUN_AS_NODE:'1'},graceMs:2000,signal:AbortSignal.any([lifetime,signal,AbortSignal.timeout(config.embeddingTimeoutMs)]),stdio:{stdin:'ignore',stdout:{maxBytes:4096},stderr:{maxBytes:32768}}})
    const outcome=await child.done
    signal.throwIfAborted();lifetime.throwIfAborted()
    if(outcome.exitCode!==0)throw new InsightError('EMBEDDING_FAILED','本地嵌入模型执行失败，请检查模型下载、缓存和 CPU 运行库：'+child.collected.stderr.readFrom(0).text)
    return JSON.parse(await readFile(output,'utf8'))
   }finally{
    if(child){child.terminate();await child.waitForExit(AbortSignal.timeout(3000))}
    await rm(directory,{recursive:true,force:true})
   }
  },
  async fetch(url,signal){if(!ctx.web)throw new InsightError('WEB_UNAVAILABLE','当前宿主没有启用网页读取');return ctx.web.fetch({url},signal)},
  async scheduleCreate(request,actor,signal){return scheduler().create(request,actor.sessionId,signal)},
  async scheduleView(id){return scheduler().view({id})},
  scheduleEdit:(id,active,actor,signal)=>edit(id,{active},actor,signal),
  scheduleUpdate:edit,
 }
}
