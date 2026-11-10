/** Inline report references resolve only to evidence saved in the selected batch. */
import React,{createContext,useContext} from 'react'
import {references,sourceTitle} from './model.js'
import {useT} from './locales.js'

export const ReportCitationContext=createContext(null)

/** Render explicit quotation markers as numbered links without adding inferred references. */
export function ReportText({text}) {
  const context=useContext(ReportCitationContext),t=useT()
  if(!context||typeof text!=='string')return text
  const {detail,open}=context,parts=[],pattern=/\{\{evidence:([A-Za-z0-9_.-]+)\}\}|ev_[a-f0-9]{32}|\[(\d+)[，,]\s*原文单元\s*(\d+)\]/g
  let end=0
  for(const match of text.matchAll(pattern)){
    parts.push(text.slice(end,match.index))
    const rows=match[2]?references(detail).find(row=>row.number===Number(match[2]))?.evidence.filter(e=>e.locator.unit_index===Number(match[3]))??[]:(detail.evidence??[]).filter(e=>e.evidence_id===(match[1]??match[0]))
    parts.push(rows.length?<sup className="ri-inline-citations" key={match.index}>{rows.map(e=>{
      const number=detail.evidence.findIndex(item=>item.evidence_id===e.evidence_id)+1,reference=references(detail).find(row=>row.evidence.some(item=>item.evidence_id===e.evidence_id))
      return <button type="button" key={e.evidence_id} aria-label={`${t('openEvidence')} ${number}`} title={`${reference?sourceTitle(reference.source):t('evidenceSourceMissing')} · ${t('evidenceUnit')} ${e.locator.unit_index}`} onClick={()=>open({type:'evidence',id:e.evidence_id})}>{number}</button>
    })}</sup>:match[0])
    end=match.index+match[0].length
  }
  parts.push(text.slice(end))
  return <>{parts}</>
}
