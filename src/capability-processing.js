/** Non-destructive text cleanup and duplicate reports over saved document versions. */
import {capabilityHash} from './capability-storage.js'

/** Normalize derived text only; original document text and citation offsets remain unchanged. */
export function normalizeDocuments(documents){
 return {method:'unicode-nfkc-whitespace@1',documents:documents.map(({version,document})=>({source_version_id:version.version_id,source_id:version.source_id,units:document.units.map(unit=>{
  const normalized=unit.text.normalize('NFKC').replace(/\r\n?/g,'\n').replace(/[\t\p{Zs}]+/gu,' ').replace(/ *\n */g,'\n').trim()
  return {index:unit.index,kind:unit.kind,original_characters:Array.from(unit.text).length,normalized_characters:Array.from(normalized).length,changed:normalized!==unit.text,text:normalized,original_sha256:capabilityHash(unit.text)}
 }),warnings:document.warnings??[]})),notice:'Derived text only. Evidence continues to use original text and original character positions.'}
}

/** Report identical originals and identical normalized documents without discarding sources or evidence. */
export function deduplicateDocuments(documents){
 const originals=new Map(),texts=new Map()
 for(const {version,document}of documents){
  const normalized=document.units.map(unit=>unit.text.normalize('NFKC').replace(/\s+/gu,' ').trim()).join('\n')
  for(const [map,key]of [[originals,version.raw_artifact_id],[texts,capabilityHash(normalized)]]){
   if(!map.has(key))map.set(key,[])
   map.get(key).push({source_id:version.source_id,source_version_id:version.version_id})
  }
 }
 const groups=[...originals].filter(([,members])=>members.length>1).map(([artifact_id,members])=>({match:'original',artifact_id,members}))
 groups.push(...[...texts].filter(([,members])=>members.length>1).map(([text_hash,members])=>({match:'normalized_text',text_hash,members})))
 return {method:'exact-artifact-and-normalized-text@1',documents:documents.length,unique_originals:originals.size,unique_texts:texts.size,groups,notice:'Potential duplicate groups do not establish source independence. No original or evidence was deleted.'}
}

/** Preserve Python's Unicode code-point coordinates when chunking originals for retrieval. */
export function documentChunks(documents,characters){
 return documents.flatMap(({version,document})=>document.units.flatMap(unit=>{
  const points=Array.from(unit.text),chunks=[]
  for(let start=0;start<points.length;start+=characters){const text=points.slice(start,start+characters).join('');if(text.trim())chunks.push({source_version_id:version.version_id,source_id:version.source_id,unit_index:unit.index,char_start:start,char_end:Math.min(points.length,start+characters),text})}
  return chunks
 }))
}
