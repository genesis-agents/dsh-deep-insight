import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Research } from '../src/research.js'
import { mkdtemp, mkdir, writeFile, readFile, realpath, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

test('project folders are generated for the selected session run and cannot be opened for another run', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'insight-project-folder-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  const projectDirectory = join(workspace, '01-研究项目', 'selected-project')
  let generations = 0
  const research = new Research({ dir: '/profile', cwd: '/code' }, {})
  research.settings = async () => ({ workspace, engineRoot: '/engine' })
  research.readSnapshot = async () => ({ details: [{ run: { run_id: 'selected-run' }, input_snapshot: { project: { project_id: 'selected-project' } } }] })
  research.invoke = async (_settings, argv) => {
    assert.deepEqual(argv, ['reading-room'])
    generations++
    await mkdir(projectDirectory, { recursive: true })
    return { research_state_changed: false }
  }
  const actor = { sessionId: 'selected-session', preset: 'workspace-write' }
  const signal = new AbortController().signal
  const result = await research.execute(actor, { action: 'reading-room', runId: 'selected-run' }, signal)
  assert.equal(result.projectDirectory, await realpath(projectDirectory))
  assert.equal(result.research_state_changed, false)
  await assert.rejects(research.execute(actor, { action: 'reading-room', runId: 'another-run' }, signal), error => error.code === 'RUN_NOT_FOUND')
  await assert.rejects(research.call({ ...actor, preset: 'read-only' }, { action: 'reading-room', runId: 'selected-run' }, signal), error => error.code === 'READ_ONLY')
  assert.equal(generations, 1)
})

test('delivery assets follow the selected run and reject a mismatched manifest', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'insight-delivery-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  const output = join(workspace, 'outputs'), delivery = join(output, 'batch-one')
  await mkdir(delivery, { recursive: true })
  await writeFile(join(workspace, 'conversation.json'), JSON.stringify({ question: 'Fixture only' }))
  const manifest = { run_id: 'one', created_at: '2026-11-06', figure_provenance: [{ source_version_id: 'version-one', unit_index: 2, path: 'figures/page.png' }], files: [] }
  await writeFile(join(delivery, 'manifest.json'), JSON.stringify(manifest))
  const research = new Research({ dir: '/profile', cwd: '/code' }, { run: async () => ({ runs: [{ run_id: 'one' }], details: [{ run: { run_id: 'one', delivery_ref: 'batch-one' } }], storage: { data_root: workspace, outputs: output } }) })
  research.settings = async () => ({ engineRoot: '/engine', workspace })
  const snapshot = await research.readSnapshot('fixture', new AbortController().signal)
  assert.equal(snapshot.details[0].delivery.path, 'outputs/batch-one')
  assert.equal(snapshot.details[0].delivery.figures[0].source_version_id, 'version-one')
  await writeFile(join(delivery, 'manifest.json'), JSON.stringify({ ...manifest, run_id: 'another-run' }))
  await assert.rejects(research.readSnapshot('fixture', new AbortController().signal), error => error.code === 'DELIVERY_MISMATCH')
})

test('snapshot readers share in-flight work and mutations invalidate cached state', async () => {
  const research = new Research({ dir: '/cache-profile', cwd: '/code' }, {})
  let reads = 0, release
  const gate = new Promise(resolve => { release = resolve })
  research.readSnapshot = async sessionId => { reads++; await gate; return { sessionId, runs: [] } }
  const signal = new AbortController().signal
  const first = research.snapshot('one', signal), second = research.snapshot('one', signal)
  release()
  assert.equal((await first).sessionId, 'one')
  await second
  await research.snapshot('one', signal)
  assert.equal(reads, 1)
  research.execute = async () => ({ saved: true })
  research.record = async () => {}
  await research.call({ sessionId: 'one', preset: 'workspace-write' }, { action: 'project' }, signal)
  await research.snapshot('one', signal)
  assert.equal(reads, 2)
})

test('original-page previews only use evidence-linked PDFs in the session and reuse rendered files', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'insight-preview-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  await mkdir(join(workspace, 'delivery', 'materials'), { recursive: true })
  await writeFile(join(workspace, 'delivery', 'materials', 'raw.pdf'), 'PDF fixture')
  let renders = 0
  const research = new Research({ dir: '/profile', cwd: '/code' }, { run: async (_cwd, argv) => { renders++; await writeFile(argv.at(-2), 'PNG fixture'); return { rendered: true } } })
  research.settings = async () => ({ workspace, engineRoot: '/engine' })
  research.snapshot = async () => ({ details: [{ run: { run_id: 'one' }, delivery: { path: 'delivery', files: [{ path: 'materials/raw.pdf' }] }, source_versions: [{ version_id: 'v1', raw_artifact_id: 'raw' }], evidence: [{ evidence_id: 'e1', source_version_id: 'v1', locator: { unit_index: 2 }, quote: 'Fixture quote' }] }] })
  const signal = new AbortController().signal
  const [result, duplicate] = await Promise.all([research.illustrations('session', 'one', signal), research.illustrations('session', 'one', signal)])
  assert.deepEqual(duplicate, result)
  assert.equal(research.previews.size, 0)
  assert.equal(result.figures[0].unit_index, 2)
  assert.equal(result.figures[0].evidence_id, 'e1')
  await research.illustrations('session', 'one', signal)
  assert.equal(renders, 1)
  await assert.rejects(research.illustrations('session', 'another-run', signal), error => error.code === 'RUN_NOT_FOUND')
})

test('research workspaces isolate sessions and profiles and reject model writes in read-only mode', async () => {
  const a = new Research({ dir: '/profile-a', cwd: '/code' }, { run() { throw new Error('Must not execute') } })
  const b = new Research({ dir: '/profile-b', cwd: '/code' }, {})
  assert.notEqual(a.workspace('one'), a.workspace('two'))
  assert.notEqual(a.workspace('one'), b.workspace('one'))
  assert.throws(() => a.workspace('../escape'), /标识/)
  await assert.rejects(a.call({ sessionId: 'one', preset: 'read-only' }, { action: 'project', data: {} }, new AbortController().signal), error => error.code === 'READ_ONLY')
  await assert.rejects(a.call({ sessionId: 'one', preset: 'read-only' }, { action: 'quality' }, new AbortController().signal), error => error.code === 'READ_ONLY')
})

test('text reports do not need decorative charts to reach engine validation', async () => {
  const research = new Research({dir:'/profile',cwd:'/code'}, {})
  let writes=0
  research.execute=async()=>{writes++;return {accepted:true}}
  research.record=async()=>{}
  await research.call({sessionId:'text-report',preset:'workspace-write'}, {action:'analysis',data:{narrative:{sections:[{blocks:[{kind:'paragraph',text:'Evidence-led prose'}]}]}}},new AbortController().signal)
  assert.equal(writes,1)
})

test('operations preserve exact batch identity in running and completed records', async () => {
  const research = new Research({ dir: '/runtime-profile', cwd: '/code' }, {})
  let release
  research.execute = () => new Promise(resolve => { release = resolve })
  research.readSnapshot = async sessionId => ({ sessionId, runs: [] })
  const records=[]
  research.record = async (_id,event) => records.push(event)
  const signal=new AbortController().signal
  const operation=research.call({sessionId:'targeted',preset:'workspace-write'},{action:'analysis',data:{run_id:'selected-run'}},signal)
  const snapshot=await research.snapshot('targeted',signal)
  assert.equal(snapshot.current.runId,'selected-run')
  release({saved:true});await operation
  assert.equal((await research.snapshot('targeted',signal)).current,null)
  assert.equal(records[0].runId,'selected-run')
  assert.equal(records[0].status,'running')
  assert.equal(records[1].runId,'selected-run')
  assert.deepEqual(records[1].input,{action:'analysis',data:{run_id:'selected-run'}})
  assert.deepEqual(records[1].result,{saved:true})
})

test('a snapshot finishing after an operation stops does not report stale running state',async()=>{
 const research=new Research({dir:'/runtime-profile',cwd:'/code'}, {})
 let finishRead
 research.readSnapshot=()=>new Promise(resolve=>{finishRead=resolve})
 research.running.set('one',{activity:{action:'analysis'},runId:'batch'})
 const reading=research.snapshot('one',new AbortController().signal)
 research.running.delete('one')
 finishRead({runs:[]})
 assert.equal((await reading).current,null)
})

test('complete operation records retain inputs, results and failures while polls retain the entire lightweight index',async t=>{
 const workspace=await mkdtemp(join(tmpdir(),'insight-activity-'))
 t.after(()=>rm(workspace,{recursive:true,force:true}))
 await writeFile(join(workspace,'conversation.json'),JSON.stringify({question:'Fixture'}))
 const research=new Research({dir:workspace,cwd:workspace},{run:async()=>({runs:[],details:[],storage:{data_root:workspace,outputs:workspace}})})
 research.workspace=()=>workspace
 research.settings=async()=>({engineRoot:workspace,workspace})
 const legacy=Array.from({length:125},(_,i)=>({action:'evidence',status:'completed',startedAt:String(i)}))
 await writeFile(join(workspace,'activity.jsonl'),legacy.map(event=>JSON.stringify(event)).join('\n')+'\n')
 const input={action:'analysis',data:{run_id:'batch',text:'Full input '.repeat(10000)}}
 research.execute=async()=>({run_id:'batch',saved:'Full output '.repeat(10000)})
 await research.call({sessionId:'fixture',preset:'workspace-write'},input,new AbortController().signal)
 const snapshot=await research.readSnapshot('fixture',new AbortController().signal)
 assert.equal(snapshot.events.length,126)
 const completed=snapshot.events.at(-1)
 assert.equal(completed.status,'completed')
 assert.equal(completed.runId,'batch')
 assert.equal(completed.hasDetails,true)
 assert.equal(Object.hasOwn(completed,'input'),false)
 assert.equal(Object.hasOwn(completed,'result'),false)
 const record=await research.activityRecord('fixture',completed.id)
 assert.deepEqual(record.input,input)
 assert.equal(record.result.saved.length,120000)
 assert.equal(JSON.parse(await readFile(join(workspace,'.activity',completed.id+'.json'),'utf8')).status,'completed')
 research.execute=async()=>{const error=new Error('Source unavailable');error.code='SOURCE_DENIED';throw error}
 await assert.rejects(research.call({sessionId:'fixture',preset:'workspace-write'},{action:'worker',runId:'batch'},new AbortController().signal),/Source unavailable/)
 const failed=(await research.readSnapshot('fixture',new AbortController().signal)).events.at(-1)
 assert.deepEqual((await research.activityRecord('fixture',failed.id)).error,{code:'SOURCE_DENIED',message:'Source unavailable'})
 await assert.rejects(research.activityRecord('fixture','../escape'),error=>error.code==='INVALID_ID')
 await assert.rejects(research.activityRecord('fixture','missing'),error=>error.code==='ACTIVITY_NOT_FOUND')
})
