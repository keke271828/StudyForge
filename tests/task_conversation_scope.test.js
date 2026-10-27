const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function client(){
 const calls={open:[],messages:0,read:0,save:[],toast:[],errors:[]};
 const ctx=vm.createContext({window:{studyforgeRefresh:{pollTask:async()=>{throw Error('unexpected poll');}}},
   state:{project:{id:'p'},conversation:'a',reading:null,view:'exercises'},knowledgeState:{},document:{addEventListener(){}},
   api:async()=>{},$:()=>({open:false}),renderReadingStatus:()=>calls.read++,captureStudyRequest:()=>({project_id:'p',conversation_id:ctx.state.conversation,source_ids:['s'],provider:'deepseek',model:'fixture',reasoning_effort:'high'}),
   materialScope:()=>'',refreshArtifacts:async()=>{},refreshExercises:async()=>{},refreshConversations:async()=>{},refreshSources:async()=>{},
   refreshConversationMessages:async()=>calls.messages++,saveConversation:v=>calls.save.push(v),
   openSet:async id=>calls.open.push(id),toast:v=>calls.toast.push(v),error:e=>calls.errors.push(e.message),setTimeout});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/task_controls.js'),'utf8'),ctx);
 vm.runInContext('syncTaskWidgets=()=>{}',ctx);
 return {ctx,calls,run:code=>vm.runInContext(code,ctx)};
}
function job(overrides={}){return {id:'j',project_id:'p',kind:'generate',status:'completed',progress:100,
 payload:{conversation_id:'a',source_ids:['s'],provider:'deepseek',model:'fixture',reasoning_effort:'high'},
 result:{output:{exercise_set:{id:'set-a'}}},...overrides};}

test('a different chat finishing cannot open its worksheet or refresh current chat history',async()=>{
 const {ctx,calls,run}=client();ctx.state.conversation='b';ctx.window.studyforgeRefresh.pollTask=async()=>job();
 await run("watchOutcomeTask('j')");assert.deepEqual(calls.open,[]);assert.equal(calls.messages,0);assert.match(calls.toast[0],/另一项任务/);
});
test('the originating chat still opens its new worksheet and refreshes its history',async()=>{
 const {ctx,calls,run}=client();ctx.window.studyforgeRefresh.pollTask=async()=>job();await run("watchOutcomeTask('j')");
 assert.deepEqual(calls.open,['set-a']);assert.equal(calls.messages,1);
});
test('a project switch while completion refresh awaits suppresses all follow-up effects',async()=>{
 const {ctx,calls,run}=client();let release;ctx.refreshArtifacts=()=>new Promise(r=>release=r);
 ctx.window.studyforgeRefresh.pollTask=async()=>job();const pending=run("watchOutcomeTask('j')");
 await new Promise(setImmediate);ctx.state.project={id:'q'};ctx.state.conversation='other';release();await pending;
 assert.deepEqual(calls.open,[]);assert.equal(calls.messages,0);assert.deepEqual(calls.toast,[]);
});
test('a chat switch during source refresh is checked again before opening or saving',async()=>{
 const {ctx,calls,run}=client();ctx.refreshSources=async()=>{ctx.state.conversation='b';};
 ctx.window.studyforgeRefresh.pollTask=async()=>job();await run("watchOutcomeTask('j')");
 assert.deepEqual(calls.open,[]);assert.equal(calls.messages,0);assert.deepEqual(calls.save,[]);
});
test('a resumed reading only writes the original scope and preserves notes in current state',async()=>{
 const {ctx,calls,run}=client();ctx.state.reading={job_id:'j',status:'running'};
 ctx.window.studyforgeRefresh.pollTask=async()=>job({kind:'read',result:{reading_id:'r',notes:'完整笔记'}});
 await run("watchOutcomeTask('j')");assert.equal(ctx.state.reading.notes,'完整笔记');assert.equal(calls.save[0].reading_id,'r');
});
test('restoring running reading follows existing task once; paused and failed do not restart anything',async()=>{
 const {ctx,calls,run}=client();let polls=0,release;ctx.state.reading={job_id:'j'};
 ctx.window.studyforgeRefresh.pollTask=()=>{polls++;return new Promise(r=>release=r);};
 ctx.row={reading_task:job({kind:'read',status:'running'})};run('restoreReadingTask(row);restoreReadingTask(row)');
 assert.equal(polls,1);ctx.state.conversation='b';release(job({kind:'read',status:'paused'}));await new Promise(setImmediate);
 ctx.state.conversation='a';for(const status of ['paused','failed']){ctx.row.reading_task.status=status;run('restoreReadingTask(row)');}
 assert.equal(polls,1);assert.equal(run('taskUI.watching.size'),0);assert.deepEqual(calls.save,[]);
});
test('task cache never holds lesson, dialogue, answers or image data and bounds old terminal rows',()=>{
 const {ctx,run}=client();ctx.large=job({result:{output:{answer:'ANSWER'.repeat(10000)},notes:'NOTES'.repeat(10000),reading_id:'r'}});
 ctx.large.payload.dialogue='PRIVATE'.repeat(10000);ctx.large.payload.images=['data:image/png;base64,large'];
 run('rememberTask(large)');assert.equal(run("JSON.stringify(taskUI.jobs.get('j')).length<1000"),true);
 assert.doesNotMatch(run("JSON.stringify(taskUI.jobs.get('j'))"),/ANSWER|NOTES|PRIVATE|base64/);
 run("state.reading={job_id:'keep'};rememberTask({id:'keep',status:'completed'});rememberTask({id:'active',status:'running'});for(let i=0;i<600;i++)rememberTask({id:'old-'+i,status:'completed'})");
 assert.equal(run('taskUI.jobs.size'),130);assert(run("taskUI.jobs.has('keep')&&taskUI.jobs.has('active')&&!taskUI.jobs.has('old-0')"));
});
test('a failure in another chat leaves that chats error out of current-chat popup',async()=>{
 const {ctx,calls,run}=client();ctx.state.conversation='b';ctx.window.studyforgeRefresh.pollTask=async()=>job({status:'failed',error:'original failure'});
 await run("watchOutcomeTask('j')");assert.deepEqual(calls.errors,[]);assert.match(calls.toast[0],/另一项任务未完成/);
});
