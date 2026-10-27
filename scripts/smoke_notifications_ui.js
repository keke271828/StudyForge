/* Real Chromium stacking, modal, fullscreen and pointer checks. No model calls. */
const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {registerWindowHandlers,attachWindowControls}=require('../desktop/window_controls');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_DISPLAY_CASE,'utf8'));
const root=path.dirname(process.env.STUDYFORGE_DISPLAY_CASE),baseline=process.argv.includes('--baseline');
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
app.on('window-all-closed',()=>{});
let win,manager;const errors=[],checks={},sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=code=>win.webContents.executeJavaScript(code,true);
async function until(code){for(let n=0;n<160;n++){if(await run(`Boolean(${code})`))return;await sleep(50);}throw Error('Timeout: '+code);}
async function open(native=true){
  win=new BrowserWindow({show:false,width:1480,height:960,minWidth:600,minHeight:480,
    webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false,...(native?{preload:path.resolve('desktop/preload.js')}:{})}});
  attachWindowControls(win);win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
}
async function snapshot(name){await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');win.webContents.invalidate();await sleep(180);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function geometry(){return run(`(()=>{
  const node=$('toast'),r=node.getBoundingClientRect(),css=getComputedStyle(node),pointer=node.style.pointerEvents;
  node.style.pointerEvents='auto';const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);node.style.pointerEvents=pointer;
  return {visible:css.display!=='none'&&Number(css.opacity)>0.99,onTop:hit===node||node.contains(hit),
    hit:hit?.id||hit?.className||hit?.tagName,parent:node.parentElement.id||node.parentElement.tagName,
    popover:node.matches(':popover-open'),inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
    width:r.width,height:r.height,viewport:[innerWidth,innerHeight],overflow:node.scrollWidth>node.clientWidth+1};
})()`);}
async function visible(name,message='通知验收：操作已完成，学习记录已保存。'){
  await run(`toast(${JSON.stringify(message)})`);await sleep(250);const value=await geometry();checks[name]=value;
  if(!baseline){assert.equal(value.visible,true,name+' visible');assert.equal(value.onTop,true,name+' covered: '+JSON.stringify(value));assert.equal(value.inside,true,name+' outside viewport');assert.equal(value.overflow,false,name+' horizontal overflow');}
  return value;
}
async function click(selector){const point=await run(`(()=>{const n=document.querySelector(${JSON.stringify(selector)}),r=n.getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
  win.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});win.webContents.sendInputEvent({type:'mouseUp',...point,button:'left',clickCount:1});await sleep(80);}
async function keys(key){win.webContents.sendInputEvent({type:'keyDown',keyCode:key});win.webContents.sendInputEvent({type:'keyUp',keyCode:key});await sleep(100);}
app.whenReady().then(async()=>{
  ipcMain.handle('studyforge:desktop-status',()=>({tray_available:false}));registerWindowHandlers(ipcMain,new URL(input.url).origin,()=>win);
  manager=createUpdateManager({currentVersion:'0.3.5',packaged:false,storageDirectory:path.join(root,'updates'),createUpdater:()=>{throw Error('No updater in notification test');},requestQuit:()=>{throw Error('No install');}});
  registerUpdateHandlers(ipcMain,new URL(input.url).origin,()=>win,manager,()=>true,()=>false);
  try{
    await open();await run(`$('prompt').focus();$('prompt').value='通知不会中断我未发送的讲解要求。'`);
    await visible('normal');await snapshot(baseline?'修复前普通布局':'普通布局通知');
    if(!baseline){assert.equal(await run('document.activeElement.id'),'prompt');assert.equal(await run(`$('prompt').value`),'通知不会中断我未发送的讲解要求。');}
    await run(`$('readingNotesDialog').showModal()`);await visible('reading_modal');await snapshot(baseline?'修复前阅读弹窗':'阅读弹窗通知');
    if(baseline){await run(`$('readingNotesDialog').close()`);}
    else{
      // A modal opening after a notification must not cover an already visible notification.
      await run(`$('readingNotesDialog').close();toast('弹窗打开前已经出现的通知');$('submitHomework').click()`);
      await until(`$('homeworkDialog').open`);await sleep(250);checks.modal_opened_after=await geometry();assert.equal(checks.modal_opened_after.onTop,true);
      await click('#toast .toast-close');assert.equal(await run(`$('toast').matches(':popover-open')`),false);assert.equal(await run(`$('homeworkDialog').open`),true);
      await visible('homework_modal');await keys('Escape');assert.equal(await run(`$('homeworkDialog').open`),false);await sleep(80);
      checks.after_modal_close=await geometry();assert.equal(checks.after_modal_close.onTop,true);
      // More than one modal can open in an order different from DOM order.
      await run(`$('knowledgeDialog').showModal();$('readingNotesDialog').showModal()`);await visible('stacked_modals');
      assert.equal(checks.stacked_modals.parent,'readingNotesDialog');await click('#toast .toast-close');
      await run(`$('readingNotesDialog').close();$('knowledgeDialog').close()`);
      await run(`$('expandConversation').click()`);await visible('expanded');
      await run(`$('fullscreenConversation').click()`);await until('conversationDisplay.fullscreen&&!conversationDisplay.busy');assert.equal(win.isFullScreen(),true);
      await visible('native_fullscreen');await snapshot('全屏通知');await run(`$('submitHomework').click()`);await until(`$('homeworkDialog').open`);await visible('fullscreen_modal');
      await keys('Escape');assert.equal(await run('conversationDisplay.fullscreen'),true);await keys('F11');await until('!conversationDisplay.fullscreen&&!conversationDisplay.busy');
      await run(`restoreConversationLayout();showView('settings')`);await visible('settings');
      await run(`showView('study');applyStudioPreferences({...studioPreferences,ui_theme:'night'},true)`);win.setSize(600,480);await sleep(150);
      await visible('small_long_error','操作失败：'+('题目中有一处条件需要重新核对；资料已经保存，可修改要求后继续。'.repeat(9))+' https://example.com/'+('a'.repeat(200)));
      assert.equal(await run(`(()=>{const text=$('toast').querySelector('.toast-message');return text.scrollHeight>text.clientHeight;})()`),true,'Long error text must be scrollable');
      await snapshot('小窗口长通知');await click('#toast .toast-close');
      // Text must never be interpreted as markup from an error or source title.
      await run(`toast('<img src=x onerror="window.toastInjected=true">',{duration:1000})`);assert.equal(await run(`Boolean($('toast').querySelector('img')||window.toastInjected)`),false);
      // A later notification owns its own timeout.
      await run(`toast('旧通知',{duration:120})`);await sleep(70);await run(`toast('新通知',{duration:500})`);await sleep(150);
      assert.equal(await run(`$('toast').classList.contains('show')`),true);await sleep(400);assert.equal(await run(`$('toast').classList.contains('show')`),false);
      // Hover and keyboard focus must provide time to read or copy a long notification.
      await run(`window.toastPointerEvents=[];for(const event of ['pointerenter','pointerleave','mouseenter','mouseleave','mousemove'])$('toast').addEventListener(event,()=>window.toastPointerEvents.push(event));toast('鼠标停留时不会消失',{duration:700})`);await sleep(100);
      const hover=await run(`(()=>{const r=$('toast').getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
      win.webContents.sendInputEvent({type:'mouseMove',...hover});await sleep(100);
      checks.hover_enter=await run(`({events:window.toastPointerEvents,paused:[...notificationState.paused],hovered:$('toast').matches(':hover')})`);
      await sleep(650);assert.equal(await run(`$('toast').classList.contains('show')`),true,JSON.stringify(checks.hover_enter));
      win.webContents.sendInputEvent({type:'mouseMove',x:5,y:5});await sleep(700);assert.equal(await run(`$('toast').classList.contains('show')`),false);
      await run(`toast('键盘阅读时不会消失',{duration:250});$('toast').querySelector('.toast-close').focus()`);await sleep(300);
      checks.focus_enter=await run(`({active:document.activeElement.className,paused:[...notificationState.paused],hovered:$('toast').matches(':hover'),remaining:notificationState.remaining})`);
      assert.equal(await run(`$('toast').classList.contains('show')`),true);await run(`$('prompt').focus()`);await sleep(300);
      checks.focus_leave=await run(`({active:document.activeElement.id,paused:[...notificationState.paused],hovered:$('toast').matches(':hover'),remaining:notificationState.remaining})`);
      assert.equal(await run(`$('toast').classList.contains('show')`),false,JSON.stringify(checks.focus_leave));
      win.destroy();await open(false);await run(`$('fullscreenConversation').click()`);await until('document.fullscreenElement&&conversationDisplay.fullscreen&&!conversationDisplay.busy');
      await visible('browser_fullscreen');await run(`$('readingNotesDialog').showModal()`);await visible('browser_fullscreen_modal');await click('#toast .toast-close');
      await run(`$('readingNotesDialog').close();document.exitFullscreen()`);await until('!document.fullscreenElement');
      // Explicitly exercise the fallback for browsers without the popover API.
      await run(`window.nativeShowPopover=HTMLElement.prototype.showPopover;HTMLElement.prototype.showPopover=undefined`);
      await visible('fallback_normal');await run(`$('readingNotesDialog').showModal()`);await visible('fallback_modal');
      await click('#toast .toast-close');await run(`$('readingNotesDialog').close();HTMLElement.prototype.showPopover=window.nativeShowPopover;undefined`);
      assert.equal(errors.length,0,errors.join('\n'));
    }
    const modelState=await run(`api('/__display_test__/state')`);assert.equal(modelState.model_calls,0);
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({ok:baseline?undefined:true,baseline,checks,model_calls:0,errors},null,2));console.log(JSON.stringify({baseline,checks,model_calls:0,errors}));
  }catch(error){await snapshot('failure').catch(()=>{});fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,checks,errors},null,2));throw error;}
  finally{manager.dispose();if(win&&!win.isDestroyed())win.destroy();}
  app.quit();
}).catch(error=>{console.error(error.stack);if(win&&!win.isDestroyed())win.destroy();app.exit(1);});
