/** Group linked quotations by source and relation without hiding individual evidence records. */
import React,{useState} from 'react'
import {references,sourceTitle} from './model.js'
import {useT} from './locales.js'
import {CitationReader} from './citation-reader.jsx'

/** Render source disclosures whose quotations open the exact evidence in the selected batch. */
export function EvidenceLinks({links,detail,onInspect,sessionId,openInitially=false}){
 const t=useT(),refs=references(detail),groups=new Map(),seen=new Set()
 for(const link of links??[]){
  const key=link.evidence_id+':'+(link.relation??'')
  if(seen.has(key))continue
  seen.add(key)
  const evidence=detail.evidence?.find(item=>item.evidence_id===link.evidence_id)
  const ref=refs.find(item=>item.evidence.some(quote=>quote.evidence_id===link.evidence_id))
  const groupKey=(ref?.source.source_id??link.evidence_id)+':'+(link.relation??'')
  if(!groups.has(groupKey))groups.set(groupKey,{ref,relation:link.relation,items:[]})
  groups.get(groupKey).items.push({id:link.evidence_id,evidence})
 }
 return <div className="tech-evidence-groups">{[...groups].map(([key,group])=><EvidenceGroup key={key} group={group} detail={detail} onInspect={onInspect} sessionId={sessionId} openInitially={openInitially}/>)}</div>
}

function EvidenceGroup({group,detail,onInspect,sessionId,openInitially}){
 const t=useT(),[open,setOpen]=useState(openInitially)
 const versions=[...new Set(group.items.map(item=>item.evidence?.source_version_id).filter(Boolean))]
 return <details className="tech-evidence-group" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary>{group.relation&&<span className="tech-evidence-relation">{t(group.relation)}</span>}<span className="tech-evidence-title">{group.ref?`[${group.ref.number}] ${sourceTitle(group.ref.source)}`:t('evidenceSourceMissing')}</span><span className="tech-evidence-count">{group.items.length} {t('countEvidence')}</span></summary>
  {open&&versions.map(version=><CitationReader key={version} items={group.items.filter(item=>item.evidence?.source_version_id===version).map(item=>item.evidence)} sessionId={sessionId} runId={detail.run.run_id} versionId={version} onInspect={onInspect} source={group.ref?.source}/>)}
  {group.items.filter(item=>!item.evidence).map(item=><p key={item.id} role="alert">{t('evidenceRecordMissing')} <code>{item.id}</code></p>)}
 </details>
}
