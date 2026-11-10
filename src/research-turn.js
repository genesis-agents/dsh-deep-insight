/** Completion belongs to research quality, not the lifetime of one tool or native prompt. */
import { InsightError } from './engine.js'

const workActions = new Set(['project', 'source-import', 'source-register', 'plan', 'run', 'worker', 'evidence', 'context', 'analysis', 'verification', 'search', 'review', 'deliver', 'resume'])

/** Own only research attempted in this native generation; inspecting old work does not resume it. */
export class ResearchTurn {
  constructor(research, actor, signal) {
    this.research = research
    this.actor = actor
    this.signal = signal
    this.active = false
    this.runId = undefined
    this.delivered = false
    this.cancelled = false
  }

  async call(actor, input, signal) {
    if (workActions.has(input?.action) && actor.preset !== 'read-only') {
      this.active = true
      this.delivered = false
      if (input.runId || input.data?.run_id) this.runId = input.runId ?? input.data.run_id
    }
    const result = await this.research.call(actor, input, signal)
    if (input.action === 'project' || input.action === 'plan') this.runId = undefined
    if (input.action === 'run') this.runId = result.run_id
    if (input.action === 'worker' && !this.runId && result.processed_runs?.length === 1) this.runId = result.processed_runs[0]
    if (input.action === 'cancel' && input.runId === this.runId) this.cancelled = true
    if (input.action === 'resume') this.cancelled = false
    if (input.action === 'deliver' && input.draft !== true) this.delivered = true
    return result
  }

  /** Re-evaluate authoritative quality after end_turn; never accept cached UI or tool success. */
  async completionRequirement() {
    this.signal.throwIfAborted()
    if (!this.active) return undefined
    if (this.cancelled) throw new InsightError('RESEARCH_CANCELLED', '研究已取消，未完成项保留；本轮不计为研究完成')
    let remaining
    if (!this.runId) remaining = { next_actions: ['Create a run for the current source plan and complete the research.'] }
    else {
      const quality = await this.research.call(this.actor, { action: 'quality', runId: this.runId }, this.signal)
      if (!Array.isArray(quality?.next_actions) || typeof quality.quality_state !== 'string') {
        throw new InsightError('QUALITY_INVALID', '无法核验研究质量状态；本轮不计为完成，请检查研究内核')
      }
      if (['machine_verified', 'reviewed'].includes(quality.quality_state) && quality.next_actions.length === 0 && this.delivered) return undefined
      remaining = { run_id: this.runId, quality_state: quality.quality_state, next_actions: quality.next_actions, delivery_required: !this.delivered }
    }
    return 'Research is not complete. Current authoritative checks:\n' + JSON.stringify(remaining)
      + '\nContinue the authorized research in this session. Repair the failed checks, use alternative sources for blocked acquisition, revise analysis, and rerun review and quality before final delivery. Do not lower the agreed quality standard or substitute a draft for completion. A completed tool call or progress report is not task completion. Preserve completed work and prior runs. If a genuine blocker prevents progress, report the exact blocker and incomplete work; do not claim success. User cancellation and execution limits still apply.'
  }
}
