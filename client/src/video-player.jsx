/** Play registered video sources on demand alongside their preserved transcript. */
import React,{useState} from 'react'
import {useT} from './locales.js'
import {videoSource,videoTime} from './video-source.js'

export function VideoPlayer({resource,start=0,positions=[]}){
 const t=useT(),[open,setOpen]=useState(true),[seconds,setSeconds]=useState(start),[failed,setFailed]=useState(false)
 const source=videoSource(resource,seconds)
 if(!source)return null
 const seek=value=>{setSeconds(value);setFailed(false);setOpen(true)}
 return <section className="tech-video-source">
  <div className="tech-document-toolbar"><button onClick={()=>setOpen(value=>!value)}>{t(open?'videoHide':'videoShow')}</button><a href={source.original} target="_blank" rel="noopener noreferrer">{t('videoOriginal')}</a></div>
  {open&&<>{source.kind==='youtube'?<iframe key={seconds} className="tech-video-player" src={source.embed} title={t('videoPlayer')} allow="encrypted-media; fullscreen; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin"/>:<video key={seconds} className="tech-video-player" controls preload="metadata" src={source.embed} onError={()=>setFailed(true)}/>}
  <p className="tech-document-note" role={failed?'alert':undefined}>{t(failed?'videoFailed':'videoExternalNote')}</p></>}
  {positions.length>0&&<div className="tech-video-positions">{[...new Set(positions)].filter(value=>videoTime(value)!==null).map(value=><button key={value} onClick={()=>seek(value)}>{t('videoSeek')} {videoTime(value)}</button>)}</div>}
 </section>
}
