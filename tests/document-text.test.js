import {test} from 'node:test'
import assert from 'node:assert/strict'
import {documentSentences} from '../client/src/document-text.js'

test('extraction line wraps become complete sentence rows without changing the source',()=>{
 const source='The rapid scaling of large language model training requires distributing GPU resources across\nmultiple data center buildings and regions. We refer to such paradigm as scale-across training.\nExperiments show a 64.62% improvement under the stated conditions.\n\n中文第一句话。中文第二句话！'
 const result=documentSentences(source)
 assert.equal(result.filter(item=>item.kind==='sentence').length,5)
 assert.match(result[0].text,/across multiple data center/)
 assert.equal(result[2].text,'Experiments show a 64.62% improvement under the stated conditions.')
 assert.equal(source.includes('across\nmultiple'),true)
})

test('isolated table and diagram labels remain explicitly separate from prose',()=>{
 const source='This paragraph explains the mechanism.\n\n1\n2\nm\nn\nHost\nRTSW\nCTSW\nBuilding p\nAI\nZone 5\n\nThe actual source page preserves the diagram.'
 const result=documentSentences(source),layout=result.find(item=>item.kind==='layout')
 assert.ok(layout)
 assert.match(layout.text,/Host\nRTSW\nCTSW/)
 assert.equal(result.filter(item=>item.kind==='sentence').length,2)
})
