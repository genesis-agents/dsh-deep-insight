import {test} from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,rm,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {tmpdir} from 'node:os'
import {ResearchCapabilities} from '../src/capabilities.js'
import {resolveCapabilityConfig} from '../src/capability-config.js'
import {validateCapabilityAnalysis} from '../src/capability-analysis.js'

async function fixture(t){
 const workspace=await mkdtemp(join(tmpdir(),'pies-capabilities-'));t.after(()=>rm(workspace,{recursive:true,force:true}))
 const source={source_id:'s1',title:'Synthetic source',resource_uri:'https://example.org/source'}
 const version={version_id:'v1',source_id:'s1',raw_artifact_id:'raw1',extracted_artifact_id:'text1',published_at:'2026-05-26'}
 const quote='GPU networking improved in the reported experiment.',evidence={evidence_id:'e1',source_version_id:'v1',quote,locator:{unit_index:1,char_start:0,char_end:quote.length}}
 const detail={run:{run_id:'run1'},input_snapshot:{project:{question:'Synthetic research',subquestions:['What changed?']},sources:[source],plan:{limits:{context_characters:1000000}}},source_versions:[version,{...version,version_id:'v2'}],evidence:[evidence],analysis:{claims:[{claim_id:'c1',statement:quote,evidence_links:[{evidence_id:'e1',relation:'supports'}]}]}}
 const receipts=[],documents={units:[{index:1,kind:'document',text:quote},{index:2,kind:'document',text:'A\twide　space\n\nAnother line.'}],warnings:[]}
 let changed=false,modelOutput,fetchFailure=false,schedules=0
 const tasks=new Map(),ports={
  embed:async texts=>({model:'fixture-model',dimensions:2,vectors:texts.map((text,index)=>text.startsWith('query:')?[1,0]:index%2?[0,1]:[1,0])}),
  fetch:async url=>{if(fetchFailure)throw Error('network unavailable');return {url,statusCode:200,truncated:false,body:{kind:'text',content:changed?'Changed GPU material':'Original GPU material'}}},
  scheduleCreate:async request=>{const task={...request,id:'schedule-'+(++schedules),status:'active',updatedAt:'initial'};tasks.set(task.id,task);return task},
  scheduleView:async id=>tasks.get(id),scheduleEdit:async(id,active)=>{const task={...tasks.get(id),status:active?'active':'paused'};tasks.set(id,task);return task},
  scheduleUpdate:async(id,patch)=>{const task={...tasks.get(id),...patch,status:patch.active?'active':'paused'};tasks.set(id,task);return task},
 }
 const research={workspace:()=>workspace,settings:async()=>({workspace,engineRoot:'/fixture'}),snapshot:async()=>({details:[detail]}),invoke:async()=>documents,receipt:async(_settings,run,kind,payload)=>receipts.push({run,kind,payload}),execution:{review:async(_actor,messages)=>typeof modelOutput==='function'?modelOutput(messages):modelOutput},running:new Map()}
 const service=new ResearchCapabilities(research,resolveCapabilityConfig({enrichment:{embeddingModel:'fixture-model'}}),ports)
 const actor={sessionId:'session1',preset:'workspace-write',provider:'fixture',model:'fixture'},signal=new AbortController().signal
 const execute=(kind,data={})=>service.execute(actor,{action:'enrich',runId:'run1',data:{kind,...data}},signal)
 return {workspace,detail,service,execute,actor,signal,receipts,tasks,ports,setChanged:value=>{changed=value},setOutput:value=>{modelOutput=value},setFetchFailure:value=>{fetchFailure=value}}
}
const products={
 entities:{entities:[{name:'GPU',category:'technology',aliases:[],evidence_ids:['e1']}],limitations:['Synthetic fixture only']},
 structure:{nodes:[{id:'gpu',label:'GPU',evidence_ids:['e1']},{id:'network',label:'networking',evidence_ids:['e1']}],edges:[{source:'gpu',target:'network',relation:'uses',evidence_ids:['e1']}],limitations:[]},
 trend:{signals:[{date:'2026-05-26',date_basis:'publication',date_quote:'GPU networking improved',statement:'One published observation; not a population trend',direction:'unknown',dimension:'networking',evidence_ids:['e1']}],conclusion:'One observation does not establish a trend.',limitations:['No comparable time series']},
 benchmark:{dimensions:['networking'],rows:[{subject:'GPU',values:[{dimension:'networking',value:'Improvement reported without comparable measurements',conditions:['Reported experiment only'],evidence_ids:['e1']}]}],limitations:['No common baseline']},
 impact:{assessments:[{affected_entity:'GPU networking',mechanism:'Potentially improves communication',direction:'uncertain',conditions:['Only if the experiment transfers to the deployment'],actions:['Validate a common baseline'],evidence_ids:['e1']}],limitations:['No economic impact measured']},
}

test('all ten enrichments have real execution, durable products, retrieval and monitor controls',async t=>{
 const f=await fixture(t),results=[]
 for(const kind of ['dedup','normalize','entities','structure','trend','benchmark','impact','vectors','knowledge'])results.push(await f.execute(kind,products[kind]?{result:products[kind]}:{}))
 assert.equal(results[0].result.groups.length,2)
 assert.equal((await f.service.record('session1','run1',results[1].record_id)).result.documents[0].units[1].text,'A wide space\n\nAnother line.')
 const query=await f.execute('vectors',{query:'GPU networking',limit:2})
 assert.equal(query.matches.length,2);assert.equal(query.matches[0].score,1);assert.equal(query.matches[0].source_version_id,'v1')
 const exported=await f.service.exportKnowledge('session1','run1',results.at(-1).record_id)
 assert.equal(exported.documents.length,2);assert.equal(exported.evidence[0].evidence_id,'e1')
 const subscribed=await f.execute('alerts',{urls:['https://example.org/source'],timing:{kind:'every',every_seconds:3600},keywords:['GPU']})
 assert.equal(subscribed.result.schedule.target.sessionId,'session1')
 const updated=await f.execute('alerts',{urls:['https://example.org/source'],timing:{kind:'every',every_seconds:7200},keywords:['GPU']})
 assert.equal(updated.result.schedule.id,subscribed.result.schedule.id);assert.equal(f.tasks.size,1)
 f.setChanged(true)
 const checked=await f.execute('alerts',{mode:'check'})
 assert.equal(checked.result.changes.length,1)
 const paused=await f.execute('alerts',{mode:'pause'});assert.equal(paused.result.schedule.status,'paused')
 const resumed=await f.execute('alerts',{mode:'resume'});assert.equal(resumed.result.schedule.status,'active')
 const summaries=await f.service.summaries('session1',f.detail)
 assert.equal(Object.keys(summaries).length,10)
 assert.ok(Object.values(summaries).every(item=>item.status==='completed'&&!item.stale))
 assert.ok(Object.values(summaries).every(item=>!Object.hasOwn(item,'result')&&!Object.hasOwn(item,'request')))
 const reopened=new ResearchCapabilities(f.service.research,f.service.config,f.ports)
 assert.equal((await reopened.summaries('session1',f.detail)).knowledge.status,'completed')
 assert.equal((await reopened.record('session1','run1',resumed.record_id)).liveSchedule.status,'active')
})

test('unproven references, mismatched graph endpoints and invented dates cannot become saved products',async t=>{
 const f=await fixture(t)
 await assert.rejects(f.execute('entities',{result:{...products.entities,entities:[{...products.entities.entities[0],evidence_ids:['foreign-evidence']}]}}),error=>error.code==='CAPABILITY_EVIDENCE_INVALID')
 assert.throws(()=>validateCapabilityAnalysis('entities',{...products.entities,entities:[{...products.entities.entities[0],name:'Invented company'}]},f.detail),error=>error.code==='CAPABILITY_EVIDENCE_INVALID')
 assert.throws(()=>validateCapabilityAnalysis('structure',{...products.structure,edges:[{...products.structure.edges[0],target:'missing'}]},f.detail),error=>error.code==='CAPABILITY_RESULT_INVALID')
 assert.throws(()=>validateCapabilityAnalysis('trend',{...products.trend,signals:[{...products.trend.signals[0],date:'2025-01-01'}]},f.detail),error=>error.code==='CAPABILITY_EVIDENCE_INVALID')
 assert.equal((await f.service.summaries('session1',f.detail)).entities.status,'failed')
})

test('model requests and invalid raw replies remain complete; stale analysis does not invalidate text processing',async t=>{
 const f=await fixture(t)
 f.setOutput(JSON.stringify({entities:products.entities}))
 const generated=await f.execute('entities')
 assert.equal(generated.result.method,'isolated-model-analysis')
 assert.equal(f.receipts[0].kind,'capability_requested')
 const record=await f.service.record('session1','run1',generated.record_id)
 assert.ok(record.request.messages[0].content[0].text.includes('e1'));assert.equal(record.output,JSON.stringify({entities:products.entities}))
 await f.execute('normalize');await f.execute('impact',{result:products.impact})
 f.detail.analysis.claims[0].statement='Updated analysis'
 const summaries=await f.service.summaries('session1',f.detail)
 assert.equal(summaries.impact.stale,true);assert.equal(summaries.normalize.stale,false)
 f.setOutput('not JSON; full failed reply')
 await assert.rejects(f.execute('benchmark'))
 const failed=(await f.service.summaries('session1',f.detail)).benchmark
 assert.equal((await f.service.record('session1','run1',failed.id)).output,'not JSON; full failed reply')
})

test('artifacts reject tampering and path escapes; failed monitoring cannot create a schedule',async t=>{
 const f=await fixture(t),saved=await f.execute('vectors')
 await assert.rejects(f.service.record('session1','run1','../elsewhere'),error=>error.code==='INVALID_ID')
 const artifact=saved.result.artifact,path=join(f.workspace,'.capabilities','run1',artifact.id+'.data.json')
 const original=await readFile(path,'utf8');await writeFile(path,original.replace('fixture-model','changed-model'))
 await assert.rejects(f.execute('vectors',{query:'GPU'}),error=>error.code==='CAPABILITY_ARTIFACT_CHANGED')
 f.setFetchFailure(true)
 await assert.rejects(f.execute('alerts',{timing:{kind:'every',every_seconds:3600}}),/network unavailable/)
 assert.equal(f.tasks.size,0)
 await assert.rejects(f.execute('alerts',{}),error=>error.code==='ALERT_TIMING_REQUIRED')
})

test('Chinese reading aligns every complete source sentence and reuses the saved translation',async t=>{
 const f=await fixture(t)
 f.setOutput(messages=>{
  const source=JSON.parse(messages[0].content[0].text.split('\n原句：')[1])
  return JSON.stringify({sentences:source.map(item=>({id:item.id,translation:'该实验报告了 GPU 网络改进。',explanation:'只陈述这项实验。'})),glossary:[{term:'GPU',meaning:'图形处理器'}],limitations:['机器译文须结合原文核对']})
 })
 const first=await f.execute('interpret',{version:'v1',unit:1})
 assert.equal(first.result.sentences.length,1)
 assert.equal(first.result.sentences[0].text,f.detail.evidence[0].quote)
 assert.equal(first.result.sentences[0].translation,'该实验报告了 GPU 网络改进。')
 const calls=f.receipts.length
 const cached=await f.execute('interpret',{version:'v1',unit:1})
 assert.equal(cached.cached,true);assert.equal(cached.record_id,first.record_id);assert.equal(f.receipts.length,calls)
 f.setOutput(JSON.stringify({sentences:[],glossary:[],limitations:[]}))
 await assert.rejects(f.execute('interpret',{version:'v1',evidence_ids:['e1']}),error=>error.code==='INTERPRETATION_INCOMPLETE')
 const summary=(await f.service.summaries('session1',f.detail)).interpret
 assert.equal(summary.status,'failed');assert.ok((await f.service.record('session1','run1',summary.id)).output)
})
