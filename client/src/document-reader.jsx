/** Read extracted source text on demand without starting or resuming research. */
import React,{useEffect,useState} from 'react'
import {useT} from './locales.js'
import {documentSentences} from './document-text.js'
import {Interpretation} from './interpretation.jsx'
import {VideoPlayer} from './video-player.jsx'

export function DocumentReader({sessionId,runId,versionId,source}){
 const t=useT(),[open,setOpen]=useState(false),[document,setDocument]=useState(null),[error,setError]=useState(null),[retry,setRetry]=useState(0),[page,setPage]=useState(0),[mode,setMode]=useState('sentences')
 useEffect(()=>{
  if(!open)return
  const controller=new AbortController()
  setError(null);setDocument(null);setPage(0)
  fetch('/deep-insight/document?session='+encodeURIComponent(sessionId)+'&run='+encodeURIComponent(runId)+'&version='+encodeURIComponent(versionId),{signal:controller.signal,cache:'no-store'})
   .then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.error?.message??`HTTP ${response.status}`);return value})
   .then(value=>{if(!controller.signal.aborted)setDocument(value)},failure=>{if(!controller.signal.aborted)setError(failure.message)})
  return()=>controller.abort()
 },[open,sessionId,runId,versionId,retry])
 return <><VideoPlayer resource={source?.resource_uri}/><details className="tech-source-document" open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>{t('techReadText')}</summary>{open&&<>
  {!document&&!error&&<p role="status">{t('loading')}</p>}{error&&<div role="alert"><p>{error}</p><button onClick={()=>setRetry(value=>value+1)}>{t('refresh')}</button></div>}
  {document&&<>{document.warnings?.map((warning,index)=><p key={index} className="tech-record-warning">{warning}</p>)}<div className="tech-document-toolbar"><label>{t('readerUnit')} <select aria-label={t('readerUnit')} value={page} onChange={event=>setPage(Number(event.target.value))}>{document.units.map((unit,index)=><option key={unit.index} value={index}>{unit.index} / {document.units.length}</option>)}</select></label><div>{['sentences','page','raw'].filter(value=>value!=='page'||document.units[page]?.kind==='page').map(value=><button key={value} aria-pressed={mode===value} onClick={()=>setMode(value)}>{t('readerMode_'+value)}</button>)}</div></div>{document.units[page]&&<section className="tech-document-unit" key={document.units[page].index}><h4>{t('techTextUnit')} {document.units[page].index}</h4>{mode==='raw'?<pre>{document.units[page].text}</pre>:mode==='page'&&document.units[page].kind==='page'?<OriginalPage sessionId={sessionId} runId={runId} versionId={versionId} unit={document.units[page].index}/>:<><p className="tech-document-note">{t('readerSentenceNote')}</p><ol className="tech-document-sentences">{documentSentences(document.units[page].text).map((item,index)=><li key={index}>{item.kind==='layout'?<details><summary>{t('readerLayoutFragments')}</summary><p>{t('readerLayoutNote')}</p><pre>{item.text}</pre>{document.units[page].kind==='page'&&<button onClick={()=>setMode('page')}>{t('readerMode_page')}</button>}</details>:<p>{item.text}</p>}</li>)}</ol><Interpretation sessionId={sessionId} runId={runId} versionId={versionId} unit={document.units[page].index}/></>}</section>}<div className="tech-document-paging"><button disabled={page===0} onClick={()=>setPage(value=>value-1)}>{t('readerPrevious')}</button><span>{page+1} / {document.units.length}</span><button disabled={page>=document.units.length-1} onClick={()=>setPage(value=>value+1)}>{t('readerNext')}</button></div></>}
 </>}</details></>
}

/** Load only the requested original page; image errors remain visible beside a retry. */
export function OriginalPage({sessionId,runId,versionId,unit}){
 const t=useT(),[image,setImage]=useState(null),[error,setError]=useState(null),[retry,setRetry]=useState(0)
 useEffect(()=>{
  const controller=new AbortController();let objectUrl
  setImage(null);setError(null)
  fetch('/deep-insight/page?session='+encodeURIComponent(sessionId)+'&run='+encodeURIComponent(runId)+'&version='+encodeURIComponent(versionId)+'&unit='+unit,{signal:controller.signal,cache:'no-store'}).then(async response=>{if(!response.ok){const value=await response.json();throw Error(value.error?.message??`HTTP ${response.status}`)}return response.blob()}).then(blob=>{if(!controller.signal.aborted){objectUrl=URL.createObjectURL(blob);setImage(objectUrl)}},failure=>{if(!controller.signal.aborted)setError(failure.message)})
  return()=>{controller.abort();if(objectUrl)URL.revokeObjectURL(objectUrl)}
 },[sessionId,runId,versionId,unit,retry])
 return error?<div role="alert"><p>{t('readerPageError')} {error}</p><button onClick={()=>setRetry(value=>value+1)}>{t('refresh')}</button></div>:image?<a href={image} target="_blank" rel="noopener noreferrer"><img className="tech-original-page" src={image} alt={t('readerOriginalPage')+' '+unit}/><span>{t('readerEnlarge')}</span></a>:<p role="status">{t('loading')}</p>
}
