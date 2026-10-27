const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function pager(){const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/message_history.js'),'utf8'),{window,URLSearchParams});return window.studyforgeHistoryPages;}
const row=(id,text=id)=>({id,content:text,role:'assistant',created_at:'2026-10-11',_order:Number(id)});
const payload=(rows,revision,cursor='cursor')=>({messages:rows,history:{revision,oldest_cursor:cursor,has_older:true}});

test('An older page cannot claim a newer revision that covered only the previous visible range',()=>{
 const p=pager(),host={};p.begin(host,'chat',payload([row('3'),row('4')],10));
 const earlier=p.request(host,{older:true}),poll=p.request(host);
 p.apply(host,payload([row('3'),row('4')],11),poll);
 p.apply(host,payload([row('1'),row('2')],10,'earlier'),earlier);
 const query=new URLSearchParams(p.request(host).query);
 assert.equal(query.get('since'),'10');assert.equal(query.get('start'),'earlier');
 const revised=p.apply(host,payload([row('1','corrected while loading'),row('2'),row('3'),row('4')],11,'earlier'),p.request(host));
 assert.equal(revised[0].content,'corrected while loading');assert.equal(p.state(host).revision,11);
});

test('A slow response for a smaller range cannot erase newly expanded history',()=>{
 const p=pager(),host={};p.begin(host,'chat',payload([row('3')],10));
 const poll=p.request(host),earlier=p.request(host,{older:true});
 p.apply(host,payload([row('1'),row('2')],10,'earlier'),earlier);
 assert.equal(p.apply(host,payload([row('3')],11),poll),null);
 assert.deepEqual(Array.from(p.state(host).rows,r=>r.id),['1','2','3']);
});

test('A changed conversation rejects earlier tickets even if an ID is later reopened',()=>{
 const p=pager(),host={};p.begin(host,'chat',payload([row('3')],10));const old=p.request(host);
 p.begin(host,'other',payload([row('9')],1));p.begin(host,'chat',payload([row('4')],11));
 assert.equal(p.apply(host,payload([row('3')],10),old),null);
 assert.equal(p.state(host).rows[0].id,'4');
});

test('Cleared display rows still retain the cursor for older saved records',()=>{
 const p=pager(),host={};p.begin(host,'chat',payload([row('3')],10));
 p.apply(host,payload([],11,'original-boundary'),p.request(host));
 assert.equal(new URLSearchParams(p.request(host,{older:true}).query).get('before'),'original-boundary');
});
