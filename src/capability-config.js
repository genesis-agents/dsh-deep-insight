/** Deployment settings for research enrichment and local semantic indexing. */
import {z} from 'zod'

export const Config=z.object({
  enrichment:z.object({
    maxPacketCharacters:z.number().int().positive().default(500000),
    embeddingModel:z.string().min(1).default('Xenova/multilingual-e5-small'),
    embeddingDtype:z.enum(['q8','fp32']).default('q8'),
    embeddingChunkCharacters:z.number().int().min(16).default(256),
    embeddingBatchSize:z.number().int().positive().default(8),
    maxEmbeddingChunks:z.number().int().positive().default(4000),
    embeddingTimeoutMs:z.number().int().positive().default(1200000),
    embeddingCache:z.string().min(1).optional(),
  }).prefault({}),
}).prefault({})

/** Resolve defaults and reject invalid deployment values before starting the plugin. */
export const resolveCapabilityConfig=value=>Config.parse(value).enrichment
