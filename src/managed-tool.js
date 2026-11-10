/** Standard DSH tool registration; identity and permissions come only from the executing agent. */
import {z} from 'zod'
import {researchActions,researchTool} from './research-tool.js'
import {researchActor} from './capability-ports.js'
import {InsightError} from './engine.js'

const inputSchema=z.object({action:z.enum(researchActions),data:z.record(z.string(),z.unknown()).optional(),draft:z.boolean().optional(),expectedRevision:z.number().int().nonnegative().optional(),runId:z.string().optional(),version:z.string().optional(),plan:z.string().optional()}).strict()

/** Create a model tool with pure presentation and host cancellation.
 * @param ctx - Host services used to resolve protected execution identity.
 * @param research - Current research dispatcher.
 * @param lifetime - Owning plugin's cancellation signal.
 * @returns Standard DSH tool definition.
 */
export function managedResearchTool(ctx,research,lifetime){
 return {name:researchTool.name,description:researchTool.description,parameters:researchTool.inputSchema,
  output:{schema:{},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
  presentCall:args=>({card:'generic',title:'Deep insight',kind:'other',rawInput:JSON.stringify(args)}),
  async execute(input,exec){
   const args=inputSchema.parse(input)
   if(!exec.agent)throw new InsightError('AGENT_REQUIRED','Research requires an executing agent')
   const actor=researchActor(ctx,exec.agent.sessionId,exec.agent)
   return research.call(actor,args,AbortSignal.any([lifetime,exec.signal]))
  },
 }
}
