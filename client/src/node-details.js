/** Node-specific detail selectors. Stages never reuse unrelated source lists as their results. */
import {businessModel} from './business-model.js'

const legacy={sources:'lane:sources',acquire:'capture',process:'extract',analysis:'synthesis',review:'verify',deliver:'report'}

/**
 * Select each business node's own inputs, operations and saved outputs.
 * @param detail Exact batch selected by the open navigation record.
 * @param state Session feed and runtime operation.
 * @param selection Node id and optional exact evidence/claim/source id.
 * @returns Distinct semantic sections for the selected node.
 */
export function nodeDetails(detail,state,selection){
 const model=businessModel(detail,state),id=legacy[selection?.nodeId]??selection?.nodeId??'orchestrator'
 const node=model.nodes.find(item=>item.id===id)??model.nodes.find(item=>item.id==='orchestrator')
 const all=model.groups.flatMap(group=>group.records),versions=detail?.source_versions??[],project=detail?.input_snapshot?.project
 const claims=model.claims.filter(item=>!selection?.recordId||item.claim_id===selection.recordId)
 const evidence=(detail?.evidence??[]).filter(item=>!selection?.recordId||item.evidence_id===selection.recordId)
 const field=(label,value,valueKey)=>({label,value:value??null,valueKey})
 const section=(title,kind,items=[],note)=>({title,kind,items,note})
 const purpose=node.channel?'techPurpose_source':'techPurpose_'+node.id.replace('lane:','lane_').replace('agent-','agent_')
 const media=all.filter(row=>['wfTranscript','wfFrames','wfVideo','wfSlides'].includes(row.goal))
 const sections=[]
 if(['dedup','normalize','entities','structure','vectors','trend','benchmark','impact','knowledge','alerts'].includes(node.id)){
  sections.push(section('capProduct','capability',[node.id]))
  return {node,sections,purpose,model}
 }
 if(node.channel){
  const group=model.groups.find(item=>item.channel===node.channel)
  const records=(group?.records??[]).filter(item=>!selection?.recordId||item.id===selection.recordId)
  sections.push(section('techChannelScope','fields',[field('techDisposition',group?.disposition,group?.disposition?'techDisposition_'+group.disposition:null),field('techRationale',group?.rationale)]),section('techInput','sources',records,node.channel==='email'?'wfEmailUnavailable':'wfNoInput'))
 }else switch(node.id){
  case 'task':
   sections.push(section('techResearchDefinition','fields',[field('questions',project?.question??state?.binding?.question),field('decision',project?.decision),field('regions',project?.scope?.regions?.join(' · ')),field('cutoff',project?.scope?.as_of),field('excluded',project?.scope?.exclusions?.join(' · '))]),section('questions','text',project?.subquestions??[]),section('techRequirements','channels',model.groups.filter(group=>group.disposition)))
   break
  case 'orchestrator':
   sections.push(section('techExecutionState','fields',[field('techRun',detail?.run?.run_id),field('techCurrentAction',model.current?.action,model.current?'action_'+model.current.action:'wfNoCurrentOperation'),field('techEngineState',detail?.run?.execution_state,detail?.run?.execution_state?'execution_'+detail.run.execution_state:null),field('techEngineStage',detail?.run?.stage,detail?.run?.stage?'stage_'+detail.run.stage:null),field('techModel',detail?.analysis?.producer?.model)]),section('techWaitingReason','text',detail?.run?.waiting_reason?[detail.run.waiting_reason]:[],'wfNoCurrentOperation'),section('quality','gates',model.gates),section('activity','logs',model.logs))
   break
  case 'lane:sources':
   sections.push(section('techRequirements','channels',model.groups),section('techRegisteredSources','sources',all.filter(item=>!selection?.recordId||item.id===selection.recordId)))
   break
  case 'capture':case 'agent-search':case 'lane:ingest':
   sections.push(section('techAcquisitionPlan','plan',all),section('techRawOutputs','versions',versions))
   break
  case 'dedup':{
   const raw=versions.map(item=>item.raw_artifact_id).filter(Boolean),unique=new Set(raw)
   sections.push(section('techDedupInput','fields',[field('techRawCount',raw.length),field('techUniqueArtifacts',unique.size),field('techSharedArtifacts',raw.length-unique.size)]),section('techRawOutputs','versions',versions),section('techOutputs','empty',[],'techNoDedupRecord'))
   break
  }
  case 'normalize':
   sections.push(section('techFormatInput','plan',all),section('techOutputs','empty',[],'techNoNormalizeRecord'))
   break
  case 'extract':
   sections.push(section('techRawInputs','versions',versions),section('techTextOutputs','versions',versions.filter(item=>item.extracted_artifact_id)))
   break
  case 'quality':
   sections.push(section('quality','gates',model.gates))
   break
  case 'multimodal':
   sections.push(section('techMediaInputs','plan',media,'techNoMediaInput'),section('techMediaOutputs','versions',versions.filter(version=>media.some(record=>record.id===version.source_id))))
   break
  case 'lane:understand':
   sections.push(section('techTextOutputs','versions',versions.filter(item=>item.extracted_artifact_id)),section('evidence','evidence',evidence),section('techUnconnectedCapabilities','text',['techEntities','techVectors','techKnowledge']))
   break
  case 'entities':
   sections.push(section('techEntityInput','evidence',evidence),section('techOutputs','empty',[],'techNoEntityRecord'))
   break
  case 'structure':
   sections.push(section('techContextCoverage','coverage',detail?.context?.coverage??[]),section('techOutputs','empty',[],'techNoStructureRecord'))
   break
  case 'vectors':
   sections.push(section('techIndexCandidates','versions',versions.filter(item=>item.extracted_artifact_id)),section('techIndexState','empty',[],'techNoVectorRecord'))
   break
  case 'evidence':
   sections.push(section('evidence','evidence',evidence),section('techContextCoverage','coverage',detail?.context?.coverage??[]))
   break
  case 'trend':
   sections.push(section('techTrendInputs','fields',[field('since',project?.scope?.since),field('cutoff',project?.scope?.as_of),field('regions',project?.scope?.regions?.join(' · '))]),section('techOutputs','empty',[],'techNoTrendRecord'))
   break
  case 'benchmark':
   sections.push(section('techBenchmarkInputs','fields',[field('decision',project?.decision),field('questions',project?.subquestions?.join(' · '))]),section('techOutputs','empty',[],'techNoBenchmarkRecord'))
   break
  case 'impact':
   sections.push(section('techImpactInputs','recommendations',model.recommendations),section('techOutputs','empty',[],'techNoImpactRecord'))
   break
  case 'verify':case 'agent-review':
   sections.push(section('techReviewState','fields',[field('techReviewFreshness',detail?.verification_status,detail?.verification_status?'review_'+detail.verification_status:null)]),section('techReviewedClaims','claims',claims),section('techReviewResults','checks',detail?.verification?.checks??[]))
   break
  case 'synthesis':case 'agent-analysis':case 'lane:analysis':
   sections.push(section('techAnalysisSummary','fields',[field('techHeadline',detail?.analysis?.title),field('synthesis',detail?.analysis?.synthesis)]),section('findings','claims',claims),section('limits','text',detail?.analysis?.limitations??[]))
   break
  case 'report':case 'agent-report':
   sections.push(section('report','report',detail?.analysis?[detail]:[]))
   break
  case 'slides':
   sections.push(section('techSlidesInput','chapters',detail?.analysis?.narrative?.sections??[]),section('techOutputs','files',model.files.filter(file=>/\.pptx$/i.test(file.path)),'techNoSlidesRecord'))
   break
  case 'recommendations':
   sections.push(section('techRecommendations','recommendations',model.recommendations))
   break
  case 'knowledge':
   sections.push(section('techKnowledgeInputs','fields',[field('techTextCount',versions.filter(item=>item.extracted_artifact_id).length),field('techEvidenceCount',evidence.length)]),section('techOutputs','empty',[],'techNoKnowledgeRecord'))
   break
  case 'alerts':
   sections.push(section('techSubscriptionState','empty',[],'techNoAlertRecord'))
   break
  case 'output':case 'lane:delivery':
   sections.push(section('techDeliveryState','fields',[field('techArchivePath',detail?.delivery?.path),field('techArchiveTime',detail?.delivery?.createdAt)]),section('techOutputs','files',model.files),section('techRecommendations','recommendations',model.recommendations))
   break
  default:
   sections.push(section('techDetails','empty',[],'techBatchUnavailable'))
 }
 return {node,sections,purpose,model}
}
