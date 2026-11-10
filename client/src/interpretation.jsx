/** Chinese sentence-by-sentence reading notes, always distinguished from the original evidence. */
import React,{useEffect,useRef,useState} from 'react'
import {useT} from './locales.js'
import {api} from './feed.js'

export function Interpretation({sessionId,runId,versionId,unit,evidenceIds}){
 const t=useT(),[record,setRecord]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(null),controller=useRef(null)
 const evidenceKey=[...(evidenceIds??[])].sort().join('|'),key=versionId+':'+(unit??'')+':'+evidenceKey
 useEffect(()=>{
  const abort=new AbortController();controller.current=abort;setRecord(null);setError(null);setBusy(false)
  const url=new URL('/deep-insight/interpretation',document.baseURI);url.searchParams.set('session',sessionId);url.searchParams.set('run',runId);url.searchParams.set('version',versionId)
  if(unit!=null)url.searchParams.set('unit',String(unit));else for(const id of evidenceKey.split('|').filter(Boolean))url.searchParams.append('evidence',id)
  fetch(url.pathname+url.search,{signal:abort.signal,cache:'no-store'}).then(async response=>{const value=await response.json();if(response.ok)return value.record;throw Error(value.error?.message??`HTTP ${response.status}`)}).then(value=>{if(!abort.signal.aborted&&value)setRecord(value)},failure=>{if(!abort.signal.aborted)setError(failure.message)})
  return()=>abort.abort()
 },[sessionId,runId,key])
 const generate=async()=>{
  setBusy(true);setError(null)
  try{
   const data={kind:'interpret',version:versionId,...unit!=null?{unit}:{evidence_ids:evidenceKey.split('|').filter(Boolean)}}
   const value=await api(sessionId,controller.current.signal,{action:'enrich',runId,data})
   if(!controller.current.signal.aborted)setRecord({id:value.result.record_id,result:value.result.result})
  }catch(failure){if(!controller.current.signal.aborted)setError(failure.message)}finally{if(!controller.current.signal.aborted)setBusy(false)}
 }
 return <section className="tech-interpretation">
  <div className="tech-interpretation-heading"><h4>{t('readerChinese')}</h4>{!record&&<button disabled={busy} onClick={generate}>{t(busy?'readerTranslating':'readerTranslate')}</button>}</div>
  <p className="tech-document-note">{t('readerTranslationNote')}</p>
  {error&&<p role="alert">{error}</p>}
  {record&&<><ol>{record.result.sentences.map(sentence=><li key={sentence.id}><p className="tech-translation-original">{sentence.text}</p><p className="tech-translation-text">{sentence.translation}</p>{sentence.explanation&&<details><summary>{t('readerExplanation')}</summary><p>{sentence.explanation}</p></details>}</li>)}</ol>{record.result.glossary.length>0&&<details><summary>{t('readerGlossary')}</summary><dl>{record.result.glossary.map((entry,index)=><React.Fragment key={index}><dt>{entry.term}</dt><dd>{entry.meaning}</dd></React.Fragment>)}</dl></details>}{record.result.limitations.map((value,index)=><p className="tech-record-warning" key={index}>{value}</p>)}</>}
 </section>
}
