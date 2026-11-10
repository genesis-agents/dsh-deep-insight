/** Reviewed computation, simulation and read-only data tools from dsh-quant 0.91.1. */
import { randomUUID } from 'node:crypto'

// Deliberately not a prefix wildcard: installing another tool must not silently
// grant a native Agent access to filesystem mutations or live trading actions.
const names = new Set(`sma ema rsi macd bollinger atr market_fetch backtest backtest_grid
kdj williams_r cci obv adx roc backtest_bollinger backtest_rsi backtest_portfolio
portfolio_optimize data_guide data_compare data_advice series_stats data_quality
series_quality data_annotate data_pit channel_guide factor_evaluate ic_decay
factor_combine layered_backtest attribution factor_correlation deflated_sharpe
parameter_sensitivity chart metrics fund risk stress_test var_backtest resample
report repo_stats npm_stats oss_pulse factor_neutralize walk_forward drawdown
execute_sim trade_quality trading_cost rebalance_schedule bond option volatility
linear_model research_pipeline`.split(/\s+/).map(name => 'quant_' + name))

/** Project only tools actually registered in the current host; execution retains its pipeline. */
export function quantTools(ctx, journal, batchId = randomUUID()) {
  return ctx.tools.schemas().filter(tool => names.has(tool.name)).map(tool => ({
    name: tool.name, description: tool.description, inputSchema: tool.parameters,
    async call(actor, args, signal) {
      signal.throwIfAborted()
      const execute = async () => {
        const batch = await ctx.tools.execute({
          calls: [{ type: 'tool-call', id: randomUUID(), name: tool.name, arguments: JSON.stringify(args ?? {}) }], signal,
        })
        const result = batch.results[0]?.result
        if (!result) throw new Error('Quant executor did not return a result')
        if (result.isError) {
          const error = new Error(result.error?.message ?? 'Quant tool failed')
          error.code = result.error?.code ?? 'QUANT_TOOL_FAILED'
          throw error
        }
        return result.value
      }
      return journal ? journal.record(actor, batchId, tool.name, args, execute) : execute()
    },
  }))
}
