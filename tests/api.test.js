import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, mkdir, writeFile, rm, realpath } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { apply } from '../src/index.js'

test('profile API rejects cross-origin mutations and malformed JSON, then saves only validated workspace settings', async t => {
  const root = await mkdtemp(join(tmpdir(), 'insight-api-'))
  const profile = join(root, 'profile'), host = join(root, 'host'), engine = join(root, 'engine'), workspace = join(root, 'data')
  for (const path of [profile, host, workspace, join(engine, 'src/insight/entrypoints')]) await mkdir(path, { recursive: true })
  await writeFile(join(engine, 'pyproject.toml'), '[project]\nname="fixture"\n')
  await writeFile(join(engine, 'src/insight/entrypoints/cli.py'), '# test fixture\n')
  const routes = [], disposers = []
  apply({ profileContext: { dir: profile, cwd: host, name: 'web' }, subprocess: { spawn() { throw new Error('Unexpected process') } },
    tools: { schemas: () => [], register:()=>()=>{} },
    provide: () => () => {},
    effect: fn => { const dispose = fn(); if (dispose?.next) { for (const _ of dispose) {} return () => {} }; disposers.push(dispose); return dispose },
    webServer: { register: route => { assert.equal(route.path.endsWith('/'), false); routes.push(route); return () => {} } } })
  const server = createServer((req, res) => { void routes[0].handler(req, res) })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(async () => {
    for (const dispose of disposers) await dispose()
    await new Promise(resolve => server.close(resolve))
    await rm(root, { recursive: true, force: true })
  })
  const origin = `http://127.0.0.1:${server.address().port}`, url = `${origin}/deep-insight/api`
  const post = (body, requestOrigin = origin) => fetch(url, { method: 'POST', headers: { origin: requestOrigin, 'content-type': 'application/json' }, body })
  assert.equal((await post('{}', 'https://other.example')).status, 403)
  assert.equal((await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:'{}'})).status,403)
  const forwarded=()=>fetch(url,{method:'POST',headers:{'content-type':'application/json','x-deep-insight-client':'1'},body:JSON.stringify({action:'configure',config:{engineRoot:engine,workspace}})})
  assert.equal((await forwarded()).status,200)
  assert.equal((await fetch(url,{method:'POST',headers:{'content-type':'application/json','x-deep-insight-client':'1','sec-fetch-site':'cross-site'},body:'{}'})).status,403)
  assert.equal((await post('null')).status, 400)
  assert.equal((await post('{')).status, 400)
  assert.equal((await post(JSON.stringify({ action: 'configure', config: { engineRoot: engine, workspace } }))).status, 200)
  const state = await (await fetch(url)).json()
  assert.equal(state.config.workspace, await realpath(workspace))
  assert.equal(state.host.profile, 'web')
  assert.equal(state.busy, false)
  assert.equal((await post(JSON.stringify({ action: 'configure', config: { engineRoot: engine, workspace: host } }))).status, 400)
  assert.equal((await (await fetch(url)).json()).config.workspace, await realpath(workspace))
})
