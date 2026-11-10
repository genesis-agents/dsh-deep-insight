/** Accessible report figures; source images and analytical graphics remain distinct. */
import React from 'react'
import {useT} from './locales.js'
import {assetUrl,sourceTitle,webLink} from './model.js'
import {OriginalPage} from './document-reader.jsx'
import {ReportText} from './report-citations.jsx'
export function Block({block,detail,sessionId}) {
  const t=useT()
  if(block.kind==='paragraph') return <p>{<ReportText text={block.text}/>}</p>
  if(block.kind==='table') return <figure><figcaption>{<ReportText text={block.caption}/>}</figcaption><div className="ri-table-scroll"><table><thead><tr>{block.columns.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{block.rows.map((r,i)=><tr key={i}>{r.cells.map((c,j)=><td key={j}><ReportText text={c}/></td>)}</tr>)}</tbody></table></div></figure>
  if(block.kind==='figure') {
    const figure=detail.delivery?.figures?.find(f=>f.source_version_id===block.source_version_id&&f.unit_index===block.unit_index)
    const captured=(detail.events??[]).find(e=>e.kind==='source_image_archived'&&e.payload?.source_version_id===block.source_version_id&&e.payload?.unit_index===block.unit_index&&e.payload?.image_artifact_id===block.image_artifact_id)?.payload
    const url=figure?assetUrl(sessionId,detail.delivery.path+'/'+figure.path):captured&&assetUrl(sessionId,captured.path)
    const version=detail.source_versions.find(v=>v.version_id===block.source_version_id),source=detail.input_snapshot.sources.find(s=>s.source_id===version?.source_id)
    return <figure className="ri-original">{url?<a href={url} target="_blank" rel="noopener noreferrer"><img src={url} alt={block.caption} loading="lazy"/></a>:version&&!block.image_artifact_id?<OriginalPage sessionId={sessionId} runId={detail.run.run_id} versionId={version.version_id} unit={block.unit_index}/>:<p className="ri-notice">{t('figureMissing')}</p>}<figcaption><span>{t('figure')}</span> · {<ReportText text={block.caption}/>}<p>{<ReportText text={block.explanation}/>}</p>{source&&webLink(source.resource_uri)&&<a href={source.resource_uri} target="_blank" rel="noopener noreferrer">{t('source')}：{sourceTitle(source)}</a>}<p className="ri-muted">{<ReportText text={block.reading_note}/>}</p></figcaption></figure>
  }
  if(block.kind==='chart') {
    const lo=Math.min(0,...block.points.map(p=>p.value)),hi=Math.max(0,...block.points.map(p=>p.value)),span=hi-lo||1
    return <figure><figcaption>{<ReportText text={block.caption}/>} <span>{t('chart')}</span></figcaption>{block.points.map((p,i)=><div className="ri-bar-row" key={i}><span>{p.label}</span><div className="ri-bar-track" role="img" aria-label={`${p.label} ${p.value} ${block.unit}`}><i className="ri-zero" style={{left:`${-lo/span*100}%`}}/><i style={{left:`${(Math.min(0,p.value)-lo)/span*100}%`,width:`${Math.abs(p.value)/span*100}%`}}/></div><span>{p.value} {block.unit}</span></div>)}<p className="ri-muted">{<ReportText text={block.note}/>}</p></figure>
  }
  if(block.kind==='diagram') return <>{(block.nodes??[]).filter(node=>node.detail?.trim()).map(node=><p key={node.node_id}><ReportText text={node.label+'：'+node.detail}/></p>)}</>
  return <p className="ri-notice">{t('unsupported')}: {block.kind}</p>
}
