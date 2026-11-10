/** Complete paged activity history with lazily loaded operation inputs and outputs. */
import React,{useEffect,useState} from 'react'
import {useT} from './locales.js'
import {activityKey} from './presentation.js'

/** Render batch history separately from operations whose older records have no batch identity. */
export function ActivityLog({logs,sessionLogs,sessionId}){
 const t=useT(),[scope,setScope]=useState('batch'),[visible,setVisible]=useState(25),[query,setQuery]=useState('')
 const records=(scope==='session'?sessionLogs:logs)??[]
 const matches=records.filter(log=>[t(activityKey(log.kind)),log.kind,log.message,log.runId,JSON.stringify(log.payload)].join(' ').toLowerCase().includes(query.toLowerCase()))
 return <section className="tech-activity">
  {sessionLogs&&<div className="tech-activity-scope"><button aria-pressed={scope==='batch'} onClick={()=>{setScope('batch');setVisible(25)}}>{t('activityBatch')}</button><button aria-pressed={scope==='session'} onClick={()=>{setScope('session');setVisible(25)}}>{t('activitySession')}</button></div>}
  <label className="tech-log-search">{t('activitySearch')}<input type="search" value={query} onChange={event=>{setQuery(event.target.value);setVisible(25)}}/></label>
  <p className="tech-log-count">{t('activityCount')} {matches.length}{scope==='session'&&' · '+t('activityLegacyScope')}</p>
  <ol className="tech-detail-logs">{matches.slice(0,visible).map((log,index)=><ActivityRecord key={log.id??(log.time??'legacy')+':'+log.kind+':'+index} log={log} sessionId={sessionId}/>)}</ol>
  {!matches.length&&<p>{t('wfNoLogs')}</p>}
  {matches.length>visible&&<button onClick={()=>setVisible(value=>value+25)}>{t('activityLoadMore')} ({matches.length-visible})</button>}
 </section>
}

function ActivityRecord({log,sessionId}){
 const t=useT(),[open,setOpen]=useState(false),[value,setValue]=useState(null),[error,setError]=useState(null),[retry,setRetry]=useState(0)
 useEffect(()=>{
  if(!open||(!log.hasDetails&&!log.engineSequence))return
  const controller=new AbortController()
  setError(null)
  fetch('/deep-insight/activity?session='+encodeURIComponent(sessionId)+(log.engineSequence?'&run='+encodeURIComponent(log.runId)+'&sequence='+log.engineSequence:'&id='+encodeURIComponent(log.id)),{signal:controller.signal,cache:'no-store'})
   .then(async response=>{const record=await response.json();if(!response.ok)throw Error(record.error?.message??`HTTP ${response.status}`);return record})
   .then(record=>{if(!controller.signal.aborted)setValue(record)},failure=>{if(!controller.signal.aborted)setError(failure.message)})
  return()=>controller.abort()
 },[open,log.id,log.status,log.hasDetails,log.engineSequence,log.runId,sessionId,retry])
 const duration=log.finishedAt&&log.startedAt?Math.max(0,Date.parse(log.finishedAt)-Date.parse(log.startedAt)):null
 return <li><details open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary><span>{t(activityKey(log.kind))===activityKey(log.kind)?t('activityEngineRecord'):t(activityKey(log.kind))}</span>{log.status&&<span className="tech-log-status" data-status={log.status}>{t('wfLog_'+log.status)}</span>}<time>{log.time?new Date(log.time).toLocaleString():'—'}</time></summary>
  {log.message&&<p role={log.status==='failed'?'alert':undefined}>{log.message}</p>}
  {open&&<div className="tech-log-record"><dl><dt>{t('activityStarted')}</dt><dd>{log.startedAt?new Date(log.startedAt).toLocaleString():t('activityNotRecorded')}</dd><dt>{t('activityFinished')}</dt><dd>{log.finishedAt?new Date(log.finishedAt).toLocaleString():t(log.status==='running'?'wfRunning':'activityNotRecorded')}</dd><dt>{t('activityDuration')}</dt><dd>{duration===null?t('activityNotRecorded'):(duration/1000).toLocaleString()+' s'}</dd><dt>{t('techRun')}</dt><dd>{log.runId??t(log.scope==='wfBatchLog'?'activityThisBatch':'activityNotRecorded')}</dd></dl>
   {log.hasDetails||log.engineSequence?<>{!value&&!error&&<p role="status">{t('loading')}</p>}{error&&<div role="alert"><p>{error}</p><button onClick={()=>setRetry(count=>count+1)}>{t('refresh')}</button></div>}{value&&log.engineSequence?<pre>{JSON.stringify(value,null,2)}</pre>:value&&<><h4>{t('activityInput')}</h4><pre>{JSON.stringify(value.input,null,2)}</pre><h4>{t(value.error?'activityFailure':'activityResult')}</h4><pre>{JSON.stringify(value.error??value.result,null,2)??t('activityNotRecorded')}</pre></>}</>:<><p>{t(log.scope==='wfBatchLog'?'activityEngineRecord':'activityLegacyMissing')}</p><pre>{JSON.stringify(log.payload??log,null,2)}</pre></>}
  </div>}
 </details></li>
}
