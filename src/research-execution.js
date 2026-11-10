/** Host-owned searches and isolated review calls; their exact inputs and results are durable. */
import { InsightError } from './engine.js'

/** Bind execution to host search and model services without replaying author history. */
export function researchExecution(ctx) {
  return {
    async search(queries, signal) {
      if (!ctx.web) throw new InsightError('SEARCH_UNAVAILABLE', '当前宿主未提供网络检索，请配置搜索服务后重试')
      const results=[]
      for(const query of queries){
        signal.throwIfAborted()
        const result=await ctx.web.search({query},signal)
        if (!Array.isArray(result?.sources) || typeof result.truncated !== 'boolean') throw new InsightError('SEARCH_INVALID', '检索返回格式无法核验')
        results.push({query,...result})
      }
      return {results,sources:[...new Map(results.flatMap(result=>result.sources).map(source=>[source.url,source])).values()],truncated:results.some(result=>result.truncated)}
    },
    async review(actor, messages, signal) {
      if (!actor.provider || !ctx.llm) throw new InsightError('REVIEW_UNAVAILABLE', '无法确定复核模型，请重新连接当前 Agent')
      let output = '', finish
      // Omitting sessionId starts a fresh model context with no author conversation or research MCP.
      try{
        for await (const chunk of ctx.llm.stream({ provider: actor.provider, model: actor.model, messages, tools: [], signal })) {
          if (chunk.type === 'text-delta') output += chunk.text
          if (chunk.type === 'finish') finish = chunk.reason
        }
      }catch(error){const failure=new InsightError(error.code??'MODEL_STREAM_FAILED',error.message,502);failure.output=output;throw failure}
      if (finish?.kind !== 'stop' || !output.trim()) {const failure=new InsightError('REVIEW_INCOMPLETE', '模型输出未完整结束，未登记为成功');failure.output=output;throw failure}
      return output
    },
  }
}
