/** Reference-led business workflow with real research state and host-owned node inspection. */
import React,{useEffect,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react'
import {Locale,useT} from './locales.js'
import {businessModel} from './business-model.js'
import {workflowTransfers} from './workflow-model.js'
import {assetUrl} from './model.js'
import styles from './tech-workflow.css'
import {nodeDetails} from './node-details.js'
import {Report} from './report-reader.jsx'
import {DocumentReader} from './document-reader.jsx'
import {VideoPlayer} from './video-player.jsx'
import {ActivityLog} from './activity-log.jsx'
import {EvidenceLinks} from './evidence-links.jsx'
import {CapabilityPanel} from './capability-panel.jsx'
import {activityKey} from './presentation.js'
import readerStyles from './research.css'

export function FlowIcon({name,size=24}){return <svg width={size} height={size} aria-hidden="true"><use href={`#dsw-icon-${name}-regular`}/></svg>}
const activeNodes={worker:['capture'],document:['extract'],'source-image':['multimodal'],evidence:['evidence'],context:['evidence'],analysis:['synthesis'],verification:['verify'],review:['verify'],deliver:['report'],search:['capture']}
function Node({node,model,inspect,moving,large=false}){
 const t=useT(),active=model.current?.runId===model.runId&&model.runId&&activeNodes[model.current.action]?.includes(node.id)&&!node.untracked
 const changed=moving.some(edge=>edge.to===node.owner&&(!node.channel||edge.channel===node.channel))
 const status=active?'wfRunning':node.status
 return <button className={'tech-node'+(large?' tech-node-large':'')} data-node={node.id} data-state={status} data-updated={changed} onClick={()=>inspect(node.id)} aria-label={`${t(node.title)} · ${t(status)}`}>
  <span className="tech-node-icon">{node.channel==='x'?<span className="tech-brand-letter">{t('x')}</span>:node.channel==='email'?<span className="tech-brand-letter">@</span>:<FlowIcon name={node.icon}/>}</span><span className="tech-node-name">{t(node.title)}</span><span className="tech-node-meta">{node.count!==null&&<strong>{node.count}</strong>}{t(status)}</span><i className="tech-node-port tech-node-port-in"/><i className="tech-node-port tech-node-port-out"/>
 </button>
}

/** Render the selected batch's business workflow; callbacks open the existing right sidebar. */
export function Workflow({detail,state,sessionId,onInspect,syncError}){
 const t=useT(),model=businessModel(detail,syncError?{...state,current:null}:state),previous=useRef(null),pan=useRef(null),canvas=useRef(null)
 const [moving,setMoving]=useState([]),[scale,setScale]=useState(1)
 const inspect=(id,recordId)=>onInspect(id,model.runId,recordId)
 useEffect(()=>{const changes=syncError?[]:workflowTransfers(previous.current,model);previous.current=model;setMoving(changes);if(!changes.length)return;const timer=setTimeout(()=>setMoving([]),3000);return()=>clearTimeout(timer)},[state,detail,syncError])
 const progress=model.totalChecks?Math.round(model.satisfied/model.totalChecks*100):0
 const nextStep=!detail?.source_versions?.length?'techPendingSources':!model.evidenceCount?'techPendingEvidence':!detail.analysis?'techPendingAnalysis':detail.verification_status!=='current'||model.gates.some(gate=>gate.state!=='passed')?'techPendingReview':!detail.delivery?'techPendingDelivery':'techViewDelivery'
 return <section className="tech-workflow" aria-label={t('workflow')}><style>{styles}</style>
  <div className="tech-view-tools"><span className="tech-live" data-live={!syncError&&!!model.current}><i/>{t(syncError?'wfSyncInterrupted':model.current?'wfOperationActive':model.hasRun?'wfSynced':'wfNotStarted')}</span><div><button aria-label={t('wfZoomOut')} onClick={()=>setScale(value=>Math.max(.8,value-.1))}>−</button><output>{Math.round(scale*100)}%</output><button aria-label={t('wfZoomIn')} onClick={()=>setScale(value=>Math.min(1.2,value+.1))}>+</button><button onClick={()=>setScale(1)}>{t('wfReset')}</button><button onClick={()=>inspect('orchestrator')}>{t('techDetails')}</button></div></div>
  <div className="tech-canvas" style={{zoom:scale}} ref={canvas}>
   <DataRoutes canvas={canvas} model={model} moving={moving} scale={scale}/>
   <div className="tech-hero"><button className="tech-job" onClick={()=>inspect('task')}><span className="tech-job-label"><FlowIcon name="goal-outline" size={18}/>{t('techJob')}</span><h2>{detail?.input_snapshot?.project?.question??state?.binding?.question??t('emptyTitle')}</h2><div className="tech-progress"><span style={{'--tech-progress':progress+'%'}}/><output>{model.totalChecks?`${model.satisfied}/${model.totalChecks}`:'—'}</output></div><small>{t('techChecksProgress')}</small><div className="tech-job-stats">{[[model.sourceCount,'countSources'],[model.evidenceCount,'countEvidence'],[model.claims.length,'countClaims']].map(([count,label])=><span key={label}><strong>{count}</strong>{t(label)}</span>)}</div></button>
    <section className="tech-run-summary"><h2>{t('techRunSummary')}</h2><p className="tech-summary-state">{model.current?t(activityKey(model.current.action)):t(detail?'execution_'+detail.run.execution_state:'wfNotStarted')}</p><p className="tech-summary-note">{t(model.current?'wfOperationActive':'techNoCurrentOperation')}</p><div className="tech-next"><span>{t('techNextStep')}</span><p>{t(nextStep)}</p></div><div className="tech-summary-actions"><button data-node="orchestrator" onClick={()=>inspect('orchestrator')}>{t('techOpenProgress')}</button><button data-node="report" onClick={()=>inspect('report')} disabled={!detail?.analysis}>{t('techOpenReport')}</button></div></section>
   </div>
   <div className="tech-lanes">{model.lanes.map((lane,index)=><section key={lane.id} className="tech-lane" data-tone={lane.tone} data-moving={moving.some(edge=>lane.nodes.some(node=>node.owner===edge.to))}>
     <button className="tech-lane-label" data-node={'lane:'+lane.id} onClick={()=>inspect('lane:'+lane.id)} aria-label={`${t(lane.title)} · ${t('techDetails')}`}><FlowIcon name={lane.icon} size={26}/><span><strong>{String(index+1).padStart(2,'0')} {t(lane.title)}</strong></span></button>
     <div className="tech-stage-scroll" tabIndex={0} aria-label={t(lane.title)} onPointerDown={event=>{if(event.target.closest('button')||event.button!==0)return;pan.current={x:event.clientX,left:event.currentTarget.scrollLeft};event.currentTarget.setPointerCapture(event.pointerId)}} onPointerMove={event=>{if(pan.current)event.currentTarget.scrollLeft=pan.current.left-event.clientX+pan.current.x}} onPointerUp={()=>{pan.current=null}} onPointerCancel={()=>{pan.current=null}}><div className="tech-lane-items">{lane.nodes.map((node,i)=><React.Fragment key={node.id}><Node node={node} model={model} inspect={inspect} moving={moving}/>{lane.id!=='sources'&&i<lane.nodes.length-1&&<span className="tech-lane-connector" data-enabled={!node.untracked&&!lane.nodes[i+1]?.untracked} data-moving={!node.untracked&&!lane.nodes[i+1]?.untracked&&node.count>0&&moving.some(edge=>edge.to===lane.nodes[i+1]?.owner)}/>}</React.Fragment>)}</div></div>
    </section>)}</div>
  </div>
  {model.unavailable.length>0&&<details className="tech-unavailable"><summary>{t('techUnavailable')} · {model.unavailable.length}</summary><p>{t('techUnavailableNote')}</p><div>{model.unavailable.map(node=><button key={node.id} data-node={node.id} onClick={()=>inspect(node.id)}>{t(node.title)}</button>)}</div></details>}
  <div className="tech-bottom"><section><header><FlowIcon name="checklist-outline" size={18}/><h3>{t('activity')}</h3><button onClick={()=>inspect('orchestrator')}>{t('techDetails')} ↗</button></header><ol className="tech-log-list">{model.logs.slice(0,5).map((log,i)=><li key={i}><time>{log.time?new Date(log.time).toLocaleTimeString():'—'}</time><span>{t(activityKey(log.kind))===activityKey(log.kind)?t('activityEngineRecord'):t(activityKey(log.kind))}</span><span>{log.status?t('wfLog_'+log.status):t(log.scope)}</span></li>)}{!model.logs.length&&<li>{t('wfNoLogs')}</li>}</ol></section>
   <section><header><FlowIcon name="sparkle" size={18}/><h3>{t('techCoreInsights')}</h3><button onClick={()=>inspect('synthesis')}>{t('techDetails')} ↗</button></header>{model.claims.length?<ol className="tech-insight-list">{model.claims.slice(0,3).map((claim,i)=><li key={claim.claim_id}><button onClick={()=>inspect('synthesis',claim.claim_id)}><span>{i+1}</span>{claim.statement}<b>›</b></button></li>)}</ol>:<p className="tech-empty">{t('techNoInsights')}</p>}</section>
   <section><header><FlowIcon name="deliver-doc" size={18}/><h3>{t('techOutputs')}</h3><button onClick={()=>inspect('output')}>{t('techDetails')} ↗</button></header><div className="tech-output-list">{model.files.length?model.files.slice(0,3).map(file=><a key={file.path} href={assetUrl(sessionId,detail.delivery.path+'/'+file.path)} target="_blank" rel="noopener noreferrer"><FlowIcon name="deliver-doc" size={28}/><span>{file.path}</span><small>{file.size??''}</small></a>):<p className="tech-empty">{t('techNoOutputs')}</p>}</div></section>
  </div>
  <p className="tech-map-note">{t('techTruthNote')}</p>
 </section>
}

function DataRoutes({canvas,model,moving,scale}){
 const [routes,setRoutes]=useState([])
 useLayoutEffect(()=>{
  const root=canvas.current
  if(!root)return
  const targets={sources:'lane:sources',acquire:'capture',process:'extract',evidence:'evidence',analysis:'synthesis',review:'verify',deliver:'report'}
  const elements=new Map([...root.querySelectorAll('[data-node]')].filter(element=>Object.values(targets).includes(element.dataset.node)).map(element=>[element.dataset.node,element]))
  const measure=()=>{
   const origin=root.getBoundingClientRect(),rects=new Map()
   const rect=id=>{if(!rects.has(id))rects.set(id,elements.get(id)?.getBoundingClientRect());return rects.get(id)}
   const next=model.edges.flatMap(edge=>{
    if(!edge.count)return []
    const from=rect(targets[edge.from]),to=rect(targets[edge.to])
    if(!from?.width||!to?.width)return []
    const x1=(from.x+from.width/2-origin.x)/scale,y1=(from.bottom-origin.y)/scale,x2=(to.x+to.width/2-origin.x)/scale,y2=(to.top-origin.y)/scale
    const sameRow=Math.abs(from.y-to.y)<10,end=sameRow?(to.bottom-origin.y)/scale:y2,bend=sameRow?Math.max(y1,end)+14:(y1+end)/2
    return [{...edge,path:`M${x1},${y1}C${x1},${bend} ${x2},${bend} ${x2},${end}`}]
   })
   setRoutes(current=>current.length===next.length&&current.every((route,index)=>route.path===next[index].path&&route.count===next[index].count)?current:next)
  }
  measure()
  if(typeof ResizeObserver==='undefined'||typeof requestAnimationFrame==='undefined')return
  let frame=null
  const schedule=()=>{if(frame!==null)return;frame=requestAnimationFrame(()=>{frame=null;measure()})}
  const observer=new ResizeObserver(schedule);observer.observe(root)
  const scrollers=[...root.querySelectorAll('.tech-stage-scroll')]
  for(const element of scrollers)element.addEventListener('scroll',schedule,{passive:true})
  return()=>{observer.disconnect();if(frame!==null)cancelAnimationFrame(frame);for(const element of scrollers)element.removeEventListener('scroll',schedule)}
 },[canvas,model.runId,model.sourceCount,model.evidenceCount,model.files.length,model.claims.length,model.byId.acquire.count,model.byId.process.count,model.byId.review.count,scale])
 return <svg className="tech-data-routes" aria-hidden="true">{routes.map(route=>{
   const changed=moving.some(edge=>!edge.channel&&edge.to===route.to)
   return <g key={route.to} data-moving={changed}><path d={route.path}/>{changed&&[0,.35,.7].map((delay,i)=><circle key={i} r="3" opacity="0"><animateMotion path={route.path} dur="1.7s" begin="indefinite" ref={element=>element?.beginElementAt?.(delay)} fill="freeze"/><animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.1;.8;1" dur="1.7s" begin="indefinite" ref={element=>element?.beginElementAt?.(delay)} fill="freeze"/></circle>)}</g>
 })}</svg>
}

const inactiveSubscribe=()=>()=>{}
/** Read node-specific sections from the shared feed; collapsed panes stop subscribing. */
export function StageSidebar({feed,selection,sessionId,t,onInspect,onClose,active}){
 const snapshot=useSyncExternalStore(active===false?inactiveSubscribe:feed.subscribe,feed.getSnapshot)
 return <Locale.Provider value={t}><StageDetails state={snapshot.state} error={snapshot.error} selection={selection} sessionId={sessionId} onInspect={onInspect} onClose={onClose} onRefresh={feed.refresh}/></Locale.Provider>
}
function StageDetails({state,error,selection,sessionId,onInspect,onClose,onRefresh}){
 const t=useT(),body=useRef(null),detail=selection?.runId?state?.details?.find(item=>item.run.run_id===selection.runId):state?.details?.at(-1)
 const resolved=nodeDetails(detail,state,selection),{node,sections}=resolved
 const missing=selection?.runId&&state&&!detail
 useEffect(()=>{body.current?.scrollTo?.({top:0,behavior:'instant'})},[selection?.nodeId,selection?.recordId,selection?.runId])
 return <section className="tech-stage-detail research-app" data-detail-node={node.id} aria-label={t('techDetails')} onKeyDown={event=>{if(event.key==='Escape'&&!event.defaultPrevented){event.stopPropagation();onClose()}}}><style>{readerStyles}</style><style>{styles}</style>
  <header><span className="tech-detail-icon"><FlowIcon name={node.icon} size={28}/></span><div><small>{t('techDetails')}</small><h2>{t(node.title)}</h2></div><div className="tech-detail-actions"><button onClick={onRefresh}>{t('refresh')}</button><button onClick={onClose}>{t('closeDetails')}</button></div></header>
  <div ref={body} className="tech-detail-body" tabIndex={0} role="region" aria-label={t('detailContent')}>
  <div className="tech-detail-context"><span>{t(node.status)}</span>{selection?.runId&&<span>{t('batchLabel')} {state?.details?.findIndex(item=>item.run.run_id===selection.runId)+1||'—'}</span>}{selection?.recordId&&<button onClick={()=>onInspect(selection.nodeId,selection.runId)}>{t('techAllRecords')}</button>}{selection?.recordId&&detail?.analysis&&<button onClick={()=>onInspect('report',selection.runId)}>{t('backToReport')}</button>}</div>
  {error&&<p role="alert">{t('error')} {error}</p>}
  {!state&&!error&&<p role="status">{t('loading')}</p>}
  {missing?<p role="alert">{t('techBatchUnavailable')}</p>:<>{sections.map((section,index)=>{const content=<DetailSection section={section} detail={detail} node={node} sessionId={sessionId} onInspect={onInspect} state={state} onRefresh={onRefresh}/>;return section.title==='techChannelScope'?<details className="tech-detail-scope" key={section.title}><summary>{t(section.title)}</summary>{content}</details>:<section className="tech-detail-section" key={section.title+index}><h3>{t(section.title)}</h3>{content}</section>})}</>}
  </div>
 </section>
}
function DetailSection({section,detail,node,sessionId,onInspect,state,onRefresh}){
 const t=useT(),{kind,items,note}=section
 if(kind==='capability')return <CapabilityPanel key={node.id+':'+detail?.run.run_id} kind={node.id} detail={detail} state={state} sessionId={sessionId} onInspect={onInspect} onRefresh={onRefresh}/>
 if(kind==='fields')return <dl>{items.map(field=><React.Fragment key={field.label}><dt>{t(field.label)}</dt><dd>{field.valueKey?t(field.valueKey):field.value===null||field.value===''?t('unknown'):String(field.value)}</dd></React.Fragment>)}</dl>
 if(kind==='logs')return <ActivityLog key={(detail?.run.run_id??'')+':'+node.id} logs={items} sessionLogs={node.id==='orchestrator'?(state?.events??[]).map((event,index)=>({...event,id:event.id??'legacy:'+index,kind:event.action,scope:'wfSessionLog',time:event.startedAt??event.finishedAt})).reverse():undefined} sessionId={sessionId}/>
 if(!items.length)return <p className={node.untracked?'tech-capability-note':'tech-detail-empty'}>{t(note??(kind==='logs'?'wfNoLogs':'techNoOutputs'))}</p>
 if(kind==='channels')return <div>{items.map(group=><article key={group.channel}><h4>{t(group.channel)} · {group.records.length}</h4><p>{group.rationale??t(group.status)}</p><small>{group.disposition?t('techDisposition_'+group.disposition):t(group.status)}</small></article>)}</div>
 if(kind==='sources'||kind==='plan')return <div>{items.map(record=><SourceRecord key={record.id} record={record} plan={kind==='plan'} detail={detail}/>)}</div>
 if(kind==='versions')return <div>{items.map(version=><article key={version.version_id}><h4>{detail.input_snapshot.sources.find(source=>source.source_id===version.source_id)?.title??version.source_id}</h4><dl><dt>{t('techVersionId')}</dt><dd><code>{version.version_id}</code></dd><dt>{t('wfOriginals')}</dt><dd><code>{version.raw_artifact_id}</code></dd><dt>{t('wfDocuments')}</dt><dd><code>{version.extracted_artifact_id??t('waiting')}</code></dd><dt>{t('acquisitionDate')}</dt><dd>{version.acquired_at??t('unknown')}</dd></dl>{version.extracted_artifact_id&&<DocumentReader sessionId={sessionId} runId={detail.run.run_id} versionId={version.version_id} source={detail.input_snapshot.sources.find(source=>source.source_id===version.source_id)}/>}</article>)}</div>
 if(kind==='evidence')return <div><EvidenceLinks links={items.map(item=>({evidence_id:item.evidence_id}))} detail={detail} sessionId={sessionId} onInspect={onInspect} openInitially={items.length===1}/>{items.length===1&&<><button onClick={()=>onInspect('lane:sources',detail.run.run_id,detail.source_versions.find(version=>version.version_id===items[0].source_version_id)?.source_id)}>{t('techEvidenceSource')}</button><details><summary>{t('citationDiagnostics')}</summary><dl><dt>{t('techEvidenceId')}</dt><dd><code>{items[0].evidence_id}</code></dd><dt>{t('techVersionId')}</dt><dd><code>{items[0].source_version_id}</code></dd><dt>{t('exact')}</dt><dd>{items[0].locator?.unit_index??'—'} · {items[0].locator?.char_start??'—'}–{items[0].locator?.char_end??'—'}</dd></dl></details></>}</div>
 if(kind==='claims')return <div>{items.map(claim=><article key={claim.claim_id}><h4>{claim.statement}</h4><p>{claim.conditions?.join(' · ')}</p><EvidenceLinks links={claim.evidence_links} detail={detail} sessionId={sessionId} onInspect={onInspect}/></article>)}</div>
 if(kind==='coverage')return <div>{items.map((item,i)=><article key={i}><h4>{item.subquestion}</h4><EvidenceLinks links={item.evidence_ids?.map(evidence_id=>({evidence_id}))} detail={detail} sessionId={sessionId} onInspect={onInspect}/>{item.unresolved&&<p className="tech-record-warning">{item.unresolved}</p>}</article>)}</div>
 if(kind==='gates')return <div>{items.map(gate=><article key={gate.gate_id}><h4>{t(gate.gate_id)} · {t(gate.state)}</h4><p>{t(gate.gate_id+'_help')}</p><details><summary>{t('techDiagnostics')}</summary><p>{gate.detail??gate.reason}</p></details></article>)}</div>
 if(kind==='checks')return <div>{items.map((check,i)=><article key={i}><h4>{check.claim_id} · {t(check.verdict)}</h4><p>{check.rationale}</p></article>)}</div>
 if(kind==='recommendations')return <ol>{items.map((item,i)=><li key={i}><p>{item.text}</p><small>{item.claim_ids?.join(' · ')}</small></li>)}</ol>
 if(kind==='chapters')return <ol>{items.map(item=><li key={item.section_id}><h4>{item.question}</h4><p>{item.answer}</p></li>)}</ol>
 if(kind==='files'){const visible=items.filter(file=>/^(report\.(html|md)|[^/]+\.(pptx|pdf|docx|xlsx))$/i.test(file.path)),technical=items.filter(file=>!visible.includes(file));const links=files=>files.map(file=><article key={file.path}><a href={assetUrl(sessionId,detail.delivery.path+'/'+file.path)} target="_blank" rel="noopener noreferrer">{file.path==='report.html'?t('fileReportHtml'):file.path==='report.md'?t('fileReportText'):file.path} ↗</a></article>);return <div>{links(visible)}{technical.length>0&&<details><summary>{t('technicalDetails')} · {technical.length}</summary>{links(technical)}</details>}</div>}
 if(kind==='report')return <Report detail={detail} sessionId={sessionId} open={record=>onInspect(record.type==='claim'?'synthesis':record.type==='source'?'lane:sources':'evidence',detail.run.run_id,record.id)}/>

 return <ul>{items.map((value,i)=><li key={i}>{['techEntities','techVectors','techKnowledge'].includes(value)?t(value):value}</li>)}</ul>
}

function SourceRecord({record,plan,detail}){
 const t=useT(),notes=[...new Set(record.notes??[])];return <article className="tech-source-record"><h4>{record.title}</h4><VideoPlayer resource={record.uri} positions={detail.evidence.filter(item=>detail.source_versions.some(version=>version.source_id===record.id&&version.version_id===item.source_version_id)).map(item=>item.start_seconds).filter(Number.isFinite)}/><p className="tech-record-meta">{record.raw} {t('wfOriginals')} · {record.text} {t('wfDocuments')} · {record.evidence} {t('countEvidence')}</p>{plan&&<dl><dt>{t('techProvider')}</dt><dd>{record.provider}</dd><dt>{t('techAcquisitionGoal')}</dt><dd>{t(record.goal)}</dd><dt>{t('techGoalState')}</dt><dd>{t('techGoal_'+record.state)}</dd></dl>}{record.uri&&<a href={record.uri} target="_blank" rel="noopener noreferrer">{t('original')} ↗</a>}{(record.reason||notes.length>0)&&<details><summary>{t('collectionNotes')}</summary>{record.reason&&<p>{record.reason}</p>}{notes.map((value,i)=><p key={i}>{value}</p>)}</details>}</article>
}
