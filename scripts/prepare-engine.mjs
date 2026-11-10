/** Hydrate a pinned public engine artifact for source builds; installed archives already contain it. */
import {createHash} from 'node:crypto'
import {constants} from 'node:fs'
import {readFile,writeFile,mkdir,mkdtemp,rm,copyFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {resolve,dirname,basename,join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {x} from 'tar'
import {runtimeManifest} from '../src/runtime-paths.js'

/** Hydrate only manifest-listed engine files; modified local files are retained and rejected.
 * @param destination - Bundled engine directory for this source build.
 * @returns Completion after file and archive integrity checks.
 */
export async function prepareBundledEngine(destination=fileURLToPath(new URL('../engine/',import.meta.url))){
 const manifest=await runtimeManifest(),missing=[]
 const digest=bytes=>createHash('sha256').update(bytes).digest('hex')
 for(const file of manifest.files){
  try{if(digest(await readFile(join(destination,file.path)))!==file.sha256)throw Error('Engine file has local changes: '+file.path)}
  catch(error){if(error.code!=='ENOENT')throw error;missing.push(file)}
 }
 if(!missing.length)return
 const artifact=manifest.artifact
 if(!artifact||typeof artifact.url!=='string'||new URL(artifact.url).protocol!=='https:'||typeof artifact.integrity!=='string')throw Error('Missing pinned engine artifact')
 const response=await fetch(artifact.url)
 if(!response.ok)throw Error('Engine artifact download failed: HTTP '+response.status)
 const archive=Buffer.from(await response.arrayBuffer())
 if('sha512-'+createHash('sha512').update(archive).digest('base64')!==artifact.integrity)throw Error('Engine archive integrity mismatch')
 const temporary=await mkdtemp(join(tmpdir(),'deep-insight-bundle-'))
 try{
  const archivePath=join(temporary,'runtime.tgz'),extracted=join(temporary,'engine')
  await mkdir(extracted)
  await writeFile(archivePath,archive,{flag:'wx'})
  await x({file:archivePath,cwd:extracted,strip:2,filter:path=>path==='package'||path==='package/engine'||path.startsWith('package/engine/')})
  for(const file of missing){
   const source=join(extracted,file.path)
   if(digest(await readFile(source))!==file.sha256)throw Error('Engine artifact file integrity mismatch: '+file.path)
  }
  for(const file of missing){
   const target=join(destination,file.path)
   await mkdir(dirname(target),{recursive:true})
   await copyFile(join(extracted,file.path),target,constants.COPYFILE_EXCL)
  }
 }finally{
  if(dirname(resolve(temporary))!==resolve(tmpdir())||!basename(temporary).startsWith('deep-insight-bundle-'))throw Error('Unexpected temporary directory')
  await rm(temporary,{recursive:true,force:true})
 }
 console.log('Prepared verified engine artifact')
}

if(import.meta.main){try{await prepareBundledEngine()}catch(error){console.error(error.message);process.exitCode=1}}
