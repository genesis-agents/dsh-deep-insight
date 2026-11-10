/** Versioned writable engine locations; explicit administrator settings retain precedence. */
import {readFile} from 'node:fs/promises'
import {join} from 'node:path'

/** Return the bundled runtime manifest after validating its directory identifier. */
export async function runtimeManifest(){
 const value=JSON.parse(await readFile(new URL('../engine-manifest.json',import.meta.url),'utf8'))
 if(value.schemaVersion!==1||!/^[a-f0-9]{16}$/.test(value.id)||!Array.isArray(value.files))throw Error('Invalid bundled research runtime manifest')
 return value
}

/** Resolve the prepared engine for one installed DSH profile. */
export async function defaultEngineRoot(profile){return join(profile.dir,'deep-insight-engine',(await runtimeManifest()).id)}
