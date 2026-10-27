const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/refresh_state.js'),'utf8'),context);
const {coalesce,paint,pollTask}=context.window.studyforgeRefresh;
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

test('concurrent periodic reads share one request without a retained result cache',async()=>{
 const gate=deferred();let calls=0;const run=coalesce(async owner=>{calls++;await gate.promise;return owner;});
 const waiting=Array.from({length:30},()=>run('project','same'));
 assert(waiting.every(value=>value===waiting[0]));await Promise.resolve();assert.equal(calls,1);
 gate.resolve();assert((await Promise.all(waiting)).every(value=>value==='same'));await run('project','later');assert.equal(calls,2);
});
test('a mutation requests a fresh trailing read and every waiter sees the new state',async()=>{
 const gate=deferred();let version=0,calls=0;
 const run=coalesce(async()=>{const snapshot=version;if(++calls===1)await gate.promise;return snapshot;});
 const first=run('project');await Promise.resolve();version=1;
 const after=run('project',null,{fresh:true});assert.equal(first,after);
 for(let i=0;i<20;i++)run('project');gate.resolve();assert.equal(await first,1);assert.equal(calls,2);
});
test('different project and sort keys are independent',async()=>{
 const gates=[deferred(),deferred()];let calls=0;
 const run=coalesce(async owner=>{calls++;await gates[owner].promise;return owner;});
 const a=run('p:old',0),b=run('p:new',1);gates[1].resolve();assert.equal(await b,1);gates[0].resolve();assert.equal(await a,0);assert.equal(calls,2);
});
test('failed reads can be requested again',async()=>{
 let calls=0;const run=coalesce(async()=>{if(++calls===1)throw Error('temporary failure');return 'ok';});
 await assert.rejects(run('scope'));assert.equal(await run('scope'),'ok');assert.equal(calls,2);
});
test('unchanged rendering is skipped and a failed render never poisons its next attempt',()=>{
 const host={};let calls=0;assert(paint(host,['a'],()=>calls++));assert.equal(paint(host,['a'],()=>calls++),false);
 assert.throws(()=>paint(host,['b'],()=>{throw Error('render');}));assert(paint(host,['b'],()=>calls++));assert.equal(calls,2);
});
test('active watchers merge progress reads and do not ask for the task body',async()=>{
 const gate=deferred(),paths=[];const api=async path=>{paths.push(path);await gate.promise;return {status:'running',progress:35};};
 const watchers=Array.from({length:12},()=>pollTask(api,'id'));gate.resolve();const rows=await Promise.all(watchers);
 assert.equal(paths.length,1);assert.equal(paths[0],'/api/jobs/id?view=progress');assert(rows.every(row=>row.progress===35));
});
test('finished watchers merge their detail read and retain grading/output fields',async()=>{
 const paths=[];const api=async path=>{paths.push(path);return path.endsWith('progress')?{status:'completed'}:{status:'completed',result:{output:{score:82}},payload:{reading_id:'reading'}};};
 const rows=await Promise.all(Array.from({length:8},()=>pollTask(api,'job')));
 assert.equal(paths.length,2);assert(rows.every(row=>row.result.output.score===82&&row.payload.reading_id==='reading'));
});
test('phone parse polling can opt out of finished details',async()=>{
 const paths=[];const row=await pollTask(async path=>{paths.push(path);return {status:'completed',result:{source_id:'source'}};},'id',{detailOnFinish:false});
 assert.equal(paths.length,1);assert.equal(row.result.source_id,'source');
});
test('different API clients do not share requests',async()=>{
 let count=0;const one=async()=>{count++;return {status:'running',owner:1};},two=async()=>{count++;return {status:'running',owner:2};};
 const rows=await Promise.all([pollTask(one,'id'),pollTask(two,'id')]);assert.equal(count,2);assert.equal(rows[0].owner,1);assert.equal(rows[1].owner,2);
});
