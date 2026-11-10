/** Apply the reviewed engine files only to their recorded upstream revision or installed bytes. */
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {resolve,dirname,relative,isAbsolute} from 'node:path'
import {fileURLToPath} from 'node:url'
const patch=fileURLToPath(new URL('../engine-patch/',import.meta.url))
const manifest=JSON.parse(await readFile(resolve(patch,'manifest.json'),'utf8'))
const root=resolve(process.argv.slice(2).find(argument=>argument!=='--check')??'.cache/auto-systems/platforms/insight-platform')
const hash=data=>createHash('sha256').update(data).digest('hex')
const pending=[]
for(const item of manifest.files){
  const target=resolve(root,item.path),part=relative(root,target)
  if(part.startsWith('..')||isAbsolute(part))throw Error('Invalid engine patch path')
  const desired=await readFile(resolve(patch,'files',item.path))
  if(hash(desired)!==item.sha256)throw Error('Damaged engine patch: '+item.path)
  let current=null
  try{current=await readFile(target)}catch(error){if(error.code!=='ENOENT')throw error}
  if(current&&hash(current)===item.sha256)continue
  const baseHash=current?hash(Buffer.from(current.toString('utf8').replaceAll('\r\n','\n'))):null
  const desiredTextHash=hash(Buffer.from(desired.toString('utf8').replaceAll('\r\n','\n')))
  if(baseHash!==item.baseSha256&&baseHash!==desiredTextHash&&!item.previousSha256?.includes(current?hash(current):null))throw Error('Engine has unreviewed changes: '+item.path)
  pending.push({target,desired})
}
if(process.argv.includes('--check')){
  if(pending.length)throw Error('Engine patch is not installed; run this command without --check')
}else for(const {target,desired} of pending){await mkdir(dirname(target),{recursive:true});await writeFile(target,desired)}
console.log(`Research engine: ${manifest.files.length} files verified; ${pending.length} applied.`)
