/** Isolated production-component acceptance with explicitly synthetic market/results data. */
import { readFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = await import(pathToFileURL(resolve(process.env.PIES_PLAYWRIGHT)).href)
const reactRequire = createRequire(require.resolve('@testing-library/react'))
const react = dirname(reactRequire.resolve('react/package.json')), reactDom = dirname(reactRequire.resolve('react-dom/package.json'))
const output = resolve('.cache/quant-review'); await mkdir(output, { recursive: true })
const close = Array.from({ length: 120 }, (_, i) => 100 + Math.sin(i / 8) * 12 + i / 4)
const equity = close.map((_, i) => 1 + i / 1000 + Math.sin(i / 10) / 30)
const candles = close.map((value, i) => ({ openTime: Date.UTC(2026, 6, 1 + i), close: value }))
const common = { schema: 1, batchId: 'synthetic-acceptance', status: 'completed', startedAt: '2026-11-06T22:00:00Z', finishedAt: '2026-11-06T22:01:00Z' }
const snapshot = { directory: 'Synthetic fixture / Not a real investment result', calls: [
  { ...common, id: 'market', tool: 'quant_market_fetch', args: { symbol: 'SYNTHETIC', interval: '1d' }, result: { symbol: 'SYNTHETIC', interval: '1d', provider: 'fixture', candles } },
  { ...common, id: 'backtest', tool: 'quant_backtest', args: { close, fast: 5, slow: 20, feeRate: .001 }, result: { totalReturnPct: 12, maxDrawdownPct: 3, sharpe: 1.2, fast: 5, slow: 20, feeRate: .001, equityCurve: equity, trades: [{ entryIndex: 25, entryPrice: close[25], exitIndex: 52, exitPrice: close[52], returnPct: 3, exitReason: 'signal' }] } },
] }
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = []
page.on('pageerror', error => errors.push(error.message))
try {
  await page.setContent('<!doctype html><html><body style="margin:0;font-family:Arial,sans-serif;background:var(--dsw-alias-bg-layer-1)"><div id="app"></div></body></html>')
  await page.addScriptTag({ path: resolve(react, 'umd/react.development.js') }); await page.addScriptTag({ path: resolve(reactDom, 'umd/react-dom.development.js') })
  await page.evaluate(snapshot => {
    window.fetch = async () => ({ ok: true, json: async () => snapshot })
    window.__ModuleLoader__ = { load({ factory }) {
      factory(() => window.React).apply({ locale:{register:()=>()=>{},bind:()=>key=>key}, effect: fn => fn(), sidebarRightTabs: { register: () => () => {} }, sidebarRight: {}, slots: {
        inject: (_, fn) => fn(), register(entry, component) { if (entry.id === 'quant-research') window.ReactDOM.createRoot(document.getElementById('app')).render(window.React.createElement(component, entry.inject('fixture'))) },
      } })
    } }
  }, snapshot)
  await page.addScriptTag({ content: await readFile(new URL('../client/index.js', import.meta.url), 'utf8') })
  await page.getByRole('heading', { name: /SYNTHETIC/ }).waitFor()
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => { const dark = theme === 'dark'; for (const [key, value] of Object.entries({ 'label-primary': dark ? '#eef2f7' : '#202730', 'label-secondary': dark ? '#b8c4d2' : '#536171', 'bg-layer-1': dark ? '#171d25' : '#fff', 'border-l2': dark ? '#364252' : '#dce3eb' })) document.documentElement.style.setProperty('--dsw-alias-' + key, value) }, theme)
    await page.screenshot({ path: resolve(output, theme + '.png'), fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  }
  await page.getByRole('button', { name: '逐笔交易', exact: true }).click()
  await page.getByRole('button', { name: '25', exact: true }).click()
  assert.equal(await page.getByRole('slider').first().inputValue(), '25')
  await page.getByRole('button', { name: '研究报告', exact: true }).click()
  await page.getByRole('heading', { name: '本次模拟研究记录' }).waitFor()
  await page.getByRole('button', { name: /backtest.*已完成/ }).click()
  await page.getByText('实际输入参数', { exact: true }).waitFor()
  await page.setViewportSize({ width: 560, height: 900 })
  await page.getByRole('button', { name: '行情与收益', exact: true }).click()
  await page.screenshot({ path: resolve(output, 'narrow.png'), fullPage: true })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  assert.deepEqual(errors, [])
  console.log('Quant production tab: synthetic fixture, light/dark/narrow, trade-to-chart drilldown and call details passed')
} catch (error) {
  console.error('Quant UI errors:', errors)
  throw error
} finally { await browser.close() }
