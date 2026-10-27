const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {setWindowFullscreen,attachWindowControls,registerWindowHandlers}=require('../desktop/window_controls');

class Window extends EventEmitter {
  constructor(){super();this.fullscreen=false;this.destroyed=false;this.calls=[];this.sent=[];
    this.webContents={mainFrame:{url:'http://127.0.0.1:9831/'},isDestroyed:()=>false,send:(...args)=>this.sent.push(args)};}
  isDestroyed(){return this.destroyed;}
  isFullScreen(){return this.fullscreen;}
  setFullScreen(value){this.calls.push(value);this.fullscreen=value;this.emit(value?'enter-full-screen':'leave-full-screen');}
}

test('native enter and leave notify actual state and do not repeat an unchanged request',async()=>{
  const win=new Window();attachWindowControls(win);
  assert.deepEqual(await setWindowFullscreen(win,true),{fullscreen:true});
  await setWindowFullscreen(win,true);
  assert.deepEqual(await setWindowFullscreen(win,false),{fullscreen:false});
  assert.deepEqual(win.calls,[true,false]);
  assert.deepEqual(win.sent,[['studyforge:window-changed',{fullscreen:true}],['studyforge:window-changed',{fullscreen:false}]]);
});

test('asynchronous window transition completes before reporting success',async()=>{
  const win=new Window();win.setFullScreen=value=>setTimeout(()=>{win.fullscreen=value;win.emit('enter-full-screen');},15);
  assert.deepEqual(await setWindowFullscreen(win,true),{fullscreen:true});
  assert.equal(win.listenerCount('closed'),0);assert.equal(win.listenerCount('enter-full-screen'),0);
});

test('failed or closed window reports failure and removes transition listeners',async()=>{
  const stuck=new Window();stuck.setFullScreen=()=>{};
  await assert.rejects(setWindowFullscreen(stuck,true,20),/未完成/);
  assert.equal(stuck.listenerCount('enter-full-screen'),0);assert.equal(stuck.listenerCount('closed'),0);
  const closing=new Window();closing.setFullScreen=()=>{closing.destroyed=true;closing.emit('closed');};
  await assert.rejects(setWindowFullscreen(closing,true),/已经关闭/);
  const broken=new Window();broken.setFullScreen=()=>{throw Error('native failure');};
  await assert.rejects(setWindowFullscreen(broken,true),/native failure/);
  assert.equal(broken.listenerCount('closed'),0);
});

test('fullscreen IPC validates values and accepts only the local main window',async()=>{
  const win=new Window(),handlers={};registerWindowHandlers({handle:(name,handler)=>handlers[name]=handler},'http://127.0.0.1:9831',()=>win);
  const event={sender:win.webContents,senderFrame:win.webContents.mainFrame};
  assert.deepEqual(handlers['studyforge:window-state'](event),{fullscreen:false});
  assert.deepEqual(await handlers['studyforge:window-fullscreen'](event,true),{fullscreen:true});
  for(const value of [1,'true',null,{},undefined])assert.throws(()=>handlers['studyforge:window-fullscreen'](event,value),/布尔值/);
  for(const bad of [{sender:event.sender,senderFrame:{url:event.senderFrame.url}},{sender:{mainFrame:event.senderFrame},senderFrame:event.senderFrame},{sender:event.sender,senderFrame:null}])
    for(const callback of Object.values(handlers))assert.throws(()=>callback(bad,false),/主窗口/);
  win.webContents.mainFrame.url='https://untrusted.example/';
  assert.throws(()=>handlers['studyforge:window-fullscreen'](event,false),/主窗口/);
});
