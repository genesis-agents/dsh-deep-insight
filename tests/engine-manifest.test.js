import {test} from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp, mkdir, readFile, writeFile, rm, copyFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'

test('runtime regeneration publishes reviewed patches and refuses unrelated engine tampering', async t => {
  const root=await mkdtemp(join(tmpdir(),'insight-manifest-'))
  t.after(()=>rm(root,{recursive:true,force:true}))
  for(const path of ['scripts','engine/src','engine-patch/files/src'])await mkdir(join(root,path),{recursive:true})
  const script=join(root,'scripts/update-engine-manifest.mjs')
  await copyFile(new URL('../scripts/update-engine-manifest.mjs',import.meta.url),script)
  const digest=text=>createHash('sha256').update(text).digest('hex')
  await writeFile(join(root,'engine/src/original.py'),'before\n')
  await writeFile(join(root,'engine/pyproject.toml'),'fixed project\n')
  await writeFile(join(root,'engine-patch/files/src/original.py'),'after\n')
  await writeFile(join(root,'engine-patch/manifest.json'),JSON.stringify({files:[{path:'src/original.py',sha256:digest('before\n'),baseSha256:null}]}))
  await writeFile(join(root,'engine-manifest.json'),JSON.stringify({files:[{path:'src/original.py',sha256:digest('before\n')},{path:'pyproject.toml',sha256:digest('fixed project\n')}]}))
  execFileSync(process.execPath,[script],{stdio:'pipe'})
  assert.equal(await readFile(join(root,'engine/src/original.py'),'utf8'),'after\n')
  const manifest=await readFile(join(root,'engine-manifest.json'),'utf8')
  await writeFile(join(root,'engine/pyproject.toml'),'unreviewed project\n')
  assert.throws(()=>execFileSync(process.execPath,[script],{stdio:'pipe'}),/Unreviewed runtime file/)
  assert.equal(await readFile(join(root,'engine-manifest.json'),'utf8'),manifest)
})
