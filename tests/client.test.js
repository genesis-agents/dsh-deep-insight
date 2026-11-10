import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import {JSDOM} from 'jsdom'
import {createRequire} from 'node:module'
import {state} from './research-fixture.js'

test('one workflow opens distinct node data in one host sidebar and retains report evidence',{timeout:15000},async t=>{
 const dom=new JSDOM('<html><body></body></html>',{url:'http://localhost:3081'}),previous=new Map()
 for(const [key,value] of Object.entries({window:dom.window,document:dom.window.document,navigator:dom.window.navigator,HTMLElement:dom.window.HTMLElement})){previous.set(key,Object.getOwnPropertyDescriptor(globalThis,key));Object.defineProperty(globalThis,key,{configurable:true,value})}
 const require=createRequire(import.meta.url),React=require('react'),{render,fireEvent,waitFor,cleanup,act}=require('@testing-library/react'),entries=[],dicts={},polls=[],opened=[],folderCalls=[]
 let plugin,fail=false,navigation,closed=0,hidden=[]
 const fixture=structuredClone(state)
 fixture.capabilityCatalog=['dedup','normalize','entities','structure','vectors','trend','benchmark','impact','knowledge','alerts']
 fixture.details[0].delivery=null
 fixture.details[0].analysis.narrative.sections[0].blocks.find(block=>block.kind==='figure').image_artifact_id='original-image'
 fixture.details[0].events=[{kind:'source_image_archived',payload:{source_version_id:'v0',unit_index:1,image_artifact_id:'original-image',path:'.source-figures/original-image.png'}}]
 const ctx={locale:{register:(key,value)=>{dicts[key]=value;return()=>{}},bind:key=>name=>dicts[key].zh[name]},effect:fn=>fn(),slots:{inject:(_name,fn)=>fn(),register:(entry,component)=>{entries.push({...entry,component});return()=>{}}},sidebarRight:{hide:id=>hidden.push(id),openResourceIn:(sessionId,address,options)=>opened.push({sessionId,address,options})},sidebarRightTabs:{register:()=>()=>{}}}
 try{
  vm.runInNewContext(readFileSync(new URL('../client/index.js',import.meta.url),'utf8'),{window:{location:dom.window.location,__ModuleLoader__:{load:({factory})=>{plugin=factory(()=>React)}}},document:dom.window.document,fetch:async(url,options)=>{if(url==='/open-in-app/apps')return{ok:true,json:async()=>({apps:['explorer']})};if(url==='/open-in-app/open'){folderCalls.push(JSON.parse(options.body));return{ok:true,json:async()=>({})}};if(fail)throw Error('Synthetic offline');if(options?.method==='POST'&&JSON.parse(options.body).action==='reading-room')return{ok:true,json:async()=>({result:{projectDirectory:'/fixture/project'}})};if(String(url).startsWith('/deep-insight/document?')){const version=new URL(url,'http://localhost').searchParams.get('version');const quotes=fixture.details[0].evidence.filter(item=>item.source_version_id===version);return {ok:true,json:async()=>({units:quotes.map(item=>({index:item.locator.unit_index,kind:'document',text:' '.repeat(item.locator.char_start??0)+item.quote+(item.quote.endsWith('。')?'':'.')})),warnings:[]})}};if(String(url).startsWith('/deep-insight/interpretation?'))return{ok:true,json:async()=>({record:null})};return{ok:true,json:async()=>structuredClone(fixture)}},AbortController,URL,console,setTimeout:fn=>{polls.push(fn);return polls.length},clearTimeout:()=>{},Date})
  plugin.apply(ctx)
  const panel=entries.find(entry=>entry.id==='deep-insight'),view=render(React.createElement(panel.component,panel.inject('fixture')))
  await waitFor(()=>assert.ok(view.getByRole('heading',{name:fixture.binding.question})))
  assert.equal(view.queryAllByRole('tab').length,0)
  assert.equal(view.container.querySelectorAll('.tech-lane').length,5)
  const folder=view.getByRole('button',{name:'打开研究目录'}),batch=view.getByRole('combobox',{name:'当前研究批次'})
  assert.ok(folder.compareDocumentPosition(batch)&dom.window.Node.DOCUMENT_POSITION_FOLLOWING)
  fireEvent.click(folder);await waitFor(()=>assert.equal(folderCalls.length,1));assert.equal(folderCalls[0].path,'/fixture/project')
  for(const node of view.container.querySelectorAll('.tech-node'))fireEvent.click(node)
  assert.equal(opened.length,view.container.querySelectorAll('.tech-node').length)
  assert.ok(opened.every(call=>call.sessionId==='fixture'&&call.options.destination==='sidebar'&&call.options.params.deepInsight.runId==='visual'))
  const sidebar=entries.find(entry=>entry.key==='dsh-deep-insight/research')
  const choose=id=>{fireEvent.click(view.container.querySelector('[data-node="'+id+'"]'));navigation=opened.at(-1)}
  choose('capture')
  const props=()=>({useTabInfo:()=>({tab:{id:'insight-detail',actions:{close:()=>{closed++}},visible:true,contentId:navigation.address,navigation:{params:navigation.options.params}}})})
  const sideContainer=document.createElement('div');document.body.append(sideContainer)
  const pane=render(React.createElement(sidebar.component,props()),{container:sideContainer,baseElement:sideContainer})
  assert.ok(pane.getByRole('heading',{name:'采集计划与执行观察'}))
  assert.ok(pane.getAllByText('合成验收资料 1',{exact:true}).length>0)
  t.assert.snapshot({node:'capture',content:pane.getByRole('region',{name:'节点详情内容'}).textContent.replace(/\s+/g,' ').trim()})
  choose('synthesis');pane.rerender(React.createElement(sidebar.component,props()))
  assert.ok(pane.getByRole('heading',{name:'已保存的综合分析'}))
  assert.ok(pane.getByRole('heading',{name:fixture.details[0].analysis.claims[0].statement}))
  assert.equal(pane.queryByText('合成验收资料 1',{exact:true}),null)
  t.assert.snapshot({node:'synthesis',content:pane.getByRole('region',{name:'节点详情内容'}).textContent.replace(/\s+/g,' ').trim()})
  const claim=fixture.details[0].analysis.claims[0],originalLinks=claim.evidence_links
  const extra={...fixture.details[0].evidence[0],evidence_id:'e0-extra',quote:'同一来源的另一段原文',locator:{unit_index:2,char_start:30,char_end:42}}
  fixture.details[0].evidence.push(extra)
  claim.evidence_links=[...originalLinks,{evidence_id:'e0',relation:'supports'},{evidence_id:extra.evidence_id,relation:'supports'},{evidence_id:'missing-evidence',relation:'context'}]
  await act(async()=>{await panel.inject('fixture').feed.refresh()})
  const groups=pane.container.querySelectorAll('.tech-evidence-group'),first=groups[0]
  assert.match(first.querySelector('summary').textContent,/合成验收资料 1.*2 条引文/)
  assert.equal(first.querySelectorAll('blockquote').length,0)
  assert.equal(first.open,false)
  fireEvent.click(first.querySelector('summary'))
  await waitFor(()=>assert.equal(first.querySelectorAll('blockquote').length,2))
  fireEvent.click(first.querySelectorAll('.tech-exact-citations>summary')[1])
  fireEvent.click(first.querySelectorAll('.tech-exact-citations button')[1]);navigation=opened.at(-1)
  assert.equal(navigation.options.params.deepInsight.nodeId,'evidence')
  assert.equal(navigation.options.params.deepInsight.recordId,extra.evidence_id)
  assert.equal(navigation.options.params.deepInsight.runId,'visual')
  const missing=pane.getByRole('alert').closest('details')
  assert.match(missing.textContent,/关联的证据记录缺失：.*missing-evidence/)
  assert.equal(missing.querySelectorAll('button').length,0)
  fixture.details[0].evidence.pop();claim.evidence_links=originalLinks
  await act(async()=>{await panel.inject('fixture').feed.refresh()})
  choose('vectors');pane.rerender(React.createElement(sidebar.component,props()))
  assert.ok(pane.getByRole('button',{name:'等待当前操作结束'}).disabled)
  fixture.current=null
  await act(async()=>{await panel.inject('fixture').feed.refresh()})
  assert.ok(pane.getByRole('button',{name:'执行本环节'}))
  assert.equal(pane.queryByRole('heading',{name:'已保存的综合分析'}),null)
  choose('entities');pane.rerender(React.createElement(sidebar.component,props()))
  assert.ok(pane.getByText('本批次尚未生成此环节的结果'))
  choose('report');pane.rerender(React.createElement(sidebar.component,props()))
  assert.ok(pane.getByRole('heading',{name:fixture.details[0].analysis.narrative.headline}))
  assert.ok(pane.getByText('Synthetic final conclusion',{exact:true}))
  assert.match(pane.getByRole('img',{name:'合成原始材料页面'}).getAttribute('src'),/original-image\.png$/)
  t.assert.snapshot({node:'report',content:pane.getByRole('region',{name:'节点详情内容'}).textContent.replace(/\s+/g,' ').trim()})
  assert.equal(pane.container.querySelector('.ri-report .tech-evidence-groups'),null)
  const paragraph={kind:'paragraph',text:'',claim_ids:['c0']};fixture.details[0].analysis.narrative.sections[0].blocks.push(paragraph)
  paragraph.text='A sentence with an exact source.{{evidence:e0}} An unavailable reference stays visible.{{evidence:other-batch}}'
  await act(async()=>{await panel.inject('fixture').feed.refresh()})
  const footnote=pane.getByRole('button',{name:'查看原文详情 1'})
  assert.equal(footnote.closest('sup').className,'ri-inline-citations')
  assert.ok(pane.getByText(/\{\{evidence:other-batch\}\}/))
  fireEvent.click(footnote);navigation=opened.at(-1)
  assert.equal(navigation.options.params.deepInsight.nodeId,'evidence')
  assert.equal(navigation.options.params.deepInsight.recordId,'e0')
  fixture.details[0].analysis.narrative.sections[0].blocks.pop()
  await act(async()=>{await panel.inject('fixture').feed.refresh()})
  choose('evidence');pane.rerender(React.createElement(sidebar.component,props()))
  assert.equal(pane.container.querySelectorAll('.tech-detail-section').item(0).querySelectorAll('.tech-evidence-group').length,10)
  t.assert.snapshot({node:'evidence',content:pane.getByRole('region',{name:'节点详情内容'}).textContent.replace(/\s+/g,' ').trim()})
  choose('alerts');pane.rerender(React.createElement(sidebar.component,props()))
  assert.ok(pane.getByRole('button',{name:'创建订阅'}))
  assert.equal(pane.queryByRole('heading',{name:'已保存的综合分析'}),null)
  fixture.details[0].input_snapshot.sources[0].resource_uri='https://www.youtube.com/watch?v=M7lc1UVf-VE'
  fixture.details[0].evidence[0].start_seconds=83
  await act(async()=>{await panel.inject('fixture').feed.refresh()})
  choose('lane:sources');pane.rerender(React.createElement(sidebar.component,props()))
  const player=pane.getByTitle('来源视频播放器')
  assert.match(player.getAttribute('src'),/youtube.com\/embed\/M7lc1UVf-VE/)
  fireEvent.click(pane.getByRole('button',{name:'跳转至 1:23'}))
  assert.match(pane.getByTitle('来源视频播放器').getAttribute('src'),/start=83/)
  fireEvent.click(pane.getByRole('button',{name:'收起视频'}))
  assert.equal(pane.queryByTitle('来源视频播放器'),null)
  fireEvent.click(pane.getByRole('button',{name:'关闭详情'}));assert.deepEqual(hidden,['insight-detail']);assert.equal(closed,0)
  fireEvent.keyDown(pane.getByRole('region',{name:'节点详情内容'}),{key:'Escape'});assert.deepEqual(hidden,['insight-detail','insight-detail']);assert.equal(closed,0)
  pane.unmount()
  fail=true;await act(async()=>{await panel.inject('fixture').feed.refresh()});assert.ok(view.getByRole('alert'))
  assert.equal(view.container.querySelectorAll('.tech-lane').length,5)
  assert.equal(view.container.querySelectorAll('.tech-node[data-updated=true]').length,0)
  fail=false;await act(async()=>{fireEvent.click(view.getByRole('button',{name:'刷新'}))});assert.equal(view.queryByRole('alert'),null)
  view.unmount()
  fail=true;const failed=render(React.createElement(panel.component,panel.inject('first-failure')))
  await waitFor(()=>assert.ok(failed.getByRole('alert')))
  assert.equal(failed.container.querySelectorAll('.tech-lane').length,0)
  fail=false;fireEvent.click(failed.getByRole('button',{name:'刷新'}));await waitFor(()=>assert.equal(failed.container.querySelectorAll('.tech-lane').length,5))
 }finally{cleanup();dom.window.close();for(const [key,value]of previous){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key]}}
})
