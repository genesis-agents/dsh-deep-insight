/** Presentation-only sentence segmentation; stored text and evidence coordinates stay unchanged. */

/** Merge extraction line wraps and separate diagram/table fragments from readable sentences. */
export function documentSentences(text){
 const lines=text.replace(/\r\n?/g,'\n').split('\n'),blocks=[]
 let prose=[],fragments=[]
 const flushProse=()=>{if(prose.length){blocks.push({kind:'prose',text:prose.join(' ').replace(/([\p{L}])-\s+([\p{Ll}])/gu,'$1$2')});prose=[]}}
 const flushFragments=()=>{if(fragments.length){if(fragments.length>=3){flushProse();blocks.push({kind:'layout',text:fragments.join('\n')})}else prose.push(...fragments);fragments=[]}}
 for(const value of lines){
  const line=value.trim()
  if(!line){flushFragments();flushProse();continue}
  const short=line.length<=32&&line.split(/\s+/).length<=5&&!/[.!?。！？;；,，]$/.test(line)&&!/[。！？]/.test(line)
  if(short){fragments.push(line);continue}
  flushFragments();prose.push(line)
 }
 flushFragments();flushProse()
 const segmenter=new Intl.Segmenter(undefined,{granularity:'sentence'})
 return blocks.flatMap(block=>block.kind==='layout'?[block]:[...segmenter.segment(block.text)].map(item=>({kind:'sentence',text:item.segment.trim()})).filter(item=>item.text))
}
