/** Host registrations own subscriptions and locale dictionaries; research and Quant stay isolated. */
import React from 'react'
import {createFeed} from './feed.js'
import {ResearchPage} from './research.jsx'
import {QuantPage} from './quant.jsx'
import {zh,en} from './locales.js'
import {StageSidebar,FlowIcon} from './tech-workflow.jsx'
export const name='deep-insight'
export const inject=['slots','sidebarRight','sidebarRightTabs','locale']
export function apply(ctx) {
  ctx.effect(()=>ctx.locale.register('deepInsight',{zh,en}),'deep-insight: locales')
  const t=ctx.locale.bind('deepInsight'),feeds=new Map(),inspectors=new Map()
  ctx.effect(()=>()=>{for(const feed of feeds.values())feed.dispose();feeds.clear();inspectors.clear()},'deep-insight: session views')
  function inspectFor(sessionId){
    if(!inspectors.has(sessionId))inspectors.set(sessionId,(nodeId,runId,recordId)=>ctx.sidebarRight.openResourceIn(sessionId,'dsh-resource://deep-insight/'+encodeURIComponent(sessionId),{kind:'deep-insight-research',destination:'sidebar',params:{deepInsight:{nodeId,runId,recordId}}}))
    return inspectors.get(sessionId)
  }
  function getFeed(id,quant=false) {
    const key=quant?'quant:'+id:id
    if(!feeds.has(key)) {
      if(feeds.size>=20)for(const [old,feed] of feeds){if(!feed.active()){feed.dispose();feeds.delete(old);break}}
      feeds.set(key,createFeed(id,quant?async(sessionId,signal)=>{
        const response=await fetch('/deep-insight/quant?session='+encodeURIComponent(sessionId),{signal,cache:'no-store'}),value=await response.json()
        if(!response.ok)throw Error(value.error?.message??`HTTP ${response.status}`)
        return value
      }:undefined))
    }
    return feeds.get(key)
  }
  ctx.slots.inject('conversation.view',()=>ctx.slots.register({name:'conversation.view',id:'deep-insight',locale:'deepInsight',label:()=>t('title'),order:20,inject:sessionId=>({sessionId,feed:getFeed(sessionId),t,onInspect:inspectFor(sessionId)})},ResearchPage))
  ctx.slots.inject('conversation.view',()=>ctx.slots.register({name:'conversation.view',id:'quant-research',label:()=> '量化研究',order:21,inject:sessionId=>({sessionId,feed:getFeed(sessionId,true)})},QuantPage))
  const sidebarId='dsh-deep-insight/research'
  ctx.effect(()=>ctx.sidebarRightTabs.register({id:sidebarId,kind:'deep-insight-research',closeBehavior:'hide',patterns:['dsh-resource://deep-insight/**'],title:()=>t('techDetails')}),'deep-insight: sidebar')
  function Sidebar({useTabInfo}){const {tab}=useTabInfo(),address=new URL(tab.contentId),sessionId=decodeURIComponent(address.pathname.slice(1)),selection=tab.navigation?.params?.deepInsight;return <StageSidebar feed={getFeed(sessionId)} sessionId={sessionId} selection={selection??{nodeId:'output'}} active={tab.visible!==false} onInspect={inspectFor(sessionId)} onClose={()=>ctx.sidebarRight.hide(tab.id)} t={t}/>}
  ctx.effect(()=>ctx.slots.inject('sidebar.right.pane.tab',()=>ctx.slots.register({name:'sidebar.right.pane.tab',key:sidebarId},Sidebar)),'deep-insight: sidebar content')
  function SidebarTitle(){return <span style={{display:'inline-flex',alignItems:'center',gap:6}}><FlowIcon name="branch-outline" size={16}/>{t('techDetails')}</span>}
  ctx.effect(()=>ctx.slots.inject('sidebar.right.pane.tab.title',()=>ctx.slots.register({name:'sidebar.right.pane.tab.title',key:sidebarId},SidebarTitle)),'deep-insight: sidebar title')
}
