/** Render production components with explicitly synthetic research data, never a live user session. */
import { readFile, mkdir } from 'node:fs/promises'
import { resolve, dirname, relative, extname } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = await import(process.env.PIES_PLAYWRIGHT ? pathToFileURL(resolve(process.env.PIES_PLAYWRIGHT)).href : 'playwright')
const reactRequire = createRequire(require.resolve('@testing-library/react'))
const react = dirname(reactRequire.resolve('react/package.json'))
const reactDom = dirname(reactRequire.resolve('react-dom/package.json'))
const output = resolve('.cache/insight-review')
const recorded = process.env.PIES_REVIEW_SNAPSHOT ? JSON.parse((await readFile(process.env.PIES_REVIEW_SNAPSHOT, 'utf8')).replace(/^\uFEFF/, '')) : null
await mkdir(output, { recursive: true })
const {state} = await import('./research-fixture.js')
const {transform}=await import('esbuild')
const artwork=await transform(await readFile(resolve('packages/client/ui-primitives/src/icons/artwork.ts'),'utf8'),{loader:'ts',format:'cjs'})
const iconModule={exports:{}}
new Function('module','exports',artwork.code)(iconModule,iconModule.exports)
const browser = await chromium.launch({ headless: true })
const errors = []
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  if (recorded) await page.route('https://fixture.invalid/**', async route => {
    const asset = decodeURIComponent(new URL(route.request().url()).pathname.split('/').slice(5).join('/'))
    const root = recorded.state.storage.workspace, file = resolve(root, asset)
    if (relative(root, file).startsWith('..') || !['.png', '.svg', '.jpg'].includes(extname(file))) return route.fulfill({ status: 404, body: '' })
    return route.fulfill({ contentType: extname(file) === '.svg' ? 'image/svg+xml' : extname(file) === '.png' ? 'image/png' : 'image/jpeg', body: await readFile(file) })
  })
  else
  await page.route('https://fixture.invalid/**', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="340"><rect width="600" height="340" fill="#f1f5f9"/><text x="40" y="65" font-size="26">Synthetic source page</text><rect x="40" y="110" width="220" height="120" fill="#3979d9"/><rect x="300" y="150" width="200" height="80" fill="#198b82"/><text x="40" y="290" font-size="18">Fixture only / No research claims</text></svg>' }))
  await page.setContent('<!doctype html><html><head><base href="https://fixture.invalid/"></head><body><div id="app"></div></body></html>')
  await page.evaluate(symbols=>{
    const ns='http://www.w3.org/2000/svg',sprite=document.createElementNS(ns,'svg')
    sprite.style.cssText='position:absolute;width:0;height:0;overflow:hidden'
    for(const [id,markup] of Object.entries(symbols)){
      const root=new DOMParser().parseFromString(markup,'image/svg+xml').documentElement,symbol=document.createElementNS(ns,'symbol')
      symbol.id=id
      for(const {name,value} of root.attributes)if(!['xmlns','width','height','class','aria-hidden'].includes(name))symbol.setAttribute(name,value)
      symbol.append(...[...root.childNodes].map(node=>document.importNode(node,true)));sprite.append(symbol)
    }
    document.body.prepend(sprite)
  },iconModule.exports.ICON_SYMBOLS)
  await page.addStyleTag({ content: '#sidebar{position:fixed;inset:0 0 0 auto;width:min(480px,100vw);height:100dvh;overflow:hidden;z-index:5;background:var(--dsw-alias-bg-layer-1)}#sidebar:empty,#sidebar[hidden]{display:none}body{margin:0;font-family:Arial,"Microsoft Yahei",sans-serif;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary)}' })
  await page.addScriptTag({ path: resolve(react, 'umd/react.development.js') })
  await page.addScriptTag({ path: resolve(reactDom, 'umd/react-dom.development.js') })
  await page.evaluate(({ state, previews }) => {
    window.fixture = state
    window.fetch = async (_url, options) => { const url=new URL(_url,'https://fixture.invalid');if(url.pathname==='/deep-insight/document'){const version=url.searchParams.get('version'),units=new Map();for(const item of window.fixture.details.at(-1).evidence.filter(item=>item.source_version_id===version)){const index=item.locator.unit_index;units.set(index,(units.get(index)??'')+' '.repeat(item.locator.char_start??0)+item.quote+' ')}return {ok:true,json:async()=>({units:[...units].map(([index,text])=>({index,text,kind:'document'})),warnings:[]})}}if(url.pathname==='/deep-insight/interpretation')return {ok:true,json:async()=>({record:null})};return {ok:true,json:async()=>options?.method==='POST'?previews:JSON.parse(JSON.stringify(window.fixture))} }
    window.__ModuleLoader__ = { load({ factory }) {
      const plugin = factory(name => { if (name === 'react') return window.React; throw new Error(name) })
      const dictionaries = {}; let pane, navigation, sidebar; const side=document.createElement('aside');side.id='sidebar';document.body.append(side)
      plugin.apply({ locale: {register: (key,value) => {dictionaries[key]=value;return ()=>{}},bind: key => name => dictionaries[key].zh[name]}, effect: fn => fn(), sidebarRightTabs: { register: () => () => {} }, sidebarRight: { openResourceIn(sessionId,address,options){window.nodeSelection={sessionId,address,options};side.hidden=false;navigation={contentId:address,navigation:{params:options.params},visible:true,actions:{close(){pane?.unmount();pane=null;side.hidden=true}}};pane??=window.ReactDOM.createRoot(side);pane.render(window.React.createElement(sidebar,{useTabInfo:()=>({tab:navigation})}))} }, slots: {
        inject: (_name, fn) => fn(), register(entry, component) { if(entry.name==='sidebar.right.pane.tab')sidebar=component; if (entry.name === 'conversation.view' && entry.id === 'deep-insight') window.ReactDOM.createRoot(document.getElementById('app')).render(window.React.createElement(component, entry.inject('visual'))) },
      } })
    } }
  }, recorded ?? { state, previews: {} })
  await page.addScriptTag({ content: await readFile(new URL('../client/index.js', import.meta.url), 'utf8') })

  await page.locator('.tech-lane').first().waitFor()
  assert.equal(await page.getByRole('tab').count(),0)
  assert.equal(await page.locator('.tech-lane').count(),5)
  assert.equal(await page.locator('.tech-data-routes circle').count(),0)
  const inspect=async id=>{
    if(await page.locator('.tech-stage-detail').isVisible())await page.getByRole('button',{name:'关闭详情',exact:true}).click()
    const node=page.locator(`[data-node="${id}"]`).first()
    await node.scrollIntoViewIfNeeded();await node.click()
    await page.locator('.tech-stage-detail').waitFor()
    assert.equal(await page.locator('.tech-stage-detail').getAttribute('data-detail-node'),id)
    assert.equal(await page.locator('.tech-stage-detail').count(),1)
  }
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>{const dark=theme==='dark';for(const [key,value] of Object.entries({'label-primary':dark?'#eef2f7':'#202730','label-secondary':dark?'#b8c4d2':'#536171','bg-layer-1':dark?'#171d25':'#ffffff','border-l2':dark?'#364252':'#dce3eb'}))document.documentElement.style.setProperty('--dsw-alias-'+key,value)},theme)
    for(const width of [1440,620,390]){
      await page.setViewportSize({width,height:1000})
      await page.screenshot({path:resolve(output,`${theme}-${width}-workflow.png`),fullPage:true})
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`)
    }
  }
  await page.setViewportSize({width:1440,height:1000})
  if(await page.locator('.tech-unavailable>summary').count())await page.locator('.tech-unavailable>summary').click()
  for(const id of await page.locator('.tech-node').evaluateAll(nodes=>nodes.map(node=>node.dataset.node)))await inspect(id)
  await inspect('report')
  const report=page.locator('.tech-stage-detail')
  const scroll=report.getByRole('region',{name:'节点详情内容'})
  await scroll.hover();await page.mouse.wheel(0,1000)
  await page.waitForFunction(()=>document.querySelector('.tech-detail-body').scrollTop>0)
  assert(await report.getByRole('button',{name:'关闭详情',exact:true}).isVisible())
  await scroll.evaluate(element=>element.scrollTop=0)
  await report.locator('img').evaluateAll(images=>Promise.all(images.map(img=>{img.loading='eager';return img.decode()})))
  assert(await report.locator('.ri-original img').count()>0)
  await page.screenshot({path:resolve(output,'report-reader.png'),fullPage:true})
  await report.locator('.ri-bibliography button').first().click()
  await page.locator('[data-detail-node="lane:sources"]').waitFor()
  const sources=(recorded?.state??state).details.at(-1).input_snapshot.sources
  assert.equal(await page.locator('.tech-stage-detail').getByRole('heading',{name:sources[0].title,exact:true}).count(),1)
  assert.equal(await page.locator('.tech-stage-detail').getByRole('heading',{name:sources[1].title,exact:true}).count(),0)
  await inspect('evidence')
  assert.equal(await page.locator('.tech-detail-section').first().locator('.tech-evidence-group').count(),state.details[0].input_snapshot.sources.length)
  await page.evaluate(()=>{const d=window.fixture.details.at(-1);d.source_versions.push({...d.source_versions[0],version_id:'visual-update',raw_artifact_id:'raw-update',extracted_artifact_id:'text-update'})})
  await page.locator('.tech-node[data-updated=true]').first().waitFor({timeout:15000})
  await page.emulateMedia({reducedMotion:'reduce'})
  assert.equal(await page.locator('.tech-data-routes circle').first().evaluate(node=>getComputedStyle(node).display),'none')
  await page.emulateMedia({reducedMotion:'no-preference'})
  await page.getByRole('button',{name:'关闭详情',exact:true}).click()
  await page.getByRole('button',{name:'放大流程图',exact:true}).click()
  await page.getByRole('button',{name:'重置视图',exact:true}).click()
  await page.evaluate(()=>{
    const d=window.fixture.details.at(-1),claim=d.analysis.claims[0]
    claim.evidence_links=Array.from({length:13},(_,i)=>{
      const evidence={...d.evidence[i<6?0:1],evidence_id:'caption-'+i,quote:'Synthetic caption '+i+': a distinct passage retained for exact navigation.'}
      d.evidence.push(evidence)
      return {evidence_id:evidence.evidence_id,relation:'supports'}
    })
  })
  await page.getByRole('button',{name:'刷新',exact:true}).click()
  await inspect('synthesis')
  const firstClaim=page.locator('.tech-detail-section article').nth(0)
  await page.waitForFunction(()=>document.querySelector('.tech-evidence-count')?.textContent.includes('6'))
  assert.equal(await firstClaim.locator('.tech-evidence-group').count(),2)
  assert.equal(await firstClaim.locator('button:visible').count(),0)
  await firstClaim.locator('summary').first().click()
  await firstClaim.locator('blockquote').first().waitFor();assert.equal(await firstClaim.locator('blockquote').count(),6)
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>{const dark=theme==='dark';for(const [key,value] of Object.entries({'label-primary':dark?'#eef2f7':'#202730','label-secondary':dark?'#b8c4d2':'#536171','bg-layer-1':dark?'#171d25':'#ffffff','border-l2':dark?'#364252':'#dce3eb'}))document.documentElement.style.setProperty('--dsw-alias-'+key,value)},theme)
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:1000})
      assert.equal(await page.locator('.tech-detail-body').evaluate(el=>el.scrollWidth>el.clientWidth),false)
      await page.screenshot({path:resolve(output,`${theme}-${width}-evidence-groups.png`)})
    }
  }
  await firstClaim.locator('.tech-exact-citations>summary').nth(5).click()
  await firstClaim.locator('.tech-exact-citations button').nth(5).click()
  await page.locator('[data-detail-node="evidence"]').waitFor()
  await page.locator('.tech-stage-detail blockquote').waitFor()
  assert.match(await page.locator('.tech-stage-detail blockquote').textContent(),/Synthetic caption 5:/)
  assert.deepEqual(errors,[])
  console.log('Production-component fixture passed: all node details, report/source/evidence navigation, themes, narrow layouts, updates and reduced motion. '+output)
}finally{await browser.close()}
