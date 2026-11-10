/** Executable enrichment panels over saved, session-bound results. */
import React,{useEffect,useRef,useState} from 'react'
import {useT} from './locales.js'
import {api} from './feed.js'
import {sourceTitle} from './model.js'
import {EvidenceLinks} from './evidence-links.jsx'
import {documentSentences} from './document-text.js'
import {KnowledgeGraph} from './knowledge-graph.jsx'

export function CapabilityPanel({kind,detail,state,sessionId,onInspect,onRefresh}){
 const t=useT(),summary=detail?.capabilities?.[kind],runId=detail?.run.run_id
 const [record,setRecord]=useState(null),[previousRecord,setPreviousRecord]=useState(null),[error,setError]=useState(null),[busy,setBusy]=useState(false),[query,setQuery]=useState(''),[matches,setMatches]=useState(null),[minutes,setMinutes]=useState(''),[url,setUrl]=useState(''),[keywords,setKeywords]=useState('')
 const request=useRef(null)
 useEffect(()=>()=>request.current?.abort(),[])
 useEffect(()=>{
  if(!summary){setRecord(null);setPreviousRecord(null);return}
  const controller=new AbortController();setError(null);setPreviousRecord(null)
  const read=async id=>{const response=await fetch('/deep-insight/capability?session='+encodeURIComponent(sessionId)+'&run='+encodeURIComponent(runId)+'&id='+encodeURIComponent(id),{signal:controller.signal,cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error?.message??`HTTP ${response.status}`);return value}
  Promise.all([read(summary.id),summary.previousSuccessId?read(summary.previousSuccessId):null]).then(([current,previous])=>{if(!controller.signal.aborted){setRecord(current);setPreviousRecord(previous)}},failure=>{if(!controller.signal.aborted)setError(failure.message)})
  return()=>controller.abort()
 },[sessionId,runId,summary?.id,summary?.status,summary?.finishedAt])
 const run=async(data={kind})=>{
  request.current?.abort();const controller=new AbortController();request.current=controller;setBusy(true);setError(null)
  try{
   const response=await api(sessionId,controller.signal,{action:'enrich',runId,data})
   if(controller.signal.aborted)return
   if(response.result.matches)setMatches(response.result)
   else{
    const read=await fetch('/deep-insight/capability?session='+encodeURIComponent(sessionId)+'&run='+encodeURIComponent(runId)+'&id='+encodeURIComponent(response.result.record_id),{signal:controller.signal,cache:'no-store'})
    const value=await read.json();if(!read.ok)throw Error(value.error?.message??`HTTP ${read.status}`)
    if(!controller.signal.aborted){setRecord(value);setPreviousRecord(null)}
   }
   await onRefresh()
  }catch(failure){if(!controller.signal.aborted)setError(failure.message)}finally{if(!controller.signal.aborted)setBusy(false)}
 }
 const pending=busy||!!state?.current,available=state?.capabilityCatalog?.includes(kind),displayed=previousRecord??record,result=displayed?.status==='completed'?displayed.result:null
 const sources=detail?.input_snapshot?.sources??[],title=id=>sourceTitle(sources.find(item=>item.source_id===id))
 const evidence=ids=><EvidenceLinks links={ids.map(evidence_id=>({evidence_id}))} detail={detail} sessionId={sessionId} onInspect={onInspect}/>
 return <section className="tech-capability-panel">
  <div className="tech-capability-controls">{kind!=='alerts'&&<button disabled={!runId||!available||pending} onClick={()=>run()}>{t(busy?'capRunning':state?.current?'capWaiting':summary?'capRunAgain':'capRun')}</button>}<span>{t('capSavedSeparately')}</span></div>
  {!available&&<p className="tech-record-warning">{t('capBackendUnavailable')}</p>}
  {summary?.stale&&<p className="tech-record-warning">{t('capStale')}</p>}
  {error&&<p role="alert">{error}</p>}
  {record?.error&&<p role="alert">{record.error.message}</p>}
  {result&&summary&&summary.status!=='completed'&&<p className="tech-record-warning">{t('capPreviousResult')}</p>}
  {kind==='alerts'&&<><div className="tech-capability-form"><label>{t('capMonitorSource')}<select value={url} onChange={event=>setUrl(event.target.value)}><option value="">{t('capChooseSource')}</option>{sources.filter(source=>/^https?:\/\//i.test(source.resource_uri??'')).map(source=><option key={source.source_id} value={source.resource_uri}>{sourceTitle(source)}</option>)}</select></label><label>{t('capIntervalMinutes')}<input type="number" min="1" step="1" value={minutes} onChange={event=>setMinutes(event.target.value)}/></label><label>{t('capMonitorKeywords')}<input value={keywords} onChange={event=>setKeywords(event.target.value)}/></label></div><button disabled={pending||!available||!url||!Number.isSafeInteger(Number(minutes))||Number(minutes)<1} onClick={()=>run({kind,urls:[url],keywords:keywords.split(/[,，]/).map(value=>value.trim()).filter(Boolean),timing:{kind:'every',every_seconds:Number(minutes)*60}})}>{t('capSubscribe')}</button>{result?.schedule&&<div className="tech-capability-controls"><button disabled={pending} onClick={()=>run({kind,mode:'check'})}>{t('capCheckNow')}</button><button disabled={pending} onClick={()=>run({kind,mode:(displayed.liveSchedule?.status??result.schedule.status)==='active'?'pause':'resume'})}>{t((displayed.liveSchedule?.status??result.schedule.status)==='active'?'capPause':'capResume')}</button></div>}</>}
  {!record&&!summary&&<p>{t('capNoResult')}</p>}
  {result&&kind==='dedup'&&<><dl><dt>{t('capDocuments')}</dt><dd>{result.documents}</dd><dt>{t('capUniqueOriginals')}</dt><dd>{result.unique_originals}</dd><dt>{t('capUniqueTexts')}</dt><dd>{result.unique_texts}</dd></dl>{result.groups.length?result.groups.map((group,index)=><article key={index}><h4>{t(group.match==='original'?'capSameOriginal':'capSameText')} · {group.members.length}</h4><ul>{group.members.map(member=><li key={member.source_version_id}><button onClick={()=>onInspect('lane:sources',runId,member.source_id)}>{title(member.source_id)}</button></li>)}</ul></article>):<p>{t('capNoDuplicates')}</p>}<p className="tech-document-note">{t('capDedupNote')}</p></>}
  {result&&kind==='normalize'&&result.documents.map(document=><details key={document.source_version_id}><summary>{title(document.source_id)} · {document.units.length} {t('capTextUnits')}</summary><p>{t('capNormalizationNote')}</p>{document.units.map(unit=><details key={unit.index}><summary>{t('techTextUnit')} {unit.index} · {unit.original_characters} → {unit.normalized_characters}</summary><ol className="tech-document-sentences">{documentSentences(unit.text).map((item,index)=><li key={index}><p>{item.text}</p></li>)}</ol></details>)}</details>)}
  {result&&kind==='entities'&&<>{result.entities.map((entity,index)=><article key={index}><h4>{entity.name} · {entity.category}</h4>{entity.aliases.length>0&&<p>{t('capAliases')} · {entity.aliases.join('、')}</p>}{evidence(entity.evidence_ids)}</article>)}</>}
  {result&&kind==='structure'&&<KnowledgeGraph key={displayed.id} result={result} detail={detail} sessionId={sessionId} onInspect={onInspect}/>}
  {result&&kind==='trend'&&<><p>{result.conclusion}</p>{[...result.signals].sort((a,b)=>a.date.localeCompare(b.date)).map((signal,index)=><article key={index}><h4>{signal.date} · {signal.dimension}</h4><p>{t('capDate_'+signal.date_basis)} · {t('capDirection_'+signal.direction)}</p><p>{signal.statement}</p>{evidence(signal.evidence_ids)}</article>)}</>}
  {result&&kind==='benchmark'&&<div className="ri-table-scroll"><table><caption>{t('capComparison')}</caption><thead><tr><th>{t('capSubject')}</th>{result.dimensions.map(dimension=><th key={dimension}>{dimension}</th>)}</tr></thead><tbody>{result.rows.map((row,index)=><tr key={index}><th>{row.subject}</th>{result.dimensions.map(dimension=><td key={dimension}>{row.values.filter(value=>value.dimension===dimension).map((value,i)=><div key={i}><p>{value.value}</p>{value.conditions.map((condition,j)=><p key={j}>{condition}</p>)}{evidence(value.evidence_ids)}</div>)}</td>)}</tr>)}</tbody></table></div>}
  {result&&kind==='impact'&&result.assessments.map((item,index)=><article key={index}><h4>{item.affected_entity} · {t('capDirection_'+item.direction)}</h4><p>{item.mechanism}</p><h4>{t('conditions')}</h4><ul>{item.conditions.map((value,i)=><li key={i}>{value}</li>)}</ul><h4>{t('capNextActions')}</h4><ul>{item.actions.map((value,i)=><li key={i}>{value}</li>)}</ul>{evidence(item.evidence_ids)}</article>)}
  {result&&kind==='vectors'&&<><dl><dt>{t('techModel')}</dt><dd>{result.model}</dd><dt>{t('capDimensions')}</dt><dd>{result.dimensions}</dd><dt>{t('capIndexedChunks')}</dt><dd>{result.chunks}</dd></dl><form className="tech-capability-form" onSubmit={event=>{event.preventDefault();run({kind,query})}}><label>{t('capSemanticQuery')}<input value={query} onChange={event=>setQuery(event.target.value)}/></label><button disabled={pending||!query.trim()||summary?.stale}>{t('capRetrieve')}</button></form>{matches&&<><p className="tech-document-note">{t('capSimilarityNote')}</p><ol>{matches.matches.map((item,index)=><li key={index}><p>{item.text}</p><p>{title(detail.source_versions.find(version=>version.version_id===item.source_version_id)?.source_id)} · {t('techTextUnit')} {item.unit_index} · {item.char_start}–{item.char_end} · {item.score.toFixed(3)}</p><button onClick={()=>onInspect('lane:sources',runId,item.source_id)}>{t('techEvidenceSource')}</button></li>)}</ol></>}</>}
  {result&&kind==='knowledge'&&<><p>{result.documents.length} {t('capDocuments')} · {result.evidence_count} {t('countEvidence')} · {result.claim_count} {t('countClaims')}</p><a href={'/deep-insight/knowledge?session='+encodeURIComponent(sessionId)+'&run='+encodeURIComponent(runId)+'&id='+encodeURIComponent(displayed.id)} download>{t('capExportKnowledge')}</a><ul>{result.documents.map(item=><li key={item.source_version_id}>{title(item.source_id)} · {item.units} {t('capTextUnits')}</li>)}</ul><p>{t('capKnowledgeNote')}</p></>}
  {result&&kind==='alerts'&&<><p>{t('capSubscriptionStatus')} · {t('capSchedule_'+(displayed.liveSchedule?.status??result.schedule.status))}</p>{displayed.liveScheduleError&&<p role="alert">{displayed.liveScheduleError.message}</p>}<p>{t('capNextOccurrence')} · {displayed.liveSchedule?.scheduledAt??result.schedule.scheduledAt??'—'}</p><ul>{result.urls.map(value=><li key={value}>{value}</li>)}</ul><p>{t('capChanges')} · {result.changes.length}</p>{result.changes.map((item,index)=><article key={index}><h4>{item.url}</h4><p>{item.content}</p></article>)}<p className="tech-document-note">{t('capMonitorNote')}</p></>}
  {result?.review_state==='unreviewed'&&<p className="tech-record-warning">{t('capAnalysisUnreviewed')}</p>}
  {result?.limitations?.map((value,index)=><p className="tech-record-warning" key={index}>{value}</p>)}
  {record&&<details><summary>{t('capFullRecord')}</summary><pre className="tech-capability-record">{JSON.stringify(record,null,2)}</pre></details>}
 </section>
}
