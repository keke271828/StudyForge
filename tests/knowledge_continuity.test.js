const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function client(){
 const nodes=new Map(),jobs=new Map(),calls={reading:[],watch:[],paths:[],sync:0};
 const element=id=>{if(!nodes.has(id))nodes.set(id,{id,hidden:false,disabled:false,open:id==='knowledgeDialog',textContent:'',value:'',querySelector:()=>({replaceChildren(){}}),showModal(){this.open=true;}});return nodes.get(id);};
 const request={project_id:'p',conversation_id:'a',source_ids:['s'],provider:'deepseek',model:'fixture',reasoning_effort:'high'};
 const ctx=vm.createContext({URLSearchParams,window:{},document:{addEventListener(){}},state:{project:{id:'p'},selected:new Set(['s']),conversation:'a'},
  taskUI:{jobs},pendingTaskStatuses:['queued','running','pausing','paused'],$:element,scope:'scope-a',materialScope:()=>ctx.scope,
  captureStudyRequest:()=>({...request,conversation_id:ctx.state.conversation}),toast(){},error:e=>{throw e;},
  ensureReading:async(...args)=>{calls.reading.push(args);return {reading_id:'r',status:'completed'};},
  api:async url=>{calls.paths.push(url);return url.endsWith('/jobs')?[]:{reading_id:'r',structure:null};},
  taskLabel:()=> '整理知识结构',syncTaskWidgets:rows=>{calls.sync++;rows.forEach(row=>jobs.set(row.id,row));},
  watchOutcomeTask:async id=>calls.watch.push(id),rememberTask:job=>jobs.set(job.id,job),
  jsonOptions:(method,body)=>({method,body:JSON.stringify(body)}),setTimeout,
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/knowledge.js'),'utf8'),ctx);
 vm.runInContext('renderKnowledge=row=>{knowledgeState.row=row;renderKnowledgeActions()}',ctx);
 return {ctx,calls,element,request,run:code=>vm.runInContext(code,ctx)};
}
function task(overrides={}){return {id:'job',kind:'knowledge',project_id:'p',conversation_id:'a',reading_id:'r',provider:'deepseek',model:'fixture',reasoning_effort:'high',status:'paused',progress:35,...overrides};}
test('only exact chat, reading, service, model and effort identify the resumable structure',()=>{
 const {ctx,request,run}=client();ctx.request=request;ctx.job=task();assert(run("knowledgeTaskMatches(job,'r',request)"));
 for(const [key,value] of Object.entries({project_id:'q',conversation_id:'b',reading_id:'other',provider:'codex',model:'other',reasoning_effort:'low'})){
  ctx.job=task({[key]:value});assert.equal(run("knowledgeTaskMatches(job,'r',request)"),false,key);
 }
});
test('opening finds the owning paused task, scopes the map request and never resumes automatically',async()=>{
 const {ctx,calls,element,run}=client();const own=task(),other=task({id:'other',conversation_id:'b'});
 ctx.api=async url=>{calls.paths.push(url);return url.endsWith('/jobs')?[other,own]:{reading_id:'r',structure:null};};
 await run('openKnowledge()');assert.equal(run('knowledgeState.jobId'),'job');assert(element('buildKnowledge').disabled);
 assert.match(calls.paths[0],/provider=deepseek.*model=fixture.*reasoning_effort=high/);assert.deepEqual(calls.watch,[]);
});
test('an older failed attempt is not restored after a newer completed task',async()=>{
 const {ctx,run}=client();ctx.api=async url=>url.endsWith('/jobs')?[task({status:'completed'}),task({id:'old',status:'failed'})]:{structure:null};
 await run('openKnowledge()');assert.equal(run('knowledgeState.jobId'),null);
});
test('stale opening failure never overwrites another dialog or releases its build controls',async()=>{
 const {ctx,element,run}=client();let reject;ctx.ensureReading=()=>new Promise((a,b)=>reject=b);
 const promise=run('openKnowledge()');run("knowledgeState.token++;knowledgeState.busy=true;knowledgeState.buildToken=knowledgeState.token");
 ctx.scope='scope-b';element('knowledgeStatus').textContent='新任务的状态';element('buildKnowledge').disabled=true;
 reject(Error('旧请求失败'));await promise;assert.equal(element('knowledgeStatus').textContent,'新任务的状态');assert(element('buildKnowledge').disabled);assert(run('knowledgeState.busy'));
});
test('explicit rebuild reuses the read, captures original instructions and cannot claim a later dialog',async()=>{
 const {ctx,calls,run}=client();let release,packet;run("knowledgeState.scope='scope-a';knowledgeState.row={structure:{concepts:[]}};");
 ctx.api=(url,options)=>{packet=JSON.parse(options.body);return new Promise(r=>release=r);};
 const pending=run('buildKnowledge()');await new Promise(setImmediate);
 assert(packet.force);assert.equal(packet.conversation_id,'a');assert.equal(packet.reading_id,'r');assert.deepEqual(calls.reading,[[]]);
 ctx.state.conversation='b';ctx.scope='scope-b';run("knowledgeState.token++;knowledgeState.jobId='new-job';knowledgeState.busy=true;knowledgeState.buildToken=knowledgeState.token");
 release({job_id:'old-job'});await pending;assert.equal(run('knowledgeState.jobId'),'new-job');assert(run('knowledgeState.busy'));assert.deepEqual(calls.watch,['old-job']);
});
test('closing during map fetch avoids task adoption and pending task follow-up',async()=>{
 const {ctx,calls,element,run}=client();let release;ctx.api=()=>new Promise(r=>release=r);
 const pending=run('openKnowledge()');await new Promise(setImmediate);element('knowledgeDialog').open=false;release({structure:null});await pending;
 assert.equal(calls.sync,0);assert.equal(run('knowledgeState.jobId'),null);
});
