/** Resolve short quotations to complete saved-source sentences without extending what was cited. */

/** Return complete source sentences with exact quoted spans and their evidence IDs. */
export function citationSentences(document,evidence){
 const positions=new Map();let text=''
 for(const unit of document.units){positions.set(unit.index,{start:text.length,text:unit.text,kind:unit.kind});text+=unit.text.replace(/[\r\n]/g,' ')+' '}
 const ranges=[],unresolved=[]
 for(const item of evidence){
  const unit=positions.get(item.locator?.unit_index)
  if(!unit){unresolved.push(item);continue}
  const start=item.locator?.char_start==null?unit.text.indexOf(item.quote):Array.from(unit.text).slice(0,item.locator.char_start).join('').length
  const end=item.locator?.char_end==null?start+item.quote.length:Array.from(unit.text).slice(0,item.locator.char_end).join('').length
  if(start<0||end!==start+item.quote.length||unit.text.slice(start,end)!==item.quote){unresolved.push(item);continue}
  ranges.push({start:unit.start+start,end:unit.start+start+item.quote.length,id:item.evidence_id,unit:item.locator.unit_index})
 }
 const segmenter=new Intl.Segmenter(undefined,{granularity:'sentence'}),sentences=[]
 for(const segment of segmenter.segment(text)){
  const start=segment.index,end=start+segment.segment.length,linked=ranges.filter(range=>range.start<end&&range.end>start)
  if(!linked.length)continue
  const cuts=[...new Set([start,end,...linked.flatMap(range=>[Math.max(start,range.start),Math.min(end,range.end)])])].sort((a,b)=>a-b)
  const parts=cuts.slice(0,-1).map((position,index)=>({text:text.slice(position,cuts[index+1]),quoted:linked.some(range=>range.start<cuts[index+1]&&range.end>position)}))
  sentences.push({parts,evidence_ids:[...new Set(linked.map(range=>range.id))],unit_index:linked[0].unit})
 }
 return {sentences,unresolved}
}
