import {test} from 'node:test'
import assert from 'node:assert/strict'
import {citationSentences} from '../client/src/citation-text.js'

test('adjacent subtitle quotations become one complete sentence with all five exact references',()=>{
 const parts=['We define scale across as extending','lossless connectivity between campuses','or regions for the purposes of training','an AI model or models between those','locations.']
 const document={units:parts.map((text,index)=>({index:index+81,kind:'transcript_segment',text}))}
 const evidence=parts.map((quote,index)=>({evidence_id:'e'+index,quote,locator:{unit_index:index+81,char_start:0,char_end:quote.length}}))
 const result=citationSentences(document,evidence)
 assert.equal(result.sentences.length,1)
 assert.equal(result.sentences[0].evidence_ids.length,5)
 assert.equal(result.sentences[0].parts.map(part=>part.text).join('').trim(),parts.join(' '))
 assert.equal(result.unresolved.length,0)
})

test('sentence context stays distinct from cited text and mismatches are not silently relocated',()=>{
 const document={units:[{index:1,text:'前置😀内容。这是完整的一个原句。这里是下一句。',kind:'document'}]}
 const evidence=[{evidence_id:'a',quote:'一个',locator:{unit_index:1,char_start:12,char_end:14}}]
 const source=Array.from(document.units[0].text),start=source.join('').indexOf('一个')
 evidence[0].locator.char_start=Array.from(document.units[0].text.slice(0,start)).length
 evidence[0].locator.char_end=evidence[0].locator.char_start+2
 const result=citationSentences(document,evidence)
 assert.equal(result.sentences.length,1)
 assert.equal(result.sentences[0].parts.filter(part=>part.quoted).map(part=>part.text).join(''),'一个')
 assert.match(result.sentences[0].parts.map(part=>part.text).join(''),/这是完整的一个原句/)
 evidence[0].locator.char_start=0
 assert.equal(citationSentences(document,evidence).unresolved.length,1)
})
