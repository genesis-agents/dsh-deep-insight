import {test} from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {prepareEngine} from '../scripts/setup-engine.mjs'
import {managedResearchTool} from '../src/managed-tool.js'

test('prepares a verified isolated runtime and refuses to overwrite local engine edits',async t=>{
 const dir=await mkdtemp(join(tmpdir(),'insight-setup-'))
 t.after(()=>rm(dir,{recursive:true,force:true}))
 await assert.rejects(prepareEngine({dir}),{code:'ENOENT'})
 await writeFile(join(dir,'package.json'),'{}\n')
 const target=await prepareEngine({dir})
 assert.match(await readFile(join(target,'pyproject.toml'),'utf8'),/personal-insight-platform/)
 assert.equal(await prepareEngine({dir}),target)
 await writeFile(join(target,'pyproject.toml'),'local edit\n')
 await assert.rejects(prepareEngine({dir}),/local changes/)
 assert.equal(await readFile(join(target,'pyproject.toml'),'utf8'),'local edit\n')
})

test('standard tool uses the protected agent identity and propagates cancellation',async()=>{
 const lifetime=new AbortController(),execution=new AbortController(),calls=[]
 const ctx={get:name=>name==='workingDirectory'?{get:()=>'/real'}:null}
 const agent={sessionId:'session-real',session:{},model:{current:()=>({provider:'test',model:'test'})},ctx:{get:()=>({current:()=> 'read-only'})}}
 const tool=managedResearchTool(ctx,{call:async(...args)=>{calls.push(args);return{ok:true}}},lifetime.signal)
 assert.deepEqual(await tool.execute({action:'guide'},{agent,signal:execution.signal}),{ok:true})
 assert.equal(calls[0][0].sessionId,'session-real')
 assert.equal(calls[0][0].preset,'read-only')
 await assert.rejects(tool.execute({action:'guide',sessionId:'spoof'},{agent,signal:execution.signal}))
 lifetime.abort()
 assert.equal(calls[0][2].aborted,true)
 assert.deepEqual(tool.output.render({}, {ok:true}),[{type:'text',text:'{"ok":true}'}])
})
