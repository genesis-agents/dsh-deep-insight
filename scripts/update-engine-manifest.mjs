/** Refresh reviewed patch hashes and hydrate the bundled runtime without editing installed profiles. */
import {readFile, writeFile, readdir, mkdir} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {relative} from 'node:path'
import {fileURLToPath} from 'node:url'

const root = new URL('../', import.meta.url)
const digest = data => createHash('sha256').update(data).digest('hex')
const patchUrl = new URL('engine-patch/manifest.json', root)
const patch = JSON.parse(await readFile(patchUrl, 'utf8'))
const runtimeUrl = new URL('engine-manifest.json', root)
const runtime = JSON.parse(await readFile(runtimeUrl, 'utf8'))
const updates = []
for (const path of await readdir(new URL('engine-patch/files/', root), {recursive:true, withFileTypes:true})) {
  if (!path.isFile() || !/\.(?:py|md|html)$/.test(path.name) || path.parentPath.includes('__pycache__')) continue
  const name = relative(fileURLToPath(new URL('engine-patch/files/', root)), path.parentPath + '/' + path.name).replaceAll('\\', '/')
  if (!patch.files.some(file => file.path === name)) patch.files.push({path:name, sha256:null, baseSha256:null})
}
for (const file of patch.files) {
  const bytes = await readFile(new URL('engine-patch/files/' + file.path, root))
  const sha256 = digest(bytes)
  if (sha256 === file.sha256) continue
  const target = new URL('engine/' + file.path, root)
  let current = null
  try { current = digest(await readFile(target)) }
  catch (error) { if (error.code !== 'ENOENT') throw error }
  if (current !== file.sha256 && current !== sha256 && !(current === null && !runtime.files.some(item => item.path === file.path))) throw Error('Bundled engine has unreviewed changes: ' + file.path)
  file.previousSha256 = [...new Set([...(file.previousSha256 ?? []), file.sha256].filter(Boolean))]
  file.sha256 = sha256
  updates.push({target, bytes})
}
for (const file of runtime.files) {
  const current = digest(await readFile(new URL('engine/' + file.path, root)))
  const reviewed = patch.files.find(item => item.path === file.path)?.sha256
  if (current !== file.sha256 && current !== reviewed) throw Error('Unreviewed runtime file: ' + file.path)
}
for (const update of updates) {
  await mkdir(new URL('.', update.target), {recursive:true})
  await writeFile(update.target, update.bytes)
}
for (const file of patch.files) {
  if (file.path.startsWith('src/') && !runtime.files.some(item => item.path === file.path)) runtime.files.push({path:file.path, sha256:file.sha256})
}
runtime.files.sort((a,b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0)
for (const file of runtime.files) file.sha256 = digest(await readFile(new URL('engine/' + file.path, root)))
runtime.id = digest(JSON.stringify(runtime.files)).slice(0, 16)
await writeFile(patchUrl, JSON.stringify(patch, null, 2) + '\n')
await writeFile(runtimeUrl, JSON.stringify(runtime, null, 2) + '\n')
console.log('Updated reviewed engine files:', updates.length, 'runtime:', runtime.id)
