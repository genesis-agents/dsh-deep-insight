/** Business-stage map over the actual research snapshot; absent capabilities stay explicit. */
import {currentGates} from './model.js'
import {workflowModel} from './workflow-model.js'

/**
 * Map source, artifact and review records to the reference workflow's five business layers.
 * @param detail Selected immutable research batch.
 * @param state Runtime operation and saved activity.
 * @returns Business nodes with their real records and capability limits.
 */
export function businessModel(detail,state){
 const base=workflowModel(detail,state),byId=Object.fromEntries(base.nodes.map(node=>[node.id,node]))
 const current=base.runId&&base.current?.runId===base.runId?base.current:null
 const files=detail?.delivery?.files??[],claims=detail?.analysis?.claims??[],recommendations=detail?.analysis?.narrative?.recommendations??[]
 const node=(id,title,icon,owner,extra={})=>({id,title,icon,owner,status:byId[owner]?.status??'waiting',count:byId[owner]?.count??0,...extra})
 const pending=(id,title,icon,owner)=>{
  const connected=state?.capabilityCatalog?.includes(id),record=detail?.capabilities?.[id]
  const running=current?.action==='enrich'&&(current.capability===id||current.capability==='all')
  const status=!connected?'wfUntracked':running?'wfRunning':record?.stale?'capOutdated':record?.status==='completed'?['entities','structure','trend','benchmark','impact'].includes(id)?'recordedUnchecked':'done':record?.status==='failed'||record?.status==='interrupted'||record?.status==='cancelled'?'failed':'waiting'
  return node(id,title,icon,owner,{status,count:connected?record?.count??0:null,untracked:!connected})
 }
 const media=base.groups.flatMap(group=>group.records).filter(row=>['wfTranscript','wfFrames','wfVideo','wfSlides'].includes(row.goal)&&row.state==='met')
 const sourceNodes=base.groups.map(group=>node('source:'+group.channel,group.channel,group.channel==='opensource'?'code-outline':group.channel==='paper'?'deliver-doc':group.channel==='youtube'?'play-outline':group.channel==='feed'?'flat-list-outline':group.channel==='local'?'folder-open-outline':'globe-outline','sources',{channel:group.channel,count:group.records.length,status:group.status,records:group.records}))
 const lanes=[
  {id:'sources',title:'techSources',subtitle:'techSourcesEn',icon:'database-outline',tone:'purple',nodes:sourceNodes},
  {id:'ingest',title:'techIngest',subtitle:'techIngestEn',icon:'layers-outline',tone:'green',nodes:[node('capture','techCapture','download-outline','acquire'),pending('dedup','techDedup','layers-outline','process'),pending('normalize','techNormalize','deliver-doc','process'),node('extract','techExtract','data-outline','process'),node('quality','techQuality','check-circle-outline','review',{count:currentGates(detail).length,status:base.failedChecks.length?'needsWork':currentGates(detail).length?currentGates(detail).every(gate=>gate.state==='passed')?'passed':'recordedUnchecked':'waiting'})]},
  {id:'understand',title:'techUnderstand',subtitle:'techUnderstandEn',icon:'enhance-outline',tone:'purple',nodes:[node('multimodal','techMultimodal','layers-outline','process',{count:media.length,status:media.length?'done':'waiting'}),pending('entities','techEntities','branch-outline','process'),pending('structure','techStructure','branch-outline','evidence'),node('evidence','stageEvidence','layers-outline','evidence'),pending('vectors','techVectors','database-outline','evidence')]},
  {id:'analysis',title:'techAnalysis',subtitle:'techAnalysisEn',icon:'gauge-outline',tone:'cyan',nodes:[pending('trend','techTrend','gauge-outline','analysis'),pending('benchmark','techBenchmark','compare-split-outline','analysis'),pending('impact','techImpact','goal-outline','analysis'),node('verify','techVerify','checklist-outline','review'),node('synthesis','techSynthesis','sparkle','analysis')]},
  {id:'delivery',title:'techDelivery',subtitle:'techDeliveryEn',icon:'archive-check-outline',tone:'gold',nodes:[node('report','techReport','deliver-doc','deliver',{count:detail?.analysis?1:0,status:detail?.delivery?'wfArchived':detail?.analysis?'recordedUnchecked':'waiting'}),node('slides','techSlides','deliver-doc','deliver',{count:files.filter(file=>/\.pptx$/i.test(file.path)).length,status:files.some(file=>/\.pptx$/i.test(file.path))?'wfArchived':'waiting'}),node('recommendations','techRecommendations','goal-outline','analysis',{count:recommendations.length,status:recommendations.length?'done':'waiting'}),pending('knowledge','techKnowledge','database-outline','evidence'),pending('alerts','techAlerts','alarm-clock-outline','sources')]},
 ]
 const special=[node('task','techTask','goal-outline','sources',{count:detail?1:0,status:detail?'done':'waiting'}),node('orchestrator','techOrchestrator','branch-outline','analysis',{count:null,status:current?'wfRunning':detail?.run?.execution_state==='failed'?'failed':detail?.run?.execution_state==='waiting_input'?'wfWaitingInput':detail?.delivery?'wfArchived':base.hasRun?'recordedUnchecked':'waiting'}),node('output','techOutput','deliver-doc','deliver'),
  ...['sources','ingest','understand','analysis','delivery'].map(id=>node('lane:'+id,lanes.find(lane=>lane.id===id).title,lanes.find(lane=>lane.id===id).icon,id==='ingest'?'acquire':id==='understand'?'process':id==='delivery'?'deliver':id)),
  node('agent-search','techSearchRole','search-outline','acquire'),node('agent-analysis','techAnalysisRole','enhance-outline','analysis'),node('agent-review','techReviewRole','check-outline','review'),node('agent-report','techReportRole','deliver-doc','deliver')]
 const gates=detail?currentGates(detail):[],satisfied=gates.filter(gate=>gate.state==='passed').length
 return {...base,current,lanes,nodes:[...special,...lanes.flatMap(lane=>lane.nodes)],files,claims,recommendations,satisfied,totalChecks:gates.length,gates,unavailable:lanes.flatMap(lane=>lane.nodes).filter(node=>node.untracked),byId}
}
