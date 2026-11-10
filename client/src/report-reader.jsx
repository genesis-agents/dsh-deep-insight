/** Saved research report with evidence links; rendered from node inspection. */
import React,{useState} from 'react'
import {useT} from './locales.js'
import {references,assetUrl,sourceTitle,dateText} from './model.js'
import {Block} from './blocks.jsx'
import {ReportCitationContext,ReportText} from './report-citations.jsx'
export function Report({detail,sessionId,open}) {
  const t=useT(),a=detail.analysis,n=a?.narrative,[toc,setToc]=useState(false)
  if(!a)return <div className="ri-empty"><h2>{t('noReport')}</h2><p>{t('noReportBody')}</p></div>
  const sections=n?.sections??a.claims.map(c=>({section_id:c.claim_id,question:c.statement,answer:'',claim_ids:[c.claim_id],blocks:[]}))
  return <ReportCitationContext.Provider value={{detail,open}}><article className="ri-report">
    <div className="ri-report-tools"><button aria-expanded={toc} onClick={()=>setToc(!toc)}>{t('contents')}</button>{detail.delivery&&<a href={assetUrl(sessionId,detail.delivery.path+'/report.html')} target="_blank" rel="noopener noreferrer">{t('archived')} ↗</a>}</div>
    {toc&&<nav className="ri-contents" aria-label={t('contents')}><a href="#ri-summary">{t('overview')}</a>{sections.map((s,i)=><a key={s.section_id} href={`#ri-section-${i}`} onClick={()=>setToc(false)}>{String(i+1).padStart(2,'0')}　{s.question}</a>)}<a href="#ri-limitations">{t('limits')}</a></nav>}
    <header className="ri-cover"><div className="ri-eyebrow">{t('report')}</div><h2>{n?.headline??a.title}</h2><p className="ri-standfirst">{<ReportText text={n?.standfirst??a.synthesis}/>}</p></header>
    {a.synthesis!==n?.standfirst&&<section className="ri-executive"><h3>{t('synthesis')}</h3><p>{<ReportText text={a.synthesis}/>}</p></section>}
    <section id="ri-summary"><h3>{t('overview')}</h3><div className="ri-takeaways">{(n?.takeaways??a.claims.slice(0,3).map(c=>({text:c.statement,claim_ids:[c.claim_id]}))).map((item,i)=><div className="ri-takeaway" key={i}><span>{String(i+1).padStart(2,'0')}</span><p>{item.text}</p></div>)}</div></section>
    <details className="ri-method"><summary>{t('notes')}</summary><Scope project={detail.input_snapshot.project}/><p>{t('method')}</p></details>
    {sections.map((s,i)=>{return <section key={s.section_id} id={`ri-section-${i}`} className="ri-chapter"><div className="ri-chapter-title"><span>{String(i+1).padStart(2,'0')}</span><h3>{s.question}</h3></div>{s.answer&&<p className="ri-answer">{<ReportText text={s.answer}/>}</p>}{s.blocks.map((b,j)=><Block key={j} block={b} detail={detail} sessionId={sessionId}/>)}{s.bridge&&<p className="ri-bridge">{<ReportText text={s.bridge}/>}</p>}</section>})}
    {n?.conclusion&&<section id="ri-conclusion" className="ri-conclusion"><h3>{t('conclusion')}</h3><p>{<ReportText text={n.conclusion.text}/>}</p></section>}
    {n?.recommendations?.length>0&&<section className="ri-recommendations"><h3>{t('recommendations')}</h3><ol>{n.recommendations.map((r,i)=><li key={i}><p>{<ReportText text={r.text}/>}</p></li>)}</ol></section>}
    <section id="ri-limitations"><h3>{t('limits')}</h3>{a.limitations.length?<ul>{a.limitations.map((s,i)=><li key={i}>{<ReportText text={s}/>}</li>)}</ul>:<p>{t('limitationsMissing')}</p>}</section>
    <section><h3>{t('references')}</h3><ol className="ri-bibliography">{references(detail).map(r=><li key={r.source.source_id}><button onClick={e=>open({type:'source',id:r.source.source_id},e)}>{sourceTitle(r.source)}</button><span>{r.source.publisher} · {dateText(r.versions.at(-1)?.published_at)??t('undated')}</span></li>)}</ol></section>
  </article></ReportCitationContext.Provider>
}
function Scope({project}) {
  const t=useT(),scope=project?.scope
  return <dl className="ri-scope">{[['decision',project?.decision],['regions',scope?.regions?.join(' / ')],['since',scope?.since],['cutoff',scope?.as_of],['excluded',scope?.exclusions?.join(' / ')]].map(([key,value])=><React.Fragment key={key}><dt>{t(key)}</dt><dd>{value||t('unknown')}</dd></React.Fragment>)}</dl>
}
