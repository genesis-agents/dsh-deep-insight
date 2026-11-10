/** Saved quotations render one block per evidence record; original context opens separately. */
import React,{useId,useState} from 'react'
import {useT} from './locales.js'

/**
 * Render the selected records verbatim without fetching or expanding their source documents.
 * @param props Saved evidence, batch identifier and exact-evidence navigation callback.
 * @returns One quote block per evidence record, with explicit expansion for long quotations.
 */
export function CitationReader({items,runId,onInspect}){
 return <div className="tech-citation-reader">{items.map(item=><Quotation key={item.evidence_id} item={item} runId={runId} onInspect={onInspect}/>)}</div>
}

function Quotation({item,runId,onInspect}){
 const t=useT(),[expanded,setExpanded]=useState(false),id=useId()
 const collapsible=item.quote.length>280||item.quote.split('\n').length>4
 return <div className="tech-quotation" data-evidence-id={item.evidence_id}>
  <blockquote id={id} className={collapsible&&!expanded?'tech-quotation-collapsed':undefined}>{item.quote}</blockquote>
  <div className="tech-citation-actions">
   {collapsible&&<button aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(value=>!value)}>{t(expanded?'citationCollapse':'citationExpand')}</button>}
   <button onClick={()=>onInspect('evidence',runId,item.evidence_id)}>{t('openEvidence')}</button>
  </div>
 </div>
}
