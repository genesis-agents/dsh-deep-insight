/** Session-local enrichment receipts and immutable derived files, separate from engine originals. */
import {mkdir,readFile,writeFile,rename,realpath,unlink} from 'node:fs/promises'
import {join} from 'node:path'
import {randomUUID,createHash} from 'node:crypto'
import {z} from 'zod'
import {contained,InsightError} from './engine.js'

export const capabilityKinds=['dedup','normalize','entities','structure','vectors','trend','benchmark','impact','knowledge','alerts']
const recordKinds=[...capabilityKinds,'interpret']
const id=z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/)
const identifier=value=>{if(!id.safeParse(value).success)throw new InsightError('INVALID_ID','能力记录标识无效');return value}
const receipt=z.object({schemaVersion:z.literal(1),id,runId:id,kind:z.enum(recordKinds),basis:z.string(),status:z.enum(['running','completed','failed','cancelled']),startedAt:z.string(),finishedAt:z.string().optional(),count:z.number().int().nonnegative().optional(),result:z.unknown().optional(),request:z.unknown().optional(),output:z.string().optional(),error:z.object({code:z.string(),message:z.string()}).optional()}).strict()
const summarySchema=receipt.omit({result:true,request:true,output:true})
const indexSchema=z.object({schemaVersion:z.literal(2),latest:z.partialRecord(z.enum(recordKinds),summarySchema),latestSucceeded:z.partialRecord(z.enum(recordKinds),summarySchema)}).strict()
export const capabilityHash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex')

/** Derive freshness from the inputs each capability actually consumes. */
export function capabilityBasis(kind,detail,config){
 const project=detail.input_snapshot?.project,versions=detail.source_versions??[],evidence=detail.evidence??[]
 const value=kind==='alerts'?{project}:['dedup','normalize'].includes(kind)?{versions}:kind==='vectors'?{versions,model:config.embeddingModel,dtype:config.embeddingDtype,chunk:config.embeddingChunkCharacters}:['entities','structure','trend','interpret'].includes(kind)?{versions,evidence}:kind==='knowledge'?{project,versions,evidence,analysis:detail.analysis}: {evidence,analysis:detail.analysis}
 return capabilityHash(value)
}

/** Keep every execution receipt; only the small latest-record index is replaced. */
export class CapabilityStorage{
 constructor(workspace){this.workspace=workspace;this.active=new Set()}
 async directory(sessionId,runId,create=false){
  identifier(sessionId);identifier(runId)
  const workspace=this.workspace(sessionId),directory=join(workspace,'.capabilities',runId)
  if(create)await mkdir(directory,{recursive:true})
  const root=await realpath(workspace),resolved=await realpath(directory)
  if(!contained(root,resolved))throw new InsightError('OUTSIDE_WORKSPACE','能力产物目录不在当前研究工作区内',403)
  return resolved
 }
 async atomic(directory,name,value){
  const temporary=join(directory,randomUUID()+'.tmp')
  try{await writeFile(temporary,JSON.stringify(value)+'\n',{mode:0o600});await rename(temporary,join(directory,name))}
  finally{await unlink(temporary).catch(error=>{if(error.code!=='ENOENT')throw error})}
 }
 async read(sessionId,runId,recordId){
  identifier(recordId)
  const directory=await this.directory(sessionId,runId),path=await realpath(join(directory,recordId+'.json'))
  if(!contained(directory,path))throw new InsightError('OUTSIDE_WORKSPACE','能力记录不在当前批次中',403)
  const value=receipt.parse(JSON.parse(await readFile(path,'utf8')))
  if(value.runId!==runId||value.id!==recordId)throw new InsightError('CAPABILITY_RECORD_MISMATCH','能力记录与当前批次不匹配')
  return value.status==='running'&&!this.active.has(value.id)?{...value,status:'interrupted'}:value
 }
 async summaries(sessionId,detail,config){
  let directory,index
  try{directory=await this.directory(sessionId,detail.run.run_id);index=indexSchema.parse(JSON.parse(await readFile(join(directory,'index.json'),'utf8')))}
  catch(error){if(error.code==='ENOENT')return {};throw error}
  const entries=Object.entries(index.latest).map(([kind,record])=>{
   if(record.kind!==kind||record.runId!==detail.run.run_id)throw new InsightError('CAPABILITY_RECORD_MISMATCH','能力索引与执行记录不匹配')
   const basis=capabilityBasis(kind,detail,config),previous=index.latestSucceeded[kind]
   const status=record.status==='running'&&!this.active.has(record.id)?'interrupted':record.status
   return [kind,{...record,status,stale:record.basis!==basis,...previous&&previous.id!==record.id&&previous.basis===basis?{previousSuccessId:previous.id}:{}}]
  })
  return Object.fromEntries(entries)
 }
 async save(sessionId,record){
  receipt.parse(record)
  const directory=await this.directory(sessionId,record.runId,true)
  let index={schemaVersion:2,latest:{},latestSucceeded:{}}
  try{index=indexSchema.parse(JSON.parse(await readFile(join(directory,'index.json'),'utf8')))}catch(error){if(error.code!=='ENOENT')throw error}
  await this.atomic(directory,record.id+'.json',record)
  const {result,request,output,...summary}=record
  index.latest[record.kind]=summary
  if(record.status==='completed')index.latestSucceeded[record.kind]=summary
  await this.atomic(directory,'index.json',index)
 }
 async artifact(sessionId,runId,artifactId,value){
  identifier(artifactId)
  const directory=await this.directory(sessionId,runId,true)
  await this.atomic(directory,artifactId+'.data.json',value)
  return {id:artifactId,sha256:capabilityHash(value)}
 }
 async cached(sessionId,runId,key){
  let directory,cache
  try{directory=await this.directory(sessionId,runId);cache=z.record(z.string().regex(/^[a-f0-9]{64}$/),id).parse(JSON.parse(await readFile(join(directory,'cache.json'),'utf8')))}catch(error){if(error.code==='ENOENT')return null;throw error}
  return cache[key]?this.read(sessionId,runId,cache[key]):null
 }
 async remember(sessionId,runId,key,recordId){
  const directory=await this.directory(sessionId,runId,true);let cache={}
  try{cache=z.record(z.string().regex(/^[a-f0-9]{64}$/),id).parse(JSON.parse(await readFile(join(directory,'cache.json'),'utf8')))}catch(error){if(error.code!=='ENOENT')throw error}
  cache[key]=identifier(recordId)
  await this.atomic(directory,'cache.json',cache)
 }
 async loadArtifact(sessionId,runId,artifact){
  identifier(artifact.id)
  const directory=await this.directory(sessionId,runId),path=await realpath(join(directory,artifact.id+'.data.json'))
  if(!contained(directory,path))throw new InsightError('OUTSIDE_WORKSPACE','能力文件不在当前批次中',403)
  const value=JSON.parse(await readFile(path,'utf8'))
  if(capabilityHash(value)!==artifact.sha256)throw new InsightError('CAPABILITY_ARTIFACT_CHANGED','能力文件校验失败，请重新生成')
  return value
 }
}
