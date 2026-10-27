const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function client(){let counter=0;const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/task_retry.js'),'utf8'),{window,crypto:{randomUUID:()=>String(++counter).padStart(32,'0')}});return window.studyforgeTaskRetry;}

test('double activation shares one pending request using the explicit project',async()=>{
 const helper=client(),row={id:'abc',project_id:'original',updated_at:'t1'},calls=[];let release;
 const api=(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return new Promise(resolve=>release=resolve);};
 const first=helper.manual(api,row),second=helper.manual(api,row);assert.equal(first,second);assert.equal(calls.length,1);
 assert.equal(calls[0].body.project_id,'original');release({job_id:row.id});await first;
});

test('a lost response retries with the same request ID, while a later failure gets a new one',async()=>{
 const helper=client(),row={id:'abc',project_id:'p',updated_at:'t1'},requests=[];
 const api=async(url,options)=>{requests.push(JSON.parse(options.body));if(requests.length===1)throw Error('response lost');return {job_id:row.id};};
 await assert.rejects(()=>helper.manual(api,row));await helper.manual(api,row);await helper.manual(api,{...row,updated_at:'t2'});
 assert.equal(requests[0].request_id,requests[1].request_id);assert.notEqual(requests[1].request_id,requests[2].request_id);
});

test('two project scopes are never coalesced under one client request',async()=>{
 const helper=client(),row={id:'abc',updated_at:'t1'},projects=[];
 const api=async(url,options)=>{projects.push(JSON.parse(options.body).project_id);return {};};
 await Promise.all([helper.manual(api,row,'first'),helper.manual(api,row,'second')]);assert.deepEqual(projects,['first','second']);
});
