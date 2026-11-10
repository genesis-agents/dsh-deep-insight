import {test} from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,rm,readFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {researchExecution} from '../src/research-execution.js'
import {Research} from '../src/research.js'
import {reportCriteria} from '../src/report-review.js'
import {editorialStandard} from '../src/editorial-standard.js'

test('host searches reject unavailable and malformed providers; review has fresh model context',async()=>{
  const signal=new AbortController().signal
  await assert.rejects(researchExecution({tools:{schemas:()=>[]}}).search(['query'],signal),{code:'SEARCH_UNAVAILABLE'})
  await assert.rejects(researchExecution({web:{search:async()=>({sources:[]})}}).search(['query'],signal),{code:'SEARCH_INVALID'})
  const searches=[]
  const searched=await researchExecution({web:{search:async request=>{searches.push(request.query);return {sources:[{url:'https://example.org'}],truncated:false}}}}).search(['first','second'],signal)
  assert.deepEqual(searches,['first','second']);assert.equal(searched.results.length,2);assert.equal(searched.sources.length,1)
  let request
  const execution=researchExecution({llm:{async *stream(input){request=input;yield {type:'text-delta',text:'{"checks":[]}'};yield {type:'finish',reason:{kind:'stop'}}}}})
  assert.equal(await execution.review({provider:'codex',model:'model'},[{role:'user',content:[]}],signal),'{"checks":[]}')
  assert.equal(request.sessionId,undefined)
  assert.deepEqual(request.tools,[])
  assert.equal(request.provider,'codex')
  await assert.rejects(researchExecution({llm:{async *stream(){yield {type:'text-delta',text:'partial'}}}}).review({provider:'codex'},[],signal),{code:'REVIEW_INCOMPLETE'})
  await assert.rejects(researchExecution({llm:{async *stream(){yield {type:'text-delta',text:'retained partial response'};throw Error('stream stopped')}}}).review({provider:'codex'},[],signal),error=>error.code==='MODEL_STREAM_FAILED'&&error.output==='retained partial response')
})

test('execution receipts preserve searches and reject incomplete reviewer coverage without verification',async()=>{
 const workspace=await mkdtemp(join(tmpdir(),'insight-execution-')),signal=new AbortController().signal
 const detail={run:{run_id:'run'},input_snapshot:{project:{subquestions:['Question']},sources:[],plan:{limits:{context_characters:10000}}},analysis:{claims:[{claim_id:'claim'}]},analysis_fingerprint:'frozen',evidence:[],source_versions:[]}
 const execution={search:async()=>({sources:[{url:'https://example.org'}],truncated:false}),review:async()=>JSON.stringify({checks:[]})}
 const research=new Research({cwd:workspace,dir:workspace},{},execution),records=[],commands=[]
 research.readSnapshot=async()=>({details:[detail]})
 research.receipt=async(_s,_run,kind,payload)=>records.push({kind,payload})
 research.invoke=async(_s,args)=>{commands.push(args[0]);if(args[0]==='verification')return JSON.parse(await readFile(args[2],'utf8'));return {quality_state:'machine_verified'}}
 try{
  await research.executeResearch({sessionId:'session'},{action:'search',runId:'run',data:{queries:['Query'],questions:['Question']}},{workspace},signal)
  assert.deepEqual(records.map(r=>r.kind),['search_started','search_completed'])
  await assert.rejects(research.executeResearch({sessionId:'session',provider:'codex',model:'model'},{action:'review',runId:'run'},{workspace},signal),{code:'REVIEW_INVALID'})
  assert.equal(records.at(-1).kind,'review_failed');assert.equal(records.at(-1).payload.output,JSON.stringify({checks:[]}));assert.equal(records.at(-1).payload.code,'REVIEW_INVALID');assert.equal(commands.includes('verification'),false)
  const checks=[{claim_id:'claim',verdict:'unclear',rationale:'Originals insufficient'}]
  execution.review=async()=>JSON.stringify({checks})
  await assert.rejects(research.executeResearch({sessionId:'session',provider:'codex',model:'model'},{action:'review',runId:'run'},{workspace},signal),{code:'REPORT_REVIEW_INVALID'})
  assert.equal(commands.includes('verification'),false)
  execution.review=async(_actor,messages)=>{
   assert.ok(messages[0].content[0].text.includes(editorialStandard))
   return JSON.stringify({checks,section_checks:[],report_checks:reportCriteria.map(criterion=>({criterion,verdict:'failed',rationale:'Chapter does not address the requested question',required_changes:['Explain the missing comparison']}))})
  }
  await research.executeResearch({sessionId:'session',provider:'codex',model:'model'},{action:'review',runId:'run'},{workspace},signal)
  assert.equal(records.at(-1).kind,'review_completed')
  assert.equal(records.at(-1).payload.checks[0].verdict,'unclear')
  assert.equal(records.at(-1).payload.report_checks[0].verdict,'failed')
  assert.deepEqual(commands,['verification','quality'])
 }finally{await rm(workspace,{recursive:true,force:true})}
})
