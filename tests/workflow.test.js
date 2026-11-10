import {test} from 'node:test'
import assert from 'node:assert/strict'
import {workflowModel,workflowTransfers} from '../client/src/workflow-model.js'
import {businessModel} from '../client/src/business-model.js'
import {nodeDetails} from '../client/src/node-details.js'

test('execution history has one dedicated entry and is absent from every business node',()=>{
 const state={events:[],details:[]},model=businessModel(null,state)
 for(const node of model.nodes){
  const detail=nodeDetails(null,state,{nodeId:node.id})
  assert.equal(detail.sections.some(section=>section.kind==='logs'),node.id==='orchestrator',node.id)
 }
 assert.ok(nodeDetails(null,state,{nodeId:'orchestrator'}).sections.some(section=>section.kind==='logs'))
 assert.deepEqual(state,{events:[],details:[]})
})

test('empty research shows pending topology without connected channels or transfer motion',()=>{
  const model=workflowModel(null,{details:[],events:[]})
  assert.equal(model.nodes.length,7)
  assert(model.nodes.every(node=>node.status==='waiting'))
  assert(model.groups.every(group=>group.status==='wfNotConnected'))
  assert.deepEqual(workflowTransfers(null,model),[])
})

test('lineage preserves acquisition failure, real processing artifacts and evidence associations',()=>{
  const detail={run:{run_id:'one'},input_snapshot:{sources:[{source_id:'repo',provider:'http',resource_uri:'https://github.com/example/repo',title:'Repository'},{source_id:'video',provider:'youtube',origin:{channel:'youtube'},title:'Talk'}],plan:{items:[{source_ref:'video',goal:'video_transcript',access_mode:'public_http'}]}},source_versions:[{source_id:'repo',version_id:'v1',raw_artifact_id:'raw',extracted_artifact_id:'text'}],evidence:[{evidence_id:'quote',source_version_id:'v1'}],observations:[{source_id:'video',goal_result:{state:'not_met',detail:'No transcript'}}],events:[]}
  const model=workflowModel(detail,{events:[]})
  assert.equal(model.groups.find(g=>g.channel==='opensource').records[0].evidence,1)
  const video=model.groups.find(g=>g.channel==='youtube')
  assert.equal(video.status,'failed')
  assert.equal(video.records[0].reason,'No transcript')
  assert.equal(video.records[0].goal,'wfTranscript')
  assert.equal(model.nodes.find(n=>n.id==='process').count,1)
  assert.equal(model.nodes.find(n=>n.id==='process').status,'done')
  assert.notEqual(model.nodes.find(n=>n.id==='evidence').status,'passed')
  assert.equal(model.nodes.find(n=>n.id==='deliver').status,'waiting')
  assert.deepEqual(workflowTransfers(null,model),[])
  const next=structuredClone(detail);next.source_versions.push({source_id:'video',version_id:'v2',raw_artifact_id:'raw2',extracted_artifact_id:'text2'})
  const changed=workflowModel(next,{events:[]})
  assert.deepEqual(workflowTransfers(model,changed).filter(edge=>!edge.channel).map(edge=>[edge.to,edge.delta]),[['acquire',1],['process',1]])
  assert.deepEqual(workflowTransfers(model,changed).filter(edge=>edge.channel).map(edge=>[edge.channel,edge.to,edge.delta]),[['youtube','acquire',1],['youtube','process',1]])
  assert.deepEqual(workflowTransfers(changed,changed),[])
  const other=structuredClone(changed);other.runId='two'
  assert.deepEqual(workflowTransfers(model,other),[])
})

test('archived delivery remains distinct from quality and stale reviews stay stale',()=>{
 const detail={run:{run_id:'one'},delivery:{files:[{path:'report.html'}]},verification_status:'stale',assessment:[{gate_id:'report_composition',state:'failed'}],analysis:{claims:[]},events:[]}
 const model=workflowModel(detail,{events:[]})
 assert.equal(model.nodes.find(n=>n.id==='deliver').status,'wfArchived')
 assert.equal(model.nodes.find(n=>n.id==='review').status,'stale')
 assert.equal(model.failedChecks.length,1)
 const revised=structuredClone(detail);revised.analysis_fingerprint='new-analysis'
 const old=workflowModel({...detail,analysis_fingerprint:'old-analysis'},{events:[]})
 assert.equal(workflowTransfers(old,workflowModel(revised,{events:[]})).find(edge=>edge.to==='analysis').updated,true)
})

test('historical batches do not inherit another run operation and source selection stays exact',()=>{
 const detail={run:{run_id:'history'},input_snapshot:{sources:[{source_id:'one',provider:'local',title:'First'},{source_id:'two',provider:'local',title:'Second'}]}}
 const state={current:{runId:'active',action:'analysis'}}
 const model=businessModel(detail,state)
 assert.equal(model.current,null)
 assert.notEqual(model.nodes.find(node=>node.id==='orchestrator').status,'wfRunning')
 const selected=nodeDetails(detail,state,{nodeId:'lane:sources',recordId:'two'})
 assert.deepEqual(selected.sections.find(section=>section.kind==='sources').items.map(item=>item.id),['two'])
 assert.equal(businessModel(detail,{current:{runId:'history',action:'analysis'}}).current.action,'analysis')
})

test('activity retains all batch events and separates legacy session operations from the selected batch',()=>{
 const events=Array.from({length:140},(_,sequence)=>({sequence,kind:'evidence_selected',at:new Date(sequence*1000).toISOString(),payload:{evidence_id:'e'+sequence}}))
 const model=workflowModel({run:{run_id:'batch'},events},{events:[{action:'analysis',runId:'other'},{action:'worker'},{action:'evidence',runId:'batch'}]})
 assert.equal(model.logs.length,141)
 assert.equal(model.logs.filter(log=>log.scope==='wfBatchLog').length,140)
 assert.equal(model.sessionLogs.length,3)
 assert.equal(model.logs.some(log=>log.kind==='analysis'),false)
 assert.equal(model.logs.some(log=>log.kind==='worker'),false)
 assert.equal(businessModel({run:{run_id:'batch',execution_state:'waiting_input'},events},{events:[]}).nodes.find(node=>node.id==='orchestrator').status,'wfWaitingInput')
})
