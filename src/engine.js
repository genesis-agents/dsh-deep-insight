/** Managed JSON CLI bridge; the Python application remains the only research-data writer. */
import { access, realpath, readFile } from 'node:fs/promises'
import { resolve, relative, isAbsolute, extname } from 'node:path'

export class InsightError extends Error {
  constructor(code, message, status = 400) { super(message); this.code = code; this.status = status }
}

export function contained(root, candidate) {
  const path = relative(root, candidate)
  return path === '' || (!isAbsolute(path) && path !== '..' && !path.startsWith('../') && !path.startsWith('..\\'))
}

export async function validateSettings(value, hostRoot) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || typeof value.engineRoot !== 'string' || !isAbsolute(value.engineRoot)
    || typeof value.workspace !== 'string' || !isAbsolute(value.workspace)) {
    throw new InsightError('INVALID_SETTINGS', '研究内核和工作区都必须使用绝对路径')
  }
  const engineRoot = await realpath(value.engineRoot)
  const workspace = await realpath(value.workspace)
  if (contained(await realpath(hostRoot), workspace) || contained(engineRoot, workspace)) {
    throw new InsightError('WORKSPACE_IN_CODE', '研究工作区必须位于 PIES 和研究内核源码目录之外')
  }
  await access(resolve(engineRoot, 'pyproject.toml'))
  await access(resolve(engineRoot, 'src/insight/entrypoints/cli.py'))
  return { engineRoot, workspace }
}

export class InsightEngine {
  constructor(subprocess, signal) { this.subprocess = subprocess; this.signal = signal }

  async execute(settings, command, runId) {
    const allowed = new Set(['doctor', 'status', 'init', 'reading-room', 'quality', 'collectors'])
    if (!allowed.has(command)) throw new InsightError('UNSUPPORTED_OPERATION', '不支持此研究操作')
    if (runId !== undefined && (typeof runId !== 'string' || !/^[a-zA-Z0-9_.-]{1,128}$/.test(runId))) {
      throw new InsightError('INVALID_RUN', '研究任务标识无效')
    }
    if (command === 'quality' && !runId) throw new InsightError('INVALID_RUN', '请选择研究任务')
    const argv = ['uv', 'run', '--frozen', '--no-sync', '--project', settings.engineRoot,
      'insight', '--workspace', settings.workspace, command, ...(runId ? ['--run', runId] : [])]
    return this.run(settings.engineRoot, argv, 60000, true)
  }

  async setup(settings) {
    await this.run(settings.engineRoot, ['uv', 'sync', '--frozen', '--project', settings.engineRoot], 180000, false)
    return { ready: true }
  }

  async run(cwd, argv, timeoutMs, json, signal = this.signal) {
    const child = this.subprocess.spawn({ argv, cwd, env: { PYTHONUTF8: '1' }, graceMs: 2000,
      signal: AbortSignal.any([this.signal, signal, AbortSignal.timeout(timeoutMs)]),
      stdio: { stdin: 'ignore', stdout: { maxBytes: 4 * 1024 * 1024 }, stderr: { maxBytes: 32768 } } })
    try {
      const outcome = await child.done
      if (signal.aborted || this.signal.aborted) throw new InsightError('CANCELLED', '研究操作已停止', 409)
      const output = child.collected.stdout.readFrom(0)
      if (output.lossy) throw new InsightError('OUTPUT_TOO_LARGE', '研究结果过大，请打开具体任务查看', 502)
      let value
      if (json) {
        try { value = JSON.parse(output.text) } catch {
          throw new InsightError('ENGINE_UNAVAILABLE', '研究内核未就绪，请先检查路径并准备运行环境', 502)
        }
      }
      if (outcome.exitCode !== 0 || value?.error) {
        throw new InsightError(value?.error?.code ?? 'ENGINE_FAILED',
          value?.error?.detail ?? '研究内核运行失败，请检查 uv、Python 版本和依赖安装', 502)
      }
      return value
    } finally { child.terminate(); await child.waitForExit(AbortSignal.timeout(3000)) }
  }
}

/** Only serve report formats under the configured workspace after resolving symlinks. */
export async function reportFile(workspace, path) {
  if (!path || isAbsolute(path)) throw new InsightError('INVALID_PATH', '报告路径无效')
  const root = await realpath(workspace)
  const file = await realpath(resolve(root, path))
  if (!contained(root, file)) throw new InsightError('OUTSIDE_WORKSPACE', '报告不在当前研究工作区中', 403)
  const types = { '.html': 'text/html; charset=utf-8', '.pdf': 'application/pdf', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.css': 'text/css', '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8' }
  const type = types[extname(file).toLowerCase()]
  if (!type) throw new InsightError('UNSUPPORTED_FILE', '此文件不能作为报告打开', 403)
  return { content: await readFile(file), type }
}
