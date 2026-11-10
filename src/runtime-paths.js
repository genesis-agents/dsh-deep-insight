/** Versioned writable engine locations; explicit administrator settings retain precedence. */
import {readFile} from 'node:fs/promises'
import {join} from 'node:path'

/** Read the verified runtime file inventory.
 * @returns Manifest with a safe version identifier and relative file paths.
 */
export async function runtimeManifest(){
 const value=JSON.parse(await readFile(new URL('../engine-manifest.json',import.meta.url),'utf8'))
 if(value.schemaVersion!==1||!/^[a-f0-9]{16}$/.test(value.id)||!Array.isArray(value.files))throw Error('Invalid bundled research runtime manifest')
 if(!value.files.every(file=>typeof file.path==='string'&&!file.path.includes('\\')&&!file.path.startsWith('/')&&!file.path.includes(':')&&file.path.split('/').every(part=>part&&part!=='.'&&part!=='..')&&/^[a-f0-9]{64}$/.test(file.sha256)))throw Error('Invalid engine manifest entry')
 return value
}

/** Resolve the prepared engine for one installed DSH profile.
 * @param profile - Installed profile with its absolute directory.
 * @returns Versioned writable engine directory.
 */
export async function defaultEngineRoot(profile){return join(profile.dir,'deep-insight-engine',(await runtimeManifest()).id)}
