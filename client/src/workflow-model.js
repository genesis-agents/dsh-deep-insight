/** Research lineage from saved run inputs, acquisition observations and current assessments. */
import {currentGates, researchStages, sourceTitle, webLink} from './model.js'

const channels=['official','paper','opensource','youtube','x','feed','local','email']
const goals={document_text:'wfDocument',slides_only:'wfSlides',editable_original_pptx:'wfSlides',metadata:'wfMetadata',full_talk_analysis:'wfVideo',latest_posts:'wfPosts',video_transcript:'wfTranscript',video_frames:'wfFrames',public_post:'wfPosts',discover_updates:'wfUpdates',observed_posts:'wfPosts'}
const channelOf=source=>{
  const url=webLink(source.resource_uri)
  if(url&&/^(www\.)?(github\.com|gitlab\.com|huggingface\.co)$/i.test(new URL(url).hostname))return 'opensource'
  return source.origin?.channel??(source.provider==='local'?'local':source.provider==='http'?'official':source.provider)
}

/** Counts refer to distinct source/version/evidence ids; saved output never implies passed quality.
 * @param detail Selected batch snapshot, absent before a run exists.
 * @param state Session activity and runtime operation.
 * @returns Read-only nodes, channel branches, saved counts and scoped logs.
 */
export function workflowModel(detail,state) {
  const sources=detail?.input_snapshot?.sources??[],versions=detail?.source_versions??[],observations=detail?.observations??[]
  const items=detail?.input_snapshot?.plan?.items??[],evidence=detail?.evidence??[],events=detail?.events??[]
  const requirements=detail?.input_snapshot?.project?.collection_requirements??[]
  const groups=[...new Set([...channels,...requirements.map(item=>item.channel),...sources.map(channelOf)])].map(channel=>{
    const records=sources.filter(source=>channelOf(source)===channel).map(source=>{
      const plan=items.find(item=>item.source_ref===source.source_id)
      const saved=versions.filter(version=>version.source_id===source.source_id)
      const observation=observations.find(item=>item.source_id===source.source_id)
      const quotes=evidence.filter(item=>saved.some(version=>version.version_id===item.source_version_id))
      return {id:source.source_id,title:sourceTitle(source),uri:webLink(source.resource_uri),provider:source.provider,goal:goals[plan?.goal]??'unknown',access:plan?.access_mode??null,
        raw:saved.filter(version=>version.raw_artifact_id).length,text:saved.filter(version=>version.extracted_artifact_id).length,evidence:quotes.length,
        state:observation?.goal_result?.state??'unknown',reason:observation?.goal_result?.reason??observation?.goal_result?.detail??null,
        notes:observation?.coverage_notes??[],versions:saved,evidenceIds:quotes.map(item=>item.evidence_id)}
    })
    const requirement=requirements.find(item=>item.channel===channel)
    return {channel,records,disposition:requirement?.disposition??null,rationale:requirement?.rationale??null,
      status:records.some(row=>row.state==='not_met')?'failed':records.length&&records.every(row=>row.state==='met')?'passed':records.length?'recordedUnchecked':requirement?.disposition==='excluded'?'wfExcluded':'wfNotConnected'}
  })
  const stages=researchStages(detail??{}),gates=currentGates(detail)
  const gateStatus=(keys,recorded)=>{
    const matches=gates.filter(g=>keys.includes(g.gate_id))
    return !recorded?'waiting':matches.some(g=>g.state==='failed')?'needsWork':matches.length===keys.length&&matches.every(g=>g.state==='passed')?'passed':'recordedUnchecked'
  }
  const searches=events.filter(event=>event.kind==='search_completed')
  const processing=versions.filter(version=>version.extracted_artifact_id)
  const nodes=[
    {id:'sources',title:'wfSources',icon:'globe-outline',x:24,y:24,w:248,h:248,status:gateStatus(['research_scope','research_standard'],sources.length),count:sources.length,unit:'countSources',groups},
    {id:'acquire',title:'wfAcquire',icon:'search-outline',x:320,y:24,w:248,h:248,status:stages[0].status,count:versions.length,unit:'wfVersions',groups},
    {id:'process',title:'wfProcess',icon:'layers-outline',x:616,y:24,w:248,h:248,status:processing.length?'done':'waiting',count:processing.length,unit:'wfDocuments',groups},
    {id:'evidence',title:'stageEvidence',icon:'layers-outline',x:912,y:24,w:248,h:248,status:stages[1].status,count:evidence.length,unit:'countEvidence'},
    {id:'analysis',title:'wfAnalysis',icon:'sparkle',x:912,y:352,w:248,h:144,status:stages[2].status,count:detail?.analysis?.claims?.length??0,unit:'countClaims'},
    {id:'review',title:'wfReview',icon:'check-outline',x:616,y:352,w:248,h:144,status:stages[3].status,count:detail?.verification?.checks?.length??0,unit:'wfChecks'},
    {id:'deliver',title:'wfDeliver',icon:'download-outline',x:320,y:352,w:248,h:144,status:detail?.delivery?'wfArchived':'waiting',count:detail?.delivery?.files?.length??0,unit:'wfFiles'},
  ]
  const paths=['M272 148C288 148 304 148 320 148','M568 148C584 148 600 148 616 148','M864 148C880 148 896 148 912 148','M1036 272C1036 304 1036 320 1036 352','M912 424C896 424 880 424 864 424','M616 424C600 424 584 424 568 424']
  const revisions={acquire:versions.map(v=>v.version_id).join('|'),process:processing.map(v=>v.extracted_artifact_id).join('|'),evidence:evidence.map(item=>item.evidence_id).join('|'),analysis:detail?.analysis_fingerprint,review:detail?.verification?.execution_ref,deliver:detail?.delivery?detail.delivery.path+'|'+(detail.delivery.createdAt??''):null}
  const labels=[[296,132],[592,132],[888,132],[1060,316],[888,408],[592,408]]
  const edges=nodes.slice(1).map((node,i)=>({from:nodes[i].id,to:node.id,path:paths[i],count:node.count,unit:node.unit,label:labels[i],revision:revisions[node.id]}))
  const sessionLogs=(state?.events??[]).map((event,index)=>({...event,id:event.id??'legacy:'+index,kind:event.action,scope:'wfSessionLog',time:event.startedAt??event.finishedAt}))
  const logs=[...events.map(event=>({id:'engine:'+detail.run.run_id+':'+event.sequence,engineSequence:event.sequence,runId:detail.run.run_id,scope:'wfBatchLog',kind:event.kind,time:event.created_at??event.at??event.time,message:event.payload?.message??event.payload?.detail??event.payload?.error??event.payload?.code??null,payload:event.payload})),
    ...sessionLogs.filter(event=>event.runId===detail?.run?.run_id&&event.runId)].sort((a,b)=>(Date.parse(a.time??'')||0)-(Date.parse(b.time??'')||0)).reverse()
  return {nodes,edges,groups,logs,sessionLogs,searches:searches.length,sourceCount:sources.length,evidenceCount:evidence.length,claims:detail?.analysis?.claims?.length??0,
    current:state?.current??null,failedChecks:gates.filter(g=>g.state==='failed'),hasRun:!!detail,runId:detail?.run.run_id??null}
}

/** Animate only new records in the same run; initial load and batch switches remain static.
 * @param previous Previously displayed model.
 * @param current New snapshot model for comparison.
 * @returns Edges with newly saved data or changed artifact references.
 */
export function workflowTransfers(previous,current) {
  if(!previous||!current.runId||previous.runId!==current.runId)return []
  const edges=current.edges.flatMap(edge=>{
    const before=previous.edges.find(item=>item.to===edge.to)
    if(!before)return []
    if(edge.count>before.count)return [{...edge,delta:edge.count-before.count}]
    return before.revision&&edge.revision&&before.revision!==edge.revision?[{...edge,delta:0,updated:true}]:[]
  })
  const branches=current.groups.flatMap(group=>{
    const before=previous.groups.find(item=>item.channel===group.channel)
    if(!before)return []
    return [['acquire','raw'],['process','text']].flatMap(([to,key])=>{
      const delta=group.records.reduce((sum,row)=>sum+row[key],0)-before.records.reduce((sum,row)=>sum+row[key],0)
      return delta>0?[{to,channel:group.channel,delta}]:[]
    })
  })
  return [...edges,...branches]
}
