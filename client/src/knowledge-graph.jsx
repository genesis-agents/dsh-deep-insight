/** Interactive graph over saved enrichment data; the list exposes the same evidence to keyboard users. */
import React,{useEffect,useId,useMemo,useRef,useState} from 'react'
import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import {useT} from './locales.js'
import {EvidenceLinks} from './evidence-links.jsx'

cytoscape.use(fcose)

/**
 * Render nodes, directed relations and exact evidence without modifying the saved product.
 * @param props Saved result, selected batch, session identity and evidence navigation callback.
 * @returns Graph and accessible list with evidence details.
 */
export function KnowledgeGraph({result,detail,sessionId,onInspect}){
 const t=useT(),root=useRef(null),[query,setQuery]=useState(''),[view,setView]=useState('graph'),[selection,setSelection]=useState(null),[expanded,setExpanded]=useState(false),[fullscreenFailed,setFullscreenFailed]=useState(false)
 useEffect(()=>{
  const changed=()=>setExpanded(document.fullscreenElement===root.current)
  document.addEventListener('fullscreenchange',changed)
  return()=>document.removeEventListener('fullscreenchange',changed)
 },[])
 const fullscreen=async()=>{
  setFullscreenFailed(false)
  try{if(document.fullscreenElement===root.current)await document.exitFullscreen();else await root.current.requestFullscreen()}
  catch(error){setFullscreenFailed(true)}
 }
 const nodes=useMemo(()=>new Map(result.nodes.map((node,index)=>[node.id,{...node,index}])),[result])
 const visible=useMemo(()=>{
  const term=query.trim().toLocaleLowerCase(),matches=value=>value.toLocaleLowerCase().includes(term)
  const edges=result.edges.map((edge,index)=>({...edge,index})).filter(edge=>!term||matches(edge.relation)||matches(nodes.get(edge.source).label)||matches(nodes.get(edge.target).label))
  const endpoints=new Set(edges.flatMap(edge=>[edge.source,edge.target]))
  return {nodes:[...nodes.values()].filter(node=>!term||matches(node.label)||endpoints.has(node.id)),edges}
 },[query,result,nodes])
 const selectedNode=selection?.kind==='node'?result.nodes[selection.index]:null
 const selectedEdge=selection?.kind==='edge'?result.edges[selection.index]:null
 const relations=selectedNode?visible.edges.filter(edge=>edge.source===selectedNode.id||edge.target===selectedNode.id):[]
 const evidence=ids=><EvidenceLinks links={ids.map(evidence_id=>({evidence_id}))} detail={detail} sessionId={sessionId} onInspect={onInspect}/>
 const edgeLabel=edge=>`${nodes.get(edge.source).label} → ${edge.relation} → ${nodes.get(edge.target).label}`
 return <section ref={root} className="tech-knowledge" aria-label={t('graphTitle')} onKeyDown={event=>{if(event.key==='Escape'&&expanded){event.stopPropagation();event.preventDefault();if(document.fullscreenElement===root.current)document.exitFullscreen().catch(()=>setFullscreenFailed(true))}}}>
  <div className="tech-knowledge-heading"><div><h4>{t('graphTitle')}</h4><p>{result.nodes.length} {t('capGraphNodes')}<span>·</span>{result.edges.length} {t('capGraphRelations')}</p></div>{document.fullscreenEnabled&&<button className="tech-graph-expand" aria-pressed={expanded} onClick={fullscreen}>{t(expanded?'graphExitFullscreen':'graphFullscreen')}</button>}</div>
  <div className="tech-graph-toolbar">
   <div className="tech-graph-views" role="group" aria-label={t('graphView')}><button aria-pressed={view==='graph'} onClick={()=>setView('graph')}>{t('graphTitle')}</button><button aria-pressed={view==='list'} onClick={()=>setView('list')}>{t('graphList')}</button></div>
   <label className="tech-graph-search"><span className="tech-graph-sr">{t('graphSearch')}</span><input type="search" placeholder={t('graphSearch')} value={query} onChange={event=>{setQuery(event.target.value);setSelection(null)}}/></label>
  </div>
  {fullscreenFailed&&<p role="alert">{t('graphFullscreenFailed')}</p>}
  {query.trim()&&<p role="status">{t('graphMatches')} · {visible.nodes.length} {t('capGraphNodes')} · {visible.edges.length} {t('capGraphRelations')}</p>}
  {!result.nodes.length?<p>{t('graphEmpty')}</p>:!visible.nodes.length?<p>{t('graphNoMatch')}</p>:<>
   <div className="tech-graph-workspace" data-view={view}>
   {view==='graph'&&<GraphCanvas graph={visible} selection={selection} onSelect={setSelection}/>}
   <aside className="tech-graph-inspector" aria-label={t('graphInspector')}>
   <label className="tech-graph-select">{t('graphSelect')}<select value={selectedNode?.id??''} onChange={event=>{const node=nodes.get(event.target.value);setSelection(node?{kind:'node',index:node.index}:null)}}><option value="">{t('graphChoose')}</option>{visible.nodes.map(node=><option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
   {selection&&<section className="tech-graph-selection" aria-label={t('graphSelection')}>
    <div className="tech-graph-selection-heading"><div><span className="tech-graph-kind">{t(selectedNode?'graphNodeKind':'graphEdgeKind')}</span><h4>{selectedNode?.label??edgeLabel(selectedEdge)}</h4></div><button onClick={()=>setSelection(null)}>{t('graphClear')}</button></div>
    {evidence((selectedNode??selectedEdge).evidence_ids)}
    {selectedNode&&<><h4>{t('graphRelated')} · {relations.length}</h4>{relations.length?relations.map(edge=><button className="tech-graph-relation" key={edge.index} onClick={()=>setSelection({kind:'edge',index:edge.index})}>{edgeLabel(edge)}</button>):<p>{t('graphIsolated')}</p>}</>}
    {selectedEdge&&<div className="tech-graph-endpoints">{[selectedEdge.source,selectedEdge.target].map((id,index)=><button key={index} onClick={()=>setSelection({kind:'node',index:nodes.get(id).index})}>{nodes.get(id).label}</button>)}</div>}
   </section>}
   {!selection&&<div className="tech-graph-inspector-empty"><span className="tech-graph-empty-mark" aria-hidden="true"/><h4>{t('graphInspectHeading')}</h4><p>{t('graphInspectHelp')}</p></div>}
   </aside>
   </div>
   {view==='list'&&<div className="tech-graph-list"><h4>{t('graphNodeList')}</h4>{visible.nodes.map(node=><article key={node.id}><button aria-pressed={selectedNode?.id===node.id} onClick={()=>setSelection({kind:'node',index:node.index})}>{node.label}</button>{evidence(node.evidence_ids)}</article>)}<h4>{t('graphEdgeList')}</h4>{visible.edges.length?visible.edges.map(edge=><article key={edge.index}><button aria-pressed={selection?.kind==='edge'&&selection.index===edge.index} onClick={()=>setSelection({kind:'edge',index:edge.index})}>{edgeLabel(edge)}</button>{evidence(edge.evidence_ids)}</article>):<p>{t('graphNoEdges')}</p>}</div>}
  </>}
 </section>
}

/** Own the canvas, layout and observers for one mounted graph; failures leave the list available. */
function GraphCanvas({graph,selection,onSelect}){
 const t=useT(),canvas=useRef(null),palette=useRef(null),instance=useRef(null),[failed,setFailed]=useState(false),[attempt,setAttempt]=useState(0),[layoutName,setLayoutName]=useState('fcose'),[showLabels,setShowLabels]=useState(false),hint=useId()
 useEffect(()=>{
  let cy,layout,resize,theme,disposed=false
  const dispose=()=>{if(disposed)return;disposed=true;resize?.disconnect();theme?.disconnect();layout?.stop();cy?.destroy();instance.current=null}
  setFailed(false)
  try{
   const paint=document.createElement('canvas').getContext('2d')
   if(!paint)throw Error('Canvas renderer unavailable')
   const rgb=value=>{paint.clearRect(0,0,1,1);paint.fillStyle=value;paint.fillRect(0,0,1,1);const [r,g,b]=paint.getImageData(0,0,1,1).data;return `rgb(${r},${g},${b})`}
   const colors=()=>{const style=getComputedStyle(palette.current);return {ink:rgb(style.color),bg:rgb(style.backgroundColor),accent:rgb(style.borderTopColor),muted:rgb(style.outlineColor)}}
   const stylesheet=()=>{
    const {ink,bg,accent,muted}=colors()
    return [
     {selector:'node',style:{label:'data(label)',shape:'ellipse',width:'data(size)',height:'data(size)','background-color':accent,'background-opacity':0.9,'border-color':bg,'border-width':3,color:ink,'font-family':'sans-serif','font-size':14,'font-weight':400,'text-valign':'bottom','text-margin-y':8,'text-wrap':'ellipsis','text-max-width':124,'text-background-color':bg,'text-background-opacity':0.9,'text-background-padding':2,'min-zoomed-font-size':8}},
     {selector:'node[degree = 0]',style:{'background-color':muted,'background-opacity':0.12,'border-color':muted,'border-width':1,'border-style':'dashed',color:muted}},
     {selector:'edge',style:{label:'data(label)',width:1.2,'curve-style':'bezier','target-arrow-shape':'triangle','arrow-scale':0.7,'line-color':muted,'target-arrow-color':muted,'line-opacity':0.35,'target-arrow-opacity':0.5,color:muted,'font-family':'sans-serif','font-size':12,'text-opacity':0,'text-wrap':'ellipsis','text-max-width':144,'text-background-color':bg,'text-background-opacity':1,'text-background-padding':4}},
     {selector:'edge:loop',style:{'control-point-step-size':64}},
     {selector:'edge.show-labels',style:{'text-opacity':0.9}},
     {selector:'.dim',style:{opacity:0.16}},
     {selector:'edge.dim',style:{'text-opacity':0}},
     {selector:'edge.focus-edge',style:{width:2,'line-color':accent,'target-arrow-color':accent,'line-opacity':0.95,'target-arrow-opacity':1,color:ink,'font-size':14}},
     {selector:'edge:selected',style:{'text-opacity':1}},
     {selector:'node:selected',style:{'border-width':3,'border-style':'solid','border-color':accent,'background-color':accent,'background-opacity':1,'underlay-color':accent,'underlay-opacity':0.12,'underlay-padding':7,'text-opacity':1,'font-weight':500}},
    ]
   }
   const ids=new Map(graph.nodes.map(node=>[node.id,'node-'+node.index]))
   const degrees=new Map(graph.nodes.map(node=>[node.id,0]))
   for(const edge of graph.edges){degrees.set(edge.source,degrees.get(edge.source)+1);degrees.set(edge.target,degrees.get(edge.target)+1)}
   cy=cytoscape({container:canvas.current,elements:[...graph.nodes.map(node=>({data:{id:ids.get(node.id),label:node.label,index:node.index,kind:'node',degree:degrees.get(node.id),size:degrees.get(node.id)?24+Math.min(degrees.get(node.id),8)*2:20}})),...graph.edges.map(edge=>({data:{id:'edge-'+edge.index,source:ids.get(edge.source),target:ids.get(edge.target),label:edge.relation,index:edge.index,kind:'edge'}}))],style:stylesheet(),layout:{name:'grid'},minZoom:0.1,maxZoom:3,boxSelectionEnabled:false,selectionType:'single',wheelSensitivity:0.3})
   instance.current=cy
   layout=cy.layout(layoutName==='circle'?{name:'circle',animate:false,nodeDimensionsIncludeLabels:true,padding:40,spacingFactor:0.8,sort:(a,b)=>b.degree()-a.degree()}:{name:'fcose',quality:'proof',animate:false,randomize:false,nodeDimensionsIncludeLabels:true,packComponents:false,padding:40,nodeRepulsion:()=>4500,idealEdgeLength:()=>100,tile:true,tilingPaddingHorizontal:48,tilingPaddingVertical:48})
   layout.run()
   cy.on('tap','node, edge',event=>onSelect({kind:event.target.data('kind'),index:event.target.data('index')}))
   cy.on('tap',event=>{if(event.target===cy)onSelect(null)})
   resize=new ResizeObserver(()=>{cy.resize();cy.fit(undefined,32)})
   resize.observe(canvas.current)
   theme=new MutationObserver(()=>cy.style(stylesheet()))
   for(let ancestor=canvas.current.parentElement;ancestor;ancestor=ancestor.parentElement)theme.observe(ancestor,{attributes:true,attributeFilter:['class','style','data-theme','data-color-scheme']})
  }catch(error){
   // Canvas/layout initialization may fail on unsupported renderers; textual evidence remains usable.
   dispose();setFailed(true)
  }
  return dispose
 },[graph,attempt,layoutName,onSelect])
 useEffect(()=>{
  const cy=instance.current
  if(!cy)return
  cy.batch(()=>{
   cy.elements().unselect().removeClass('dim focus-edge')
   cy.edges().toggleClass('show-labels',showLabels)
   if(selection){
    const selected=cy.getElementById(selection.kind+'-'+selection.index)
    selected.select()
    if(selected.isNode())selected.connectedEdges().addClass('focus-edge');else selected.addClass('focus-edge')
    cy.elements().difference(selected.closedNeighborhood()).addClass('dim')
   }
  })
 },[selection,graph,attempt,layoutName,showLabels])
 const zoom=factor=>{const cy=instance.current;if(cy)cy.zoom({level:Math.max(cy.minZoom(),Math.min(cy.maxZoom(),cy.zoom()*factor)),renderedPosition:{x:cy.width()/2,y:cy.height()/2}})}
 return <div className="tech-graph-visual">
  <span className="tech-graph-palette" ref={palette} aria-hidden="true"/>
  <div className="tech-graph-tools" role="group" aria-label={t('graphNavigation')}><div><button disabled={failed} onClick={()=>zoom(1.25)}>{t('graphZoomIn')}</button><button disabled={failed} onClick={()=>zoom(0.8)}>{t('graphZoomOut')}</button><button disabled={failed} onClick={()=>instance.current?.fit(undefined,32)}>{t('graphFit')}</button><button disabled={failed} aria-pressed={showLabels} onClick={()=>setShowLabels(value=>!value)}>{t('graphLabels')}</button></div><label><span className="tech-graph-sr">{t('graphLayout')}</span><select value={layoutName} onChange={event=>setLayoutName(event.target.value)}><option value="fcose">{t('graphForce')}</option><option value="circle">{t('graphCircle')}</option></select></label></div>
  {failed&&<p role="alert">{t('graphFailed')} <button onClick={()=>setAttempt(value=>value+1)}>{t('graphRetry')}</button></p>}
  <div ref={canvas} className="tech-graph-canvas" hidden={failed} role="img" aria-label={t('graphTitle')} aria-describedby={hint}/>
  <div className="tech-graph-legend"><span><i/>{t('graphConnected')}</span><span><i className="tech-graph-legend-isolated"/>{t('graphIndependent')}</span><span>{t('graphSizeHelp')}</span></div>
  <p id={hint} className="tech-graph-help">{t('graphHelp')}</p>
 </div>
}
