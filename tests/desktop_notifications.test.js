const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {createNotificationManager,registerNotificationHandlers,safeTarget}=require('../desktop/notifications');
const {ensureNotificationIdentity}=require('../desktop/notification_identity');

function fixture(t,{focused=false,enabled=true,foreground=true}={}){
  const created=[],opened=[],receipts=[],updates=[],errors=[];
  class Notification extends EventEmitter{
    static supported=true;static isSupported(){return this.supported;}
    constructor(options){super();this.options=options;created.push(this);}
    show(){this.shown=true;this.emit('show');}
    close(){this.closed=true;this.emit('close');}
  }
  const config={desktop_notifications_enabled:enabled,desktop_notifications_sound:true,desktop_notifications_foreground:foreground};
  for(const key of ['complete','approval','failure','questionnaire','chat','update'])config['desktop_notifications_'+key]=true;
  const data={events:[],recent:[],active_actions:[],settings:config};
  const flags={focused,visible:true,readError:false,ackError:false};
  const window={isDestroyed:()=>false,isVisible:()=>flags.visible,isMinimized:()=>false,isFocused:()=>flags.focused,
    webContents:{mainFrame:{url:'http://127.0.0.1:3333/'}}};
  const manager=createNotificationManager({Notification,icon:'app.ico',getWindow:()=>window,
    showWindow:async target=>{opened.push(target);flags.visible=true;},
    readFeed:async()=>{if(flags.readError)throw new Error('temporarily offline');return data;},
    acknowledge:async(ids,status)=>{if(flags.ackError)throw new Error('receipt unavailable');receipts.push({ids,status});
      data.events=data.events.filter(event=>!ids.includes(event.id));},notify:value=>updates.push(value),onError:error=>errors.push(error.message)});
  t.after(()=>manager.dispose());
  const add=(category='complete',id=created.length+1)=>{
    const event={id,category,notice_key:category+':'+id,title:'学习事件',body:'项目 / 对话\n详情',created_at:new Date().toISOString(),
      target:{view:category==='complete'?'artifacts':'study',project_id:'project',conversation_id:'chat'}};
    data.events.push(event);data.recent.unshift(event);
    if(['approval','questionnaire'].includes(category))data.active_actions.push(event.notice_key);
    return event;
  };
  return {manager,Notification,created,opened,receipts,updates,errors,data,flags,window,add};
}

test('hidden window gets a native notification; clicking restores exact scope without approval',async t=>{
  const f=fixture(t);f.flags.visible=false;const event=f.add('approval');event.target.approval_id='permission-request';
  await f.manager.poll();assert.equal(f.created.length,1);assert.equal(f.created[0].options.timeoutType,'never');
  assert.deepEqual(f.receipts,[{ids:[1],status:'sent'}]);assert.equal(f.opened.length,0);
  f.created[0].emit('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(f.opened,[event.target]);assert.equal(f.flags.visible,true);
  f.created[0].emit('click');await new Promise(resolve=>setImmediate(resolve));assert.equal(f.opened.length,1);
  await f.manager.poll();assert.equal(f.created.length,1);
});
test('resolved approval is dismissed even after the popup banner has timed out',async t=>{
  const f=fixture(t);f.add('approval');await f.manager.poll();
  f.created[0].emit('close');f.data.active_actions=[];await f.manager.poll();
  assert.equal(f.created[0].closed,true);
});
test('reply notification is quiet when app focused; completions still notify by default',async t=>{
  const f=fixture(t,{focused:true});f.add('chat',1);f.add('complete',2);await f.manager.poll();
  assert.equal(f.created.length,1);assert.deepEqual(f.receipts,[{ids:[2],status:'sent'},{ids:[1],status:'skipped'}]);
});
test('foreground preference, category switches and sounds change actual native delivery',async t=>{
  const f=fixture(t,{focused:true,foreground:false});f.add('complete',1);await f.manager.poll();assert.equal(f.created.length,0);
  f.flags.focused=false;f.data.settings.desktop_notifications_complete=false;f.add('complete',2);await f.manager.poll();assert.equal(f.created.length,0);
  f.data.settings.desktop_notifications_complete=true;f.data.settings.desktop_notifications_sound=false;
  f.add('complete',3);await f.manager.poll();assert.equal(f.created[0].options.silent,true);
});
test('disabled notifications are acknowledged once and remain in the notification list',async t=>{
  const f=fixture(t,{enabled:false});f.add('complete');await f.manager.poll();assert.equal(f.created.length,0);
  assert.equal(f.manager.snapshot().recent.length,1);assert.equal(f.receipts[0].status,'skipped');
  f.data.settings.desktop_notifications_enabled=true;await f.manager.poll();assert.equal(f.created.length,0);
  await f.manager.open(1);assert.equal(f.opened.length,1);
});
test('lost acknowledgement never duplicates an already sent notification',async t=>{
  const f=fixture(t);f.add('complete');f.flags.ackError=true;await f.manager.poll();assert.equal(f.created.length,1);
  f.flags.ackError=false;await f.manager.poll();assert.equal(f.created.length,1);assert.equal(f.data.events.length,0);
});
test('questionnaire is persistent and selecting it returns to its original chat',async t=>{
  const f=fixture(t);const event=f.add('questionnaire');event.target.homework_attempt_id='homework';
  await f.manager.poll();assert.equal(f.created[0].options.timeoutType,'never');await f.manager.open(event.id);
  assert.deepEqual(f.opened,[event.target]);
});
test('native OS errors are surfaced and correct the delivery receipt',async t=>{
  const f=fixture(t);f.add('complete');await f.manager.poll();
  f.created[0].emit('failed',{},'native show failed');await f.manager.poll();
  assert.equal(f.manager.snapshot().last_error,'native show failed');assert.equal(f.receipts.at(-1).status,'failed');
});
test('update notifications deduplicate a version and ignore download progress',async t=>{
  const f=fixture(t);await f.manager.poll();
  f.manager.update({status:'available',candidate:{version:'1.2.3'}});
  f.manager.update({status:'available',candidate:{version:'1.2.3'}});
  f.manager.update({status:'downloading',candidate:{version:'1.2.3'},progress:{percent:50}});
  f.manager.update({status:'downloaded',candidate:{version:'1.2.3'}});
  assert.equal(f.created.length,2);assert.equal(f.manager.snapshot().recent.length,2);
  assert.equal(f.created[1].options.body,'点击查看更新并选择何时重启安装。');
});
test('unsupported native API is visible and never crashes tasks',async t=>{
  const f=fixture(t);f.Notification.supported=false;f.add('complete');await f.manager.poll();
  assert.equal(f.receipts[0].status,'failed');assert.equal(f.manager.snapshot().supported,false);assert.equal(f.created.length,0);
});
test('test button calls native adapter show and honors silent preference',async t=>{
  const f=fixture(t);f.data.settings.desktop_notifications_sound=false;
  const result=await f.manager.test();assert.equal(f.created.length,1);assert.equal(result.last_delivery.native_shown,true);
  assert.equal(f.created[0].options.silent,true);
});
test('stopping desktop delivery closes owned notifications and rejects later events',async t=>{
  const f=fixture(t);f.add('approval');await f.manager.poll();f.manager.dispose();
  assert.equal(f.created[0].closed,true);f.manager.backendStopped();await f.manager.poll();assert.equal(f.created.length,1);
});
test('renderer can open only stored targets; external and child frames cannot invoke IPC',async t=>{
  const f=fixture(t);f.add();await f.manager.poll();
  const handlers=new Map();registerNotificationHandlers({handle:(channel,fn)=>handlers.set(channel,fn)},'http://127.0.0.1:3333',()=>f.window,f.manager);
  const main={sender:f.window.webContents,senderFrame:f.window.webContents.mainFrame};
  assert.equal(handlers.get('studyforge:notification-status')(main).supported,true);
  await assert.rejects(()=>f.manager.open('arbitrary-target'),/过期/);
  assert.throws(()=>handlers.get('studyforge:notification-open')({...main,senderFrame:{url:'https://evil.example/'}},1));
  assert.throws(()=>handlers.get('studyforge:notification-open')(main,{view:'study',project_id:'elsewhere'}));
  assert.throws(()=>safeTarget({view:'https://evil.example'}));
  assert.throws(()=>safeTarget({view:'study',conversation_id:'../other'}));
});
test('source Windows notification identity uses a dedicated owned Start Menu shortcut',t=>{
  const tempRoot=path.resolve(os.tmpdir()),dir=fs.mkdtempSync(path.join(tempRoot,'sf-notice-identity-'));
  assert.equal(path.dirname(path.resolve(dir)),tempRoot);assert.ok(path.basename(dir).startsWith('sf-notice-identity-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const ids=[],writes=[];
  const result=ensureNotificationIdentity({app:{isPackaged:false,setAppUserModelId:id=>ids.push(id)},
    shell:{writeShortcutLink:(file,operation,details)=>{writes.push({file,operation,details});return true;}},
    root:'C:\\Study Forge',icon:'app.ico',platform:'win32',shortcutDirectory:dir});
  assert.deepEqual(ids,['org.studyforge.desktop.source']);assert.equal(writes[0].details.args,'"C:\\Study Forge"');
  assert.equal(writes[0].details.appUserModelId,ids[0]);assert.equal(result.shortcut,writes[0].file);
});
test('installed notification identity matches existing NSIS identity without replacing shortcuts',()=>{
  const ids=[];ensureNotificationIdentity({app:{isPackaged:true,setAppUserModelId:id=>ids.push(id)},
    shell:{writeShortcutLink:()=>assert.fail('installer owns its shortcuts')},platform:'win32'});
  assert.deepEqual(ids,['org.studyforge.desktop']);
});
test('formats from the same task share one banner and both get durable receipts',async t=>{
  const f=fixture(t);f.add('complete',1).target.job_id='same-job';f.add('complete',2).target.job_id='same-job';
  await f.manager.poll();assert.equal(f.created.length,1);assert.match(f.created[0].options.title,/2 份成果/);
  assert.deepEqual(f.receipts,[{ids:[1,2],status:'sent'}]);
  f.created[0].emit('failed',{},'batch failed');await f.manager.poll();assert.deepEqual(f.receipts.at(-1),{ids:[1,2],status:'failed'});
});
test('a burst of independent tasks delivers bounded batches instead of dropping the remainder',async t=>{
  const f=fixture(t);for(let id=1;id<=6;id++)f.add('complete',id);
  await f.manager.poll();assert.equal(f.created.length,4);assert.equal(f.data.events.length,2);
  await f.manager.poll();assert.equal(f.created.length,6);assert.equal(f.data.events.length,0);
});
test('temporary backend failure clears after reconnect without requiring a new task',async t=>{
  const f=fixture(t);f.flags.readError=true;await f.manager.poll();assert.equal(f.manager.snapshot().connected,false);
  f.flags.readError=false;await f.manager.poll();assert.equal(f.manager.snapshot().connected,true);assert.equal(f.manager.snapshot().last_error,'');
});
