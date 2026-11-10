import { test } from 'node:test'
import assert from 'node:assert/strict'
import { quantTools } from '../src/quant-tools.js'
import { Context } from '../../../vendor/cordis/lib/index.js'
import Tools, { defineTool } from '../../../packages/core/tools/lib/index.js'
import * as NativeExecutor from '../../../packages/core/tool-executor-native/lib/index.js'
import SystemPrompt from '../../../packages/core/system-prompt/lib/index.js'

test('Quant bridge uses current host schemas and execution validation, excluding unrelated tools', async () => {
  const ctx = new Context()
  try {
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(Tools)
    await ctx.plugin(NativeExecutor)
    await ctx.plugin({ name: 'quant-bridge-fixture', inject: ['tools'], apply(scope) {
      for (const name of ['quant_sma', 'quant_live_trade', 'shell_exec']) scope.tools.register(defineTool({
        name, description: 'Synthetic bridge fixture', parameters: { value: { type: 'number', required: true } },
        output: { schema: { type: 'number' }, render: (_args, value) => [{ type: 'text', text: String(value) }] },
        execute: async args => args.value,
      }))
    } })
    const tools = quantTools(ctx)
    assert.deepEqual(tools.map(tool => tool.name), ['quant_sma'])
    assert.equal(tools[0].inputSchema.properties.value.type, 'number')
    const signal = new AbortController().signal
    assert.equal(await tools[0].call({ preset: 'read-only' }, { value: 7 }, signal), 7)
    await assert.rejects(tools[0].call({}, { value: 'invalid' }, signal))
    const aborted = AbortSignal.abort()
    await assert.rejects(tools[0].call({}, { value: 7 }, aborted), { name: 'AbortError' })
  } finally { await ctx.fiber.dispose() }
})
