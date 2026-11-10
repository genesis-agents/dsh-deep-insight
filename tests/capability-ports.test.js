import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile,access} from 'node:fs/promises'
import {capabilityActor,capabilityPorts} from '../src/capability-ports.js'
import {resolveCapabilityConfig} from '../src/capability-config.js'

test('browser actions resolve the live Session model and permission preset on every invocation',()=>{
 let preset='read-only'
 const agent={session:{},ctx:{get:name=>name==='permissionPresets'?{current:()=>preset}:undefined},model:{current:()=>({provider:'actual-provider',model:'actual-model'})}}
 const ctx={get:name=>name==='agents'?{get:session=>session==='known'?agent:undefined}:name==='workingDirectory'?{get:()=>'/workspace'}:undefined}
 assert.equal(capabilityActor(ctx,'known').preset,'read-only')
 preset='workspace-write'
 assert.equal(capabilityActor(ctx,'known').preset,'workspace-write')
 assert.equal(capabilityActor(ctx,'known').provider,'actual-provider')
 assert.throws(()=>capabilityActor(ctx,'foreign'),error=>error.code==='AGENT_REQUIRED')
})

test('embedding cancellation waits for child exit before removing its request files',async()=>{
 const signal=new AbortController(),lifetime=new AbortController()
 let spawned,releaseExit,request,finish
 const started=new Promise(resolve=>{spawned=resolve}),done=new Promise(resolve=>{finish=resolve}),exited=new Promise(resolve=>{releaseExit=resolve})
 let terminated=false
 const ctx={profileContext:{dir:'/fixture-profile',cwd:process.cwd()},get:()=>undefined,subprocess:{spawn:options=>{
  request=options.argv.at(-2);spawned();options.signal.addEventListener('abort',()=>finish({exitCode:1}),{once:true})
  return {done,collected:{stderr:{readFrom:()=>({text:''})}},terminate:()=>{terminated=true},waitForExit:()=>exited}
 }}}
 const ports=capabilityPorts(ctx,resolveCapabilityConfig({}),lifetime.signal)
 const pending=ports.embed(['passage: fixture text'],signal.signal)
 await started
 assert.deepEqual(JSON.parse(await readFile(request,'utf8')).texts,['passage: fixture text'])
 signal.abort();await Promise.resolve();await Promise.resolve()
 await access(request)
 releaseExit()
 await assert.rejects(pending,error=>error.name==='AbortError')
 assert.equal(terminated,true)
 await assert.rejects(access(request),error=>error.code==='ENOENT')
})
