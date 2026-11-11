import {test} from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp, rm, readFile, writeFile, readdir} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {Research} from '../src/research.js'
import {researchCheckpoint} from '../src/research-checkpoint.js'
import {validateSectionReview, reportCriteria} from '../src/report-review.js'
import {researchExecution} from '../src/research-execution.js'
import {researchPolicy} from '../src/research-policy.js'
import {researchStages} from '../client/src/model.js'

test('a reviewer can retain omitted counterevidence without granting unsupported approval', () => {
  const analysis = {claims:[{claim_id:'c',evidence_links:[{evidence_id:'author'}]}],narrative:{sections:[{section_id:'s',claim_ids:['c'],blocks:[{kind:'paragraph',text:'The platform exists; its economic effect is unknown.'}]}]}}
  const row = {section_id:'s',verdict:'unclear',analysis_excerpt:'economic effect is unknown',evidence_ids:['omitted'],rationale:'The unselected comparison contradicts the asserted effect.',required_changes:['Compare the omitted original.']}
  assert.equal(validateSectionReview([row],analysis,[{evidence_id:'omitted'}])[0].verdict,'unclear')
  assert.throws(() => validateSectionReview([row],analysis,[]),{code:'SECTION_REVIEW_INVALID'})
  assert.throws(() => validateSectionReview([{...row,verdict:'passed',required_changes:[]}],analysis,[{evidence_id:'omitted'}]),{code:'SECTION_REVIEW_INVALID'})
  analysis.narrative.sections[0].claim_ids=[]
  analysis.narrative.sections[0].blocks.push({kind:'table',rows:[{claim_ids:['c']}]})
  assert.equal(validateSectionReview([{...row,verdict:'passed',evidence_ids:['author'],required_changes:[]}],analysis)[0].verdict,'passed')
})

test('checkpoint prioritizes unavailable discovery over polishing an unsupported report', t => {
  const detail={run:{run_id:'case'},input_snapshot:{project:{subquestions:['How did the advantage form?'],research_design:[{subquestion:'How did the advantage form?',alternatives:['selection','platform effect'],evidence_needed:['matched outcomes'],stop_condition:'A bounded mechanism can be distinguished'}]}},events:[{kind:'search_failed',payload:{code:'AUTH_FAILED',error:'Configure the research search credential'}}]}
  const quality={quality_state:'draft',next_actions:[{gate_id:'report_review',detail:'Explain the mechanism'},{gate_id:'search_record',detail:'Acquire question-specific discovery'}]}
  t.assert.snapshot(researchCheckpoint(detail,quality))
  t.assert.snapshot({design:researchPolicy.researchDesign,support:researchPolicy.claimSupport,revision:researchPolicy.revision})
  assert.equal(researchCheckpoint(detail,{quality_state:'machine_verified',next_actions:[]}).next.action,'deliver')
})

test('a designed question cannot appear analyzed before its assessment exists', () => {
  const detail={run:{},input_snapshot:{project:{research_design:[]}},analysis:{},assessment:[{gate_id:'report_composition',state:'passed'},{gate_id:'independent_support',state:'passed'},{gate_id:'question_analysis',state:'failed'}]}
  assert.equal(researchStages(detail)[2].status,'needsWork')
  detail.assessment[2].state='passed'
  assert.equal(researchStages(detail)[2].status,'passed')
})

test('question-linked discovery receipts preserve the exact query assignment and block collection on failure', async t => {
  const workspace=await mkdtemp(join(tmpdir(),'insight-cycle-'))
  t.after(()=>rm(workspace,{recursive:true,force:true}))
  const detail={run:{run_id:'run',execution_state:'queued'},input_snapshot:{project:{subquestions:['Q1','Q2'],research_design:[],quality_standard:{require_search_record:true}}},events:[]}
  const research=new Research({dir:workspace,cwd:workspace},{},{search:async queries=>({results:queries.map(query=>({query,sources:[{url:'https://example.org/'+query}],truncated:false})),sources:[{url:'https://example.org'}],truncated:false})})
  research.readSnapshot=async()=>({details:[detail]})
  research.settings=async()=>({workspace})
  const records=[],commands=[]
  research.receipt=async(_s,_r,kind,payload)=>records.push({kind,payload})
  research.invoke=async(_s,args)=>{commands.push(args[0]);return {quality_state:'draft',next_actions:[{gate_id:'search_record',detail:'Not searched'}]}}
  const signal=new AbortController().signal,actor={sessionId:'s'}
  await assert.rejects(research.executeResearch(actor,{action:'search',runId:'run',data:{queries:['generic'],questions:['Q1','Q2']}},{workspace},signal),{code:'INVALID_SEARCH'})
  const result=await research.executeResearch(actor,{action:'search',runId:'run',data:{searches:[{query:'one',question:'Q1'},{query:'two',question:'Q2'}]}},{workspace},signal)
  assert.deepEqual(result.results.map(row=>row.question),['Q1','Q2'])
  assert.deepEqual(records.map(row=>row.kind),['search_started','search_completed'])
  await assert.rejects(research.execute(actor,{action:'worker'},signal),{code:'RESEARCH_SEARCH_REQUIRED'})
  assert.deepEqual(commands,['quality'])
  research.execution.search=async()=>{const error=Error('Authentication failed');error.code='AUTH_FAILED';throw error}
  await assert.rejects(research.executeResearch(actor,{action:'search',runId:'run',data:{searches:[{query:'one',question:'Q1'}]}},{workspace},signal),{code:'AUTH_FAILED'})
  assert.equal(records.at(-1).payload.code,'AUTH_FAILED')
  const other={...detail,run:{run_id:'other',execution_state:'queued'}}
  research.readSnapshot=async()=>({details:[other,detail]})
  await assert.rejects(research.execute(actor,{action:'worker'},signal),{code:'RUN_REQUIRED'})
  research.invoke=async(_s,args)=>{
    if(args[0]==='status')return detail
    if(args[0]==='quality')return {quality_state:'draft',next_actions:[]}
    assert.deepEqual(args,['worker','--max-jobs','1','--run','run'])
    return {processed_runs:['run']}
  }
  assert.deepEqual(await research.execute(actor,{action:'worker',runId:'run'},signal),{processed_runs:['run']})
})

test('independent review reads unselected originals and retains chapter-specific negative findings', async t => {
  const workspace=await mkdtemp(join(tmpdir(),'insight-review-cycle-'))
  t.after(()=>rm(workspace,{recursive:true,force:true}))
  const analysis={claims:[{claim_id:'c',evidence_links:[{evidence_id:'e',relation:'supports'}]}],narrative:{sections:[{section_id:'s',claim_ids:['c'],blocks:[{kind:'paragraph',text:'The institution reports activity, not measured net impact.'}]}]}}
  const detail={run:{run_id:'r'},input_snapshot:{project:{subquestions:['Q']},sources:[],plan:{limits:{context_characters:50000}}},source_versions:[{version_id:'used',extracted_artifact_id:'a'},{version_id:'omitted',extracted_artifact_id:'b'}],evidence:[{evidence_id:'e',source_version_id:'used'},{evidence_id:'counter',source_version_id:'omitted'}],analysis,analysis_fingerprint:'current'}
  const records=[],documents=[]
  const research=new Research({dir:workspace,cwd:workspace},{},{review:async(_actor,messages)=>{
    assert.ok(messages[0].content[0].text.includes('Omitted comparison'))
    return JSON.stringify({checks:[{claim_id:'c',verdict:'supported',rationale:'Attribution is accurate.'}],report_checks:reportCriteria.map(criterion=>({criterion,verdict:'unclear',rationale:'Mechanism lacks a comparison',required_changes:['Acquire matched outcomes']})),section_checks:[{section_id:'s',verdict:'unclear',analysis_excerpt:'not measured net impact',evidence_ids:['counter'],rationale:'The author omitted the comparison.',required_changes:['Compare the original.']}]})
  }})
  research.readSnapshot=async()=>({details:[detail]})
  research.receipt=async(_s,_r,kind,payload)=>records.push({kind,payload})
  research.invoke=async(_s,args)=>{
    if(args[0]==='document'){documents.push(args.at(-1));return {units:[{text:args.at(-1)==='omitted'?'Omitted comparison':'Selected original'}]}}
    if(args[0]==='verification')return JSON.parse(await readFile(args[2],'utf8'))
    return {quality_state:'draft',next_actions:[]}
  }
  await research.executeResearch({sessionId:'s'},{action:'review',runId:'r'},{workspace},new AbortController().signal)
  assert.deepEqual(documents,['used','omitted'])
  assert.equal(records.at(-1).kind,'review_completed')
  assert.equal(records.at(-1).payload.section_checks[0].evidence_ids[0],'counter')
})

test('visual admission uses durable host references and refuses a declared text-only model',async()=>{
  const signal=new AbortController().signal,inputs=[{data:Buffer.from('test image'),mediaType:'image/png'}]
  let saved
  const ctx={get:()=>({saveImages:async value=>{saved=value;return [{attachmentId:'stored'}]}}),llm:{resolveModelInfo:async()=>({inputModalities:['text','image']})}}
  assert.deepEqual(await researchExecution(ctx).images({provider:'p',model:'m'},inputs,signal),[{type:'image',attachment:{attachmentId:'stored'}}])
  assert.equal(saved,inputs)
  ctx.llm.resolveModelInfo=async()=>({inputModalities:['text']})
  await assert.rejects(researchExecution(ctx).images({provider:'p',model:'m'},inputs,signal),{code:'REVIEW_IMAGES_UNAVAILABLE'})
})

test('figure review sends original pixels with exact source references and cleans temporary exports', async t => {
  const workspace=await mkdtemp(join(tmpdir(),'insight-figure-review-'))
  t.after(()=>rm(workspace,{recursive:true,force:true}))
  const analysis={claims:[{claim_id:'c',evidence_links:[{evidence_id:'e'}]}],narrative:{sections:[{section_id:'s',claim_ids:['c'],blocks:[{kind:'paragraph',text:'The original plan has two centers.'},{kind:'figure',source_version_id:'v',unit_index:31}]}]}}
  const detail={run:{run_id:'r'},input_snapshot:{project:{subquestions:['Q']},sources:[],plan:{limits:{context_characters:50000}}},source_versions:[{version_id:'v',extracted_artifact_id:'a'}],evidence:[{evidence_id:'e',source_version_id:'v'}],analysis,analysis_fingerprint:'current'}
  const records=[]
  let reviewReply
  const engine={run:async(_root,argv)=>{
    const path=join(argv.at(-1),'original.png')
    await writeFile(path,Buffer.from('archived original pixels'))
    return [{path,mediaType:'image/png',source_version_id:'v',unit_index:31}]
  }}
  const execution={images:async(_actor,inputs)=>{
    assert.equal(inputs[0].data.toString(),'archived original pixels')
    assert.equal(inputs[0].name,'v-page-31')
    return [{type:'image',attachment:{attachmentId:'durable-image'}}]
  },review:async(_actor,messages)=>{
    assert.equal(messages[0].content[1].attachment.attachmentId,'durable-image')
    assert.ok(messages[0].content[0].text.includes('"unit_index":31'))
    reviewReply = JSON.stringify({checks:[{claim_id:'c',verdict:'supported',rationale:'Original plan inspected.'}],report_checks:reportCriteria.map(criterion=>({criterion,verdict:'passed',rationale:'Bounded finding matches the supplied original.',required_changes:[]})),section_checks:[{section_id:'s',verdict:'passed',analysis_excerpt:'two centers',evidence_ids:['e'],rationale:'The plan and caption agree.',required_changes:[]}]})
    return reviewReply
  }}
  const research=new Research({dir:workspace,cwd:workspace},engine,execution)
  research.readSnapshot=async()=>({details:[detail]})
  research.receipt=async(_s,_r,kind,payload)=>records.push({kind,payload})
  research.invoke=async(_s,args)=>args[0]==='document'?{units:[{text:'Original plan description'}]}:{quality_state:'machine_verified',next_actions:[]}
  await research.executeResearch({sessionId:'s'},{action:'review',runId:'r'},{workspace,engineRoot:workspace},new AbortController().signal)
  assert.equal(records.at(-1).payload.visual_scope.available,true)
  assert.equal((await readdir(workspace)).some(name=>name.startsWith('.review-images-')),false)
  delete execution.images
  execution.review=async()=>reviewReply
  await assert.rejects(research.executeResearch({sessionId:'s'},{action:'review',runId:'r'},{workspace,engineRoot:workspace},new AbortController().signal),{code:'VISUAL_REVIEW_UNAVAILABLE'})
  assert.equal(records.at(-1).kind,'review_failed')
})
