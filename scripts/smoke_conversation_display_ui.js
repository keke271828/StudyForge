const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {registerWindowHandlers,attachWindowControls}=require('../desktop/window_controls');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_DISPLAY_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_DISPLAY_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
app.on('window-all-closed',()=>{});
let win,manager;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=code=>win.webContents.executeJavaScript(code,true);
async function until(code){for(let n=0;n<160;n++){if(await run(code))return;await sleep(50);}throw Error('Timeout: '+code+'; native='+win.isFullScreen()+'; UI='+await run('JSON.stringify(conversationDisplay)'));}
async function snapshot(name){await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');win.webContents.invalidate();await sleep(200);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function open(native=true){
  win=new BrowserWindow({show:false,width:1480,height:960,minWidth:600,minHeight:480,
    webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false,...(native?{preload:path.resolve('desktop/preload.js')}:{})}});
  attachWindowControls(win);
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
  await until(`$('messages').querySelectorAll('.message').length===2`);
}
async function geometry(){return run(`(()=>{
  const r=document.querySelector('.conversation-panel').getBoundingClientRect(),m=$('messages').getBoundingClientRect();
  return {width:r.width,height:r.height,messagesHeight:m.height,viewportWidth:innerWidth,viewportHeight:innerHeight,
    sidebar:getComputedStyle(document.querySelector('.sidebar')).display,context:getComputedStyle(document.querySelector('.context-panel')).display,
    horizontal:document.documentElement.scrollWidth-innerWidth,send:$('sendMessage').getBoundingClientRect().bottom,generate:$('generate').getBoundingClientRect().bottom};
})()`);}
async function keys(key,options={}){await run(`document.dispatchEvent(new KeyboardEvent('keydown',{key:${JSON.stringify(key)},bubbles:true,cancelable:true,...${JSON.stringify(options)}}))`);await sleep(120);}
async function advancedOptions(){
  const collapsed=await run('!conversationDisplay.toolsVisible');
  if(collapsed)await run(`$('toggleConversationTools').click()`);
  await run(`document.querySelector('.advanced-generation').open=true`);await sleep(80);
  assert.equal(await run(`(()=>{const control=$('reviewMode'),r=control.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.top>=0&&r.bottom<=innerHeight&&(hit===control||control.contains(hit));})()`),true,'Advanced settings must be visible and clickable, not clipped by the composer');
  await run(`document.querySelector('.advanced-generation').open=false`);
  if(collapsed)await run(`$('toggleConversationTools').click()`);
}
async function intact(){assert.equal(await run(`$('prompt').value`),'未发送的讲解要求：不要跳过证明动机。');
  assert.equal(await run(`window.originalMessage===$('messages').querySelector('.message.assistant')`),true);
  assert.equal(await run(`JSON.stringify(studioPreferences)===window.originalPreferences`),true);
  assert.equal(await run(`state.conversation`),input.chat);
  assert.equal(await run(`$('prompt').selectionStart===3&&$('prompt').selectionEnd===7`),true);
}
app.whenReady().then(async()=>{
  ipcMain.handle('studyforge:desktop-status',()=>({tray_available:false}));
  registerWindowHandlers(ipcMain,new URL(input.url).origin,()=>win);
  manager=createUpdateManager({currentVersion:'0.3.4',packaged:false,storageDirectory:path.join(root,'updates'),createUpdater:()=>{throw Error('no updater in source test');},requestQuit:()=>{throw Error('no install');}});
  registerUpdateHandlers(ipcMain,new URL(input.url).origin,()=>win,manager,()=>true,()=>false);
  try{
    await open();
    assert.equal(await run(`$('toggleConversationTools').hidden`),false,'Normal workbench must offer the tool toggle');
    const originalFormat=await run(`$('outputFormat').value`),originalMode=await run(`$('learningMode').value`);
    const beforeCollapse=await geometry();
    await run(`$('toggleConversationTools').click()`);await until('!studioPending');await sleep(150);
    const ordinaryCollapsed=await geometry();
    assert.notEqual(ordinaryCollapsed.sidebar,'none');assert.notEqual(ordinaryCollapsed.context,'none');
    assert.ok(ordinaryCollapsed.messagesHeight>beforeCollapse.messagesHeight+30,JSON.stringify({beforeCollapse,ordinaryCollapsed}));
    assert.equal(await run(`getComputedStyle(document.querySelector('.model-toolbar')).display`),'none');
    assert.equal(await run(`getComputedStyle($('outputFormat').closest('.control')).display`),'none');
    assert.equal(await run(`$('outputFormat').value`),originalFormat);assert.equal(await run(`$('learningMode').value`),originalMode);
    assert.ok(ordinaryCollapsed.send<=ordinaryCollapsed.viewportHeight&&ordinaryCollapsed.generate<=ordinaryCollapsed.viewportHeight);
    await snapshot('普通工作台收起导师工具');
    await win.reload();await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
    assert.equal(await run('studioPreferences.ui_tutor_tools_visible'),false);
    assert.equal(await run(`document.documentElement.dataset.chatTools`),'false');
    await run(`showView('sources');showView('study')`);await sleep(120);
    assert.equal(await run(`document.documentElement.dataset.chatTools`),'false');
    await run(`$('expandConversation').click();$('toggleConversationTools').click();restoreConversationLayout()`);
    assert.equal(await run(`document.documentElement.dataset.chatTools`),'false','Temporary expanded tools must not reset the normal preference');
    await run(`$('toggleConversationTools').click()`);await until('!studioPending');await sleep(150);
    assert.equal(await run(`getComputedStyle(document.querySelector('.model-toolbar')).display`)!=='none',true);
    await run(`$('prompt').value='未发送的讲解要求：不要跳过证明动机。';$('prompt').setSelectionRange(3,7);window.originalMessage=$('messages').querySelector('.message.assistant');window.originalPreferences=JSON.stringify(studioPreferences);$('messages').scrollTop=$('messages').scrollHeight/3;`);
    const normal=await geometry();await snapshot('普通对话');
    await run(`$('expandConversation').click()`);await until(`document.documentElement.dataset.chatExpanded==='true'`);await sleep(120);
    const expanded=await geometry();assert.ok(expanded.width>normal.width+200,JSON.stringify({normal,expanded}));
    assert.ok(expanded.messagesHeight>normal.messagesHeight+100,JSON.stringify({normal,expanded}));
    assert.equal(expanded.sidebar,'none');assert.equal(expanded.context,'none');assert.ok(expanded.horizontal<=1);
    await intact();assert.ok(await run(`$('messages').scrollTop>50&&$('messages').scrollHeight-$('messages').clientHeight-$('messages').scrollTop>50`),'Reading position must not jump to either end');
    await snapshot('放大对话');
    await advancedOptions();
    await run(`$('toggleConversationTools').click()`);assert.notEqual(await run(`getComputedStyle(document.querySelector('.conversation-panel>.section-head')).display`),'none');
    await run(`$('toggleConversationTools').click()`);
    await keys('F11');await until(`conversationDisplay.fullscreen&&!conversationDisplay.busy`);assert.equal(win.isFullScreen(),true);
    await keys('F11',{repeat:true});assert.equal(win.isFullScreen(),true);
    await snapshot('真正全屏对话');const fullscreen=await geometry();await intact();
    assert.ok(fullscreen.width>=expanded.width,JSON.stringify({expanded,fullscreen}));
    await keys('Escape');await until(`!conversationDisplay.fullscreen&&!conversationDisplay.busy`);assert.equal(win.isFullScreen(),false);
    assert.equal(await run(`conversationDisplay.expanded`),true);
    await keys('Escape');assert.equal(await run(`conversationDisplay.expanded`),false);await intact();
    const restored=await geometry();assert.ok(Math.abs(restored.width-normal.width)<2,JSON.stringify({normal,restored}));
    // Entering from the normal layout returns to normal; a modal owns the first Esc.
    await run(`$('fullscreenConversation').click()`);await until(`conversationDisplay.fullscreen&&!conversationDisplay.busy`);
    await run(`$('submitHomework').click()`);await until(`$('homeworkDialog').open`);
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});
    win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});
    await until(`!$('homeworkDialog').open`);assert.equal(await run(`conversationDisplay.fullscreen`),true);
    win.setFullScreen(false);await until(`!conversationDisplay.fullscreen&&!conversationDisplay.expanded`);await intact();
    await run(`document.querySelector('.conversation-heading').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);
    assert.equal(await run(`conversationDisplay.expanded`),true);
    await keys('e',{ctrlKey:true,shiftKey:true});assert.equal(await run(`conversationDisplay.expanded`),false);
    await run(`$('fullscreenConversation').click()`);await until(`conversationDisplay.fullscreen&&!conversationDisplay.busy`);
    await keys('p',{ctrlKey:true});await until(`!conversationDisplay.fullscreen&&!conversationDisplay.busy`);
    assert.equal(await run(`document.activeElement.id`),'navigationSearch');
    await run(`$('fullscreenConversation').click()`);await until(`conversationDisplay.fullscreen&&!conversationDisplay.busy`);
    await run(`showView('sources')`);await until(`!conversationDisplay.fullscreen&&!conversationDisplay.busy`);assert.equal(win.isFullScreen(),false);
    assert.notEqual(await run(`getComputedStyle(document.querySelector('.sidebar')).display`),'none');
    await run(`showView('study')`);await intact();
    // Keep controls and composer reachable at the minimum supported window size.
    win.setSize(1080,700);await sleep(150);await run(`$('expandConversation').click()`);await sleep(100);
    const small=await geometry();assert.ok(small.messagesHeight>100&&small.horizontal<=1&&small.send<=small.viewportHeight&&small.generate<=small.viewportHeight,JSON.stringify(small));await snapshot('小窗口放大对话');
    await advancedOptions();
    await run(`restoreConversationLayout()`);await win.reload();await until('state.ready&&state.conversation&&!conversationUI.restoring');
    assert.equal(await run(`conversationDisplay.expanded`),false);assert.equal(await run(`$('messages').querySelectorAll('.message').length`),2);
    // A native permission/runtime failure restores the layout and usable controls.
    ipcMain.removeHandler('studyforge:window-fullscreen');ipcMain.handle('studyforge:window-fullscreen',()=>{throw Error('模拟窗口切换失败');});
    await run(`$('fullscreenConversation').click()`);await until(`!conversationDisplay.busy`);
    assert.equal(await run(`conversationDisplay.expanded||conversationDisplay.fullscreen`),false);
    assert.equal(await run(`$('fullscreenConversation').disabled`),false);
    win.destroy();await open(false);
    await run(`$('fullscreenConversation').click()`);await until(`Boolean(document.fullscreenElement)&&conversationDisplay.fullscreen&&!conversationDisplay.busy`);
    await snapshot('浏览器全屏兼容路径');await keys('Escape');await until(`!document.fullscreenElement&&!conversationDisplay.expanded&&!conversationDisplay.busy`);
    assert.equal((await run(`api('/__display_test__/state')`)).model_calls,0);
    assert.equal(errors.length,0,errors.join('\n'));
    const result={ok:true,normal,ordinaryCollapsed,expanded,fullscreen,restored,small,normal_tools_toggle:true,normal_tools_reload_restores:true,native_fullscreen:true,browser_fullscreen:true,
      modal_escape_priority:true,original_scroll_preserved:true,draft_and_selection_preserved:true,same_conversation_dom:true,
      settings_unchanged:true,external_exit_synchronized:true,view_change_restores_navigation:true,search_shortcut_restores_navigation:true,
      advanced_settings_reachable:true,key_repeat_does_not_toggle:true,failure_recovers_controls:true,model_calls:0,errors};
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }finally{manager.dispose();if(win&&!win.isDestroyed())win.destroy();}
  app.quit();
}).catch(error=>{console.error(error.stack);if(win&&!win.isDestroyed())win.destroy();app.exit(1);});
