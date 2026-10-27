const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createDesktopLifecycle,registerDesktopHandlers}=require('../desktop/lifecycle');

class App extends EventEmitter {
  quit(){const event={prevented:false,preventDefault(){this.prevented=true;}};this.emit('before-quit',event);
    if(!event.prevented){this.finished=true;this.emit('will-quit');}}
}
class Tray extends EventEmitter {
  constructor(){super();this.destroyed=false;}
  isDestroyed(){return this.destroyed;}
  setToolTip(value){this.tooltip=value;}
  setContextMenu(value){this.menu=value;}
  displayBalloon(value){this.balloon=value;}
  destroy(){this.destroyed=true;}
}
class Window extends EventEmitter {
  constructor(){super();this.visible=true;this.destroyed=false;this.draft='未发送草稿';this.sent=[];
    this.webContents={send:(...value)=>this.sent.push(value),mainFrame:{url:'http://127.0.0.1:9876/'}};}
  isVisible(){if(this.destroyed)throw new Error('Window destroyed');return this.visible;}
  isDestroyed(){return this.destroyed;}
  hide(){this.visible=false;this.emit('hide');}
  show(){this.visible=true;this.emit('show');}
  close(){const event={prevented:false,preventDefault(){this.prevented=true;}};this.emit('close',event);
    if(!event.prevented){this.destroyed=true;this.emit('closed');}}
}
function fixture(options={}){
  const app=new App(),win=new Window(),calls={prepared:0,stopped:0,errors:[],views:[]};
  const life=createDesktopLifecycle({app,Tray,Menu:{buildFromTemplate:items=>({items,getMenuItemById:id=>items.find(x=>x.id===id)})},
    icon:'test.ico',getWindow:()=>win,showWindow:view=>{calls.views.push(view);win.show();},
    prepareShutdown:async()=>{calls.prepared++;},stopBackend:()=>{calls.stopped++;},
    readStatus:async()=>({active_jobs:1,memory_running:false,paused_generations:0}),
    onError:error=>calls.errors.push(error.message),...options});
  life.start();life.attachWindow(win);return {app,win,life,calls};
}
test('X keeps the same window, unsent draft and backend; tray reopens it',async t=>{
  const {win,life,calls}=fixture();t.after(()=>life.dispose());
  win.close();assert.equal(win.destroyed,false);assert.equal(win.visible,false);assert.equal(calls.stopped,0);
  await life.poll();assert.match(life.tray.tooltip,/1 项任务运行中/);
  life.tray.emit('click');assert.equal(win.visible,true);assert.equal(win.draft,'未发送草稿');
  life.menu.getMenuItemById('progress').click();assert.deepEqual(calls.views,[undefined,'artifacts']);
});
test('explicit exit waits for saving, runs once and releases the tray',async()=>{
  let release;const pending=new Promise(resolve=>{release=resolve;});
  const {app,win,life,calls}=fixture({prepareShutdown:()=>pending});
  const tray=life.tray;life.menu.getMenuItemById('exit').click();app.quit();
  assert.equal(life.status().quitting,true);assert.equal(calls.stopped,0);assert.equal(app.finished,undefined);
  assert.equal(life.hide(),false);assert.equal(win.sent.at(-1)[0],'studyforge:desktop-quitting');
  release();await life.shutdownPromise;
  assert.equal(calls.stopped,2); // Normal exit and the final before-quit guard; root stop is idempotent.
  assert.equal(app.finished,true);assert.equal(tray.destroyed,true);
});
test('a failed save still exits; startup recovery handles unfinished jobs',async()=>{
  const {app,life,calls}=fixture({prepareShutdown:async()=>{throw new Error('backend unavailable');}});
  app.quit();await life.shutdownPromise;
  assert.equal(app.finished,true);assert.deepEqual(calls.errors,['backend unavailable']);
});
test('tray failure never leaves an unreachable hidden window',async()=>{
  const {app,win,life,calls}=fixture({Tray:class {constructor(){throw new Error('no notification area');}}});
  assert.equal(life.status().tray_available,false);assert.equal(life.hide(),false);assert.equal(win.visible,true);
  win.close();await life.shutdownPromise;assert.equal(app.finished,true);assert.equal(calls.prepared,1);
});
test('the app survives window-all-closed while a tray exists',async t=>{
  const {app,win,life,calls}=fixture();t.after(()=>life.dispose());
  win.destroyed=true;app.emit('window-all-closed');await life.poll();
  assert.equal(life.status().window_visible,false);assert.equal(calls.stopped,0);
  life.tray.emit('double-click');assert.equal(calls.views.length,1);
});
test('desktop IPC rejects remote pages, child frames and other windows',async t=>{
  const {win,life}=fixture();t.after(()=>life.dispose());
  const handlers={};registerDesktopHandlers({handle:(name,callback)=>{handlers[name]=callback;}},'http://127.0.0.1:9876',()=>win,life);
  const sender=win.webContents,main=sender.mainFrame,event={sender,senderFrame:main};
  assert.equal(handlers['studyforge:desktop-status'](event).tray_available,true);
  for(const bad of [{sender,senderFrame:{url:main.url}},
                    {sender:{mainFrame:main},senderFrame:main},
                    {sender,senderFrame:null}])
    for(const callback of Object.values(handlers))assert.throws(()=>callback(bad),/主窗口/);
  main.url='https://external.example/';assert.throws(()=>handlers['studyforge:quit'](event),/主窗口/);
});
test('settings hide and exit IPC use the same native lifecycle',async()=>{
  const {app,win,life}=fixture();const handlers={};
  registerDesktopHandlers({handle:(name,callback)=>{handlers[name]=callback;}},'http://127.0.0.1:9876',()=>win,life);
  const event={sender:win.webContents,senderFrame:win.webContents.mainFrame};
  assert.equal(handlers['studyforge:hide-to-tray'](event),true);assert.equal(win.visible,false);
  assert.equal(handlers['studyforge:quit'](event),true);
  await new Promise(setImmediate);await life.shutdownPromise;assert.equal(app.finished,true);
});
test('update execution starts only after a saved receipt and asynchronous backend stop',async()=>{
  let stopped;const stop=new Promise(resolve=>{stopped=resolve;});const calls=[];
  const {life}=fixture({prepareShutdown:async()=>({backup:{id:'verified-snapshot'}}),stopBackend:()=>stop});
  life.quitAfterSave({afterStop:receipt=>{calls.push(receipt.backup.id);},onFailure:error=>assert.fail(error.message)});
  await new Promise(setImmediate);assert.deepEqual(calls,[]);
  stopped();await life.shutdownPromise;assert.deepEqual(calls,['verified-snapshot']);
});
test('failed state saving cancels installation while the app can still exit',async()=>{
  let installed=false;const errors=[];
  const {app,life}=fixture({prepareShutdown:async()=>{throw new Error('backup failed');}});
  life.quitAfterSave({afterStop:()=>{installed=true;},onFailure:error=>errors.push(error.message)});
  await life.shutdownPromise;assert.equal(installed,false);assert.equal(app.finished,true);assert.ok(errors.some(x=>x.includes('backup failed')));
});

test('session-end exit reports an asynchronous backend-stop failure',async()=>{
  const {app,win,calls}=fixture({stopBackend:async()=>{throw new Error('stop failed');}});
  win.emit('query-session-end');app.quit();await new Promise(setImmediate);
  assert.equal(app.finished,true);assert.deepEqual(calls.errors,['stop failed']);
});
