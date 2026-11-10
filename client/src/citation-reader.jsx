/** Complete-sentence citation reading with source context and separate exact-location controls. */
import React,{useEffect,useState} from 'react'
import {useT} from './locales.js'
import {citationSentences} from './citation-text.js'
import {Interpretation} from './interpretation.jsx'
import {OriginalPage} from './document-reader.jsx'
import {VideoPlayer} from './video-player.jsx'

/** Load the immutable source only when its citation group is expanded. */
export function CitationReader({items,sessionId,runId,versionId,onInspect,source}){
 const t=useT(),[document,setDocument]=useState(null),[error,setError]=useState(null),[retry,setRetry]=useState(0)
 useEffect(()=>{
  const controller=new AbortController()
  setDocument(null);setError(null)
  fetch('/deep-insight/document?session='+encodeURIComponent(sessionId)+'&run='+encodeURIComponent(runId)+'&version='+encodeURIComponent(versionId),{signal:controller.signal,cache:'no-store'}).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.error?.message??`HTTP ${response.status}`);if(!Array.isArray(value.units))throw Error(t('citationContextMissing'));return value}).then(value=>{if(!controller.signal.aborted)setDocument(value)},failure=>{if(!controller.signal.aborted)setError(failure.message)})
  return()=>controller.abort()
 },[sessionId,runId,versionId,retry])
 const located=document?citationSentences(document,items):null
 const exact=ids=><details className="tech-exact-citations"><summary>{t('citationLocations')} · {ids.length}</summary>{ids.map(id=>{const item=items.find(row=>row.evidence_id===id);return <div key={id}><p>{item.quote}</p><button onClick={()=>onInspect('evidence',runId,id)}>{t('evidenceUnit')} {item.locator?.unit_index??'—'} · {item.locator?.char_start??'—'}–{item.locator?.char_end??'—'}</button></div>})}</details>
 return <div className="tech-citation-reader">
  <VideoPlayer resource={source?.resource_uri} start={items.find(item=>Number.isFinite(item.start_seconds))?.start_seconds??0} positions={items.map(item=>item.start_seconds).filter(Number.isFinite)}/>
  {!document&&!error&&<p role="status">{t('citationLoading')}</p>}
  {error&&<div role="alert"><p>{t('citationContextMissing')} {error}</p><button onClick={()=>setRetry(value=>value+1)}>{t('refresh')}</button></div>}
  {located?.sentences.length>0&&<><p className="tech-citation-note">{t('citationContextNote')}</p><ol>{located.sentences.map((sentence,index)=><li key={index}><blockquote>{sentence.parts.map((part,i)=>part.quoted?<strong key={i}>{part.text}</strong>:<span key={i} className="tech-citation-context">{part.text}</span>)}</blockquote>{exact(sentence.evidence_ids)}</li>)}</ol></>}
  {(located?.unresolved??(error?items:[])).map(item=><div key={item.evidence_id}><p className="tech-record-warning">{t('citationUnresolved')}</p><blockquote>{item.quote}</blockquote>{exact([item.evidence_id])}</div>)}
  {located?.sentences.length>0&&!located.unresolved.length&&<Interpretation sessionId={sessionId} runId={runId} versionId={versionId} evidenceIds={items.map(item=>item.evidence_id)}/>}
  {document&&[...new Set(items.map(item=>item.locator?.unit_index))].filter(index=>document.units.some(unit=>unit.index===index&&unit.kind==='page')).map(index=><CitationPage key={index} sessionId={sessionId} runId={runId} versionId={versionId} unit={index}/>)}
 </div>
}

function CitationPage(props){
 const t=useT(),[open,setOpen]=useState(false)
 return <details onToggle={event=>setOpen(event.currentTarget.open)}><summary>{t('readerMode_page')} · {props.unit}</summary>{open&&<OriginalPage {...props}/>}</details>
}
