/** Isolated CPU embedding worker; the owning subprocess terminates downloads and inference on cancellation. */
import {readFile,writeFile} from 'node:fs/promises'
import {pipeline,env} from '@huggingface/transformers'

const request=JSON.parse(await readFile(process.argv[2],'utf8'))
env.cacheDir=request.cacheDirectory
env.allowLocalModels=true
const extractor=await pipeline('feature-extraction',request.model,{dtype:request.dtype,device:'cpu'})
try{
 const vectors=[]
 for(let start=0;start<request.texts.length;start+=request.batchSize){
  const batch=request.texts.slice(start,start+request.batchSize)
  for(const text of batch){
   const tokenized=await extractor.tokenizer(text,{truncation:false})
   const length=tokenized.input_ids.dims.at(-1),limit=extractor.model.config.max_position_embeddings
   if(limit&&length>limit)throw Error('EMBEDDING_TEXT_TOO_LONG: reduce embeddingChunkCharacters; input was not truncated')
  }
  const output=await extractor(batch,{pooling:'mean',normalize:true,truncation:false})
  vectors.push(...output.tolist())
 }
 if(vectors.length!==request.texts.length||!vectors.length||vectors.some(vector=>!Array.isArray(vector)||vector.length!==vectors[0].length||vector.some(value=>!Number.isFinite(value))))throw Error('EMBEDDING_INVALID: incomplete or non-finite model output')
 await writeFile(process.argv[3],JSON.stringify({model:request.model,dimensions:vectors[0].length,vectors})+'\n',{mode:0o600})
 process.stdout.write(JSON.stringify({embedded:vectors.length,dimensions:vectors[0].length})+'\n')
}finally{await extractor.dispose()}
