const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(){
 const nodes=new Map(),calls={sent:0,events:0,close:0,view:[],focus:0,toasts:[]};
 const get=id=>{if(!nodes.has(id))nodes.set(id,{open:true,value:'',dispatchEvent(){calls.events++;},close(){calls.close++;this.open=false;},focus(){calls.focus++;}});return nodes.get(id);};
 const e={source_id:'s',source_name:'原资料',locator:'第 9 页',quote:'若 $m>0$，可由 $F=ma$ 得到 $a=F/m$。'};
 const graph={concepts:[{id:'a',name:'甲概念',domain:'领域甲',basis:'source',evidence:[e]},
 {id:'b',name:'乙概念',domain:'领域乙',basis:'source',evidence:[e]}],relations:[
 ...['supports','prerequisite','contrast','analogy'].map(kind=>({from_id:'a',to_id:'b',kind,basis:'teaching',reason:'图谱里的待核对理由',boundary:'限制条件 $m>0$',evidence:[e]}))]};
 const ctx=vm.createContext({document:{addEventListener(){}},$:get,materialScope:()=> 'scope',Event:class{},
 showView:v=>calls.view.push(v),toast:v=>calls.toasts.push(v),api:()=>{calls.sent++;throw Error('Must not send');}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/knowledge.js'),'utf8'),ctx);ctx.graph=graph;
 vm.runInContext("knowledgeState.row={id:'map',structure:graph};knowledgeState.scope='scope'",ctx);
 return {ctx,graph,calls,get,run:code=>vm.runInContext(code,ctx)};
}
test('each relation asks a different learning question and retains real source conditions',()=>{
 const {run}=fixture();const expected=[/关键转化为什么想到/,/不预先认定我缺少基础/,/定义、判别方法/,/不要强行跨学科/];
 for(let index=0;index<4;index++){
  const text=run(`knowledgeStudyQuestion(graph,'relation',${index})`);assert.match(text,expected[index]);assert.match(text,/本次只讲解，不布置习题/);
  assert.match(text,/仅用于定位/);assert.match(text,/```text\n相关知识：/);assert.match(text,/原文位置：原资料 · 第 9 页/);
  assert.equal(text.split('原文短引：').length-1,1);assert(text.includes('$m>0$'));
  assert.doesNotMatch(text,/source_id|from_id|to_id|"basis"/);
 }
});
test('draft insertion preserves exact existing text, saves an input event and never sends',()=>{
 const {calls,get,run}=fixture();const existing='  我原来的要求与公式\n    F = ma\n';get('prompt').value=existing;
 run("useKnowledgeQuestion('relation',0,'map')");assert(get('prompt').value.startsWith(existing));assert.equal(calls.events,1);assert.equal(calls.sent,0);assert.equal(calls.close,1);
 const first=get('prompt').value;get('knowledgeDialog').open=true;run("useKnowledgeQuestion('relation',0,'map')");assert.equal(get('prompt').value,first);
});
test('stale map, closed panel and changed selection cannot write the current draft',()=>{
 const {calls,get,run}=fixture();get('prompt').value='保留';run("useKnowledgeQuestion('relation',0,'old-map')");
 get('knowledgeDialog').open=false;run("useKnowledgeQuestion('relation',0,'map')");get('knowledgeDialog').open=true;run("knowledgeState.scope='other';useKnowledgeQuestion('relation',0,'map')");
 assert.equal(get('prompt').value,'保留');assert.equal(calls.events,0);assert.equal(calls.sent,0);assert.equal(calls.toasts.length,3);
});
test('invalid relations do not invent links, while node questions carry source location',()=>{
 const {ctx,graph,run}=fixture();for(const id of [-1,99,0.5,'0']){ctx.id=id;assert.equal(run("knowledgeStudyQuestion(graph,'relation',id)"),null);}
 graph.relations[0].to_id='missing';assert.equal(run("knowledgeStudyQuestion(graph,'relation',0)"),null);
 assert.match(run("knowledgeStudyQuestion(graph,'concept','a')"),/关键构造为什么这样选/);
 assert.equal(run("knowledgeStudyQuestion(graph,'concept','missing')"),null);
});
test('causal support and analogy do not use the same boundary label',()=>{
 const {run}=fixture();assert.match(run('knowledgeBoundaryLabels.supports'),/论证/);assert.match(run('knowledgeBoundaryLabels.analogy'),/类比/);
});
test('reference fence stays closed even when an AI reason contains code fences',()=>{
 const {graph,run}=fixture();graph.relations[0].reason+='\n```\n这是引用内容\n```';
 const text=run("knowledgeStudyQuestion(graph,'relation',0)");assert(text.includes('\n````text\n'));assert(text.endsWith('\n````'));
});
