import {test} from 'node:test'
import assert from 'node:assert/strict'
import {cp,mkdtemp,readFile,writeFile,rm} from 'node:fs/promises'
import {join} from 'node:path'
import {tmpdir} from 'node:os'
import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'

test('engine installer is repeatable and refuses to overwrite unknown source changes',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'insight-install-'))
  const script=fileURLToPath(new URL('../scripts/install-engine-patch.mjs',import.meta.url))
  const files=fileURLToPath(new URL('../engine-patch/files/',import.meta.url))
  try{
    await cp(files,directory,{recursive:true})
    execFileSync(process.execPath,[script,directory,'--check'],{stdio:'pipe'})
    execFileSync(process.execPath,[script,'--check',directory],{stdio:'pipe'})
    execFileSync(process.execPath,[script,directory],{stdio:'pipe'})
    const changed=join(directory,'src/insight/application/research.py')
    await writeFile(changed,'# Deliberate local modification\n')
    assert.throws(()=>execFileSync(process.execPath,[script,directory],{stdio:'pipe'}),/unreviewed changes/)
    assert.equal(await readFile(changed,'utf8'),'# Deliberate local modification\n')
  }finally{await rm(directory,{recursive:true,force:true})}
})
