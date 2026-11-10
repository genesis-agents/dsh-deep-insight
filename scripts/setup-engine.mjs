/** Prepare the bundled Python runtime in an existing DSH profile without replacing explicit settings. */
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir,access} from 'node:fs/promises'
import {homedir} from 'node:os'
import {resolve,join,isAbsolute} from 'node:path'
import {spawn} from 'node:child_process'
import {runtimeManifest,defaultEngineRoot} from '../src/runtime-paths.js'

/** Prepare the writable runtime without replacing modified files.
 * @param profile - Existing installed profile directory.
 * @returns Verified engine directory.
 */
export async function prepareEngine(profile){
 await access(join(profile.dir,'package.json'))
 const manifest=await runtimeManifest(),target=await defaultEngineRoot(profile)
 for(const file of manifest.files){
  if(typeof file.path!=='string'||file.path.includes('\\')||file.path.split('/').some(part=>!part||part==='.'||part==='..')||isAbsolute(file.path)||!/^[a-f0-9]{64}$/.test(file.sha256))throw Error('Invalid engine manifest entry')
  const source=await readFile(new URL('../engine/'+file.path,import.meta.url))
  if(createHash('sha256').update(source).digest('hex')!==file.sha256)throw Error('Bundled engine integrity failure: '+file.path)
  const destination=join(target,file.path)
  let existing
  try{existing=await readFile(destination)}catch(error){if(error.code!=='ENOENT')throw error}
  if(existing){if(createHash('sha256').update(existing).digest('hex')!==file.sha256)throw Error('Prepared engine has local changes: '+destination);continue}
  await mkdir(resolve(destination,'..'),{recursive:true})
  await writeFile(destination,source,{flag:'wx'})
 }
 return target
}

/** Synchronize an installed profile's runtime, retaining explicit settings.
 * @param args - Profile selection and optional media dependency flag.
 * @returns Completion after uv synchronization and initial settings creation.
 */
export async function setupEngine(args){
 let name,dir,media=false
 for(let i=0;i<args.length;i++){
  if(args[i]==='--profile')name=args[++i]
  else if(args[i]==='--profile-dir')dir=args[++i]
  else if(args[i]==='--media')media=true
  else throw Error('Unknown option: '+args[i])
 }
 if(!dir&&(!name||!/^[A-Za-z0-9_-]+$/.test(name)))throw Error('Supply --profile <installed-profile> or --profile-dir <absolute-path>')
 if(dir&&!isAbsolute(dir))throw Error('--profile-dir must be absolute')
 const profile={dir:dir??join(process.env.DSH_HOME??join(homedir(),'.dsh'),'profiles',name)}
 const target=await prepareEngine(profile)
 const command=['sync','--frozen','--no-dev','--project',target,...(media?['--extra','media']:[])]
 await new Promise((done,reject)=>{
  const child=spawn('uv',command,{stdio:'inherit',windowsHide:true})
  child.once('error',reject)
  child.once('exit',code=>code===0?done():reject(Error('uv sync failed with exit '+code)))
 })
 const settings=join(profile.dir,'deep-insight.json')
 const workspace=join(homedir(),'.pies','research')
 await mkdir(workspace,{recursive:true})
 try{await writeFile(settings,JSON.stringify({engineRoot:target,workspace},null,2)+'\n',{flag:'wx'})}
 catch(error){if(error.code!=='EEXIST')throw error}
 console.log('Research runtime ready: '+target+'\nExisting profile settings preserved.')
}

if(import.meta.main){
 try{await setupEngine(process.argv.slice(2))}catch(error){console.error('Research setup failed: '+error.message);process.exitCode=1}
}
