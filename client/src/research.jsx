/** One research flow per conversation; details belong to the host right sidebar. */
import React,{useState,useSyncExternalStore} from 'react'
import {Locale} from './locales.js'
import {Workflow,FlowIcon,StageSidebar} from './tech-workflow.jsx'
import readerStyles from './research.css'
import styles from './tech-workflow.css'
import {api} from './feed.js'

/** Render the live workflow and batch selector without an internal tab hierarchy. */
export function ResearchPage({feed,sessionId,t,onInspect}){
 const {state,error}=useSyncExternalStore(feed.subscribe,feed.getSnapshot)
 const [notice,setNotice]=useState('')
 const [opening,setOpening]=useState(false)
 const details=state?.details??[],detail=details.find(item=>item.run.run_id===feed.view.selected)??details.at(-1)
 const openFolder=async()=>{
  try{
   setOpening(true)
   const prepared=await api(sessionId,undefined,{action:'reading-room',runId:detail.run.run_id})
   const response=await fetch('/open-in-app/apps')
   if(!response.ok)throw new Error(t('openError'))
   const {apps}=await response.json(),app=['explorer','finder','filemanager'].find(id=>apps.includes(id))
   if(!app)throw new Error(t('openError'))
   const result=await fetch('/open-in-app/open',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({app,path:prepared.result.projectDirectory})})
   if(!result.ok)throw new Error(t('openError'))
   setNotice('')
  }catch(failure){setNotice(failure.message)}finally{setOpening(false)}
 }
 return <Locale.Provider value={t}><section className="research-app research-tech"><style>{readerStyles}</style><style>{styles}</style>
  <header className="tech-shell-bar"><div className="tech-brand"><FlowIcon name="sparkle" size={26}/>{t('title')}</div><div className="tech-batch-tools"><button disabled={opening||!state?.storage?.created||!detail} onClick={openFolder}><FlowIcon name="folder-open-outline" size={14}/>{t(opening?'preparingWorkspace':'workspace')}</button>{details.length>0&&<select aria-label={t('batch')} value={detail.run.run_id} onChange={event=>feed.chooseRun(event.target.value)}>{details.map((item,index)=><option key={item.run.run_id} value={item.run.run_id}>{t('batchLabel')} {index+1}</option>)}</select>}<button onClick={feed.refresh}>{t('refresh')}</button></div></header>
  {error&&<p role="alert" className="ri-notice">{t(state?'error':'initialLoadError')} <span>{error}</span></p>}
  {notice&&<p role="status" className="ri-notice">{notice}</p>}
  {!state&&!error&&<p role="status">{t('loading')}</p>}
  {state&&<Workflow detail={detail} state={state} sessionId={sessionId} onInspect={onInspect} syncError={error}/>}
 </section></Locale.Provider>
}
/** Legacy research resources open the current batch's saved outputs in the same right pane. */
export function ResearchSidebar({feed,t,sessionId,onInspect,active}){return <StageSidebar feed={feed} t={t} sessionId={sessionId} selection={{nodeId:'output'}} onInspect={onInspect} active={active}/>}
