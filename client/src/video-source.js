/** Resolve supported video sources without treating arbitrary pages as embeddable media. */
export function videoSource(resource,seconds=0){
 let url
 try{url=new URL(resource)}catch{return null}
 if(url.protocol!=='https:'&&url.protocol!=='http:')return null
 if(url.username||url.password)return null
 const start=Number.isFinite(seconds)&&seconds>=0?Math.floor(seconds):0
 const host=url.hostname.toLowerCase(),path=url.pathname.split('/').filter(Boolean)
 let id
 if(host==='youtu.be')id=path[0]
 else if(['youtube.com','www.youtube.com','m.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com'].includes(host))id=url.pathname==='/watch'?url.searchParams.get('v'):['embed','shorts','live'].includes(path[0])?path[1]:null
 if(id&&/^[A-Za-z0-9_-]{11}$/.test(id))return {kind:'youtube',embed:`https://www.youtube.com/embed/${id}?start=${start}&playsinline=1&controls=1`,original:`https://www.youtube.com/watch?v=${id}&t=${start}s`}
 if(/\.(mp4|webm|ogv)$/i.test(url.pathname))return {kind:'file',embed:url.href.split('#')[0]+`#t=${start}`,original:url.href}
 return null
}

/** Show recorded temporal positions without inferring times from unit numbers. */
export function videoTime(seconds){
 if(!Number.isFinite(seconds)||seconds<0)return null
 const value=Math.floor(seconds)
 return `${Math.floor(value/60)}:${String(value%60).padStart(2,'0')}`
}
