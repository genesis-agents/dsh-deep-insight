import {randomUUID} from 'node:crypto'
import {InsightError} from './engine.js'

/** Save question-specific search receipts; failed access never authorizes downstream completeness.
 * @param research - Session-bound research owner and host execution ports.
 * @param input - Search action with exact query assignments.
 * @param settings - Current engine and workspace directories.
 * @param detail - Frozen project and run records.
 * @param signal - Cancellation for requests and receipts.
 * @returns Search leads with durable execution identity and per-query results.
 */
export async function searchResearch(research, input, settings, detail, signal) {
  const project = detail.input_snapshot.project
  const data = input.data ?? {}
  let assignments
  if (Array.isArray(data.searches)) {
    assignments = data.searches
    if (!assignments.length || assignments.some(item => !item || typeof item.query !== 'string' || !item.query.trim() || !project.subquestions.includes(item.question))) {
      throw new InsightError('INVALID_SEARCH', 'searches 必须逐项提供 query 和对应的研究子问题 question')
    }
  } else {
    const {queries, questions} = data
    if (project.research_design || !Array.isArray(queries) || !queries.length || queries.some(q => typeof q !== 'string' || !q.trim()) || !Array.isArray(questions) || !questions.length || questions.some(q => !project.subquestions.includes(q))) {
      throw new InsightError('INVALID_SEARCH', '请使用 searches: [{query, question}]，逐条关联实际查询与研究子问题')
    }
    assignments = queries.map(query => ({query}))
  }
  const queries = assignments.map(item => item.query)
  const questions = data.searches ? [...new Set(assignments.map(item => item.question))] : data.questions
  const request = {execution_ref: 'exec_' + randomUUID().replaceAll('-', ''), queries, questions, assignments}
  await research.receipt(settings, input.runId, 'search_started', request, signal)
  try {
    const result = await research.execution.search(queries, signal)
    const results = (result.results ?? []).map((row, index) => ({...row, question: assignments[index].question}))
    const receipt = {...request, ...result, results}
    await research.receipt(settings, input.runId, 'search_completed', receipt, signal)
    return {...receipt, notice: 'Results are discovery leads. Acquire originals, assess relevance and source dependence, and record rejected candidates. Search receipts do not establish question coverage.'}
  } catch (error) {
    if (!signal.aborted) await research.receipt(settings, input.runId, 'search_failed', {...request, code: error.code ?? 'SEARCH_FAILED', error: error.message, partial_results: error.partial_results ?? []}, signal)
    throw error
  }
}
