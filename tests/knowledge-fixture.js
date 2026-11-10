/** Synthetic saved graph covering isolated nodes, cycles, duplicate labels and long labels. */
export const knowledgeResult={
 nodes:[
  {id:'source:#[]',label:'原始材料',evidence_ids:['e0']},
  {id:'evidence',label:'原文证据',evidence_ids:['e1']},
  {id:'claim',label:'研究判断',evidence_ids:['e2']},
  {id:'isolated',label:'孤立节点：保留没有关系但具有证据的知识',evidence_ids:['e3']},
  {id:'duplicate',label:'原文证据',evidence_ids:['e4']},
 ],
 edges:[
  {source:'source:#[]',target:'evidence',relation:'提取',evidence_ids:['e0','e1']},
  {source:'evidence',target:'claim',relation:'支持',evidence_ids:['e1','e2']},
  {source:'claim',target:'evidence',relation:'核查',evidence_ids:['e2']},
  {source:'source:#[]',target:'evidence',relation:'版本定位',evidence_ids:['e0']},
  {source:'claim',target:'claim',relation:'适用条件与限制',evidence_ids:['e2']},
 ],
 limitations:['合成验收数据，不代表真实研究结论'],review_state:'unreviewed',
}
export const knowledgeRecord={id:'graph-fixture',kind:'structure',status:'completed',result:knowledgeResult}
