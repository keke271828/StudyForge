const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {AUTO_FLAG,HIDDEN_FLAG}=require('../desktop/startup');
const {readWindowsEntry}=require('../desktop/windows_startup');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
exports.run=async({app,window:win,lifecycle,backend,url,report,startupManager,ownerToken})=>{
  const result={ok:false,desktop_pid:process.pid,backend_pid:backend.pid,checks:[]};
  const request=async route=>(await fetch(url+route,{headers:{'X-StudyForge-Desktop-Token':ownerToken}})).json();
  async function until(check,label){for(let i=0;i<150;i++){if(await check())return;await sleep(100);}throw new Error('Startup check timeout: '+label);}
  const execute=code=>win.webContents.executeJavaScript(code);
  async function clickVisible(id){
    const point=await execute(`(()=>{const el=document.getElementById(${JSON.stringify(id)}),r=el.getBoundingClientRect();if(!r.width||!r.height||r.top<0||r.bottom>innerHeight)throw new Error('Control is outside viewport');return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()`);
    win.webContents.sendInputEvent({type:'mouseMove',...point});
    win.webContents.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,...point});
    win.webContents.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,...point});
  }
  async function secondLaunch(args){
    const child=spawn(process.execPath,[path.resolve(__dirname,'..'),...args],{cwd:path.resolve(__dirname,'..'),env:process.env,windowsHide:true,stdio:'ignore'});
    try{await until(()=>child.exitCode!==null,'duplicate exits');}finally{if(child.exitCode===null)child.kill();}
  }
  try{
    await until(()=>execute('Boolean(state.ready && state.conversation && !conversationUI.restoring)'),'desktop initialized');
    assert.equal(win.isVisible(),false);assert.equal(lifecycle.status().tray_available,true);
    assert.equal((await request('/api/health')).ok,true);
    assert.equal((await request('/api/mobile/status')).running,true);
    result.checks.push('hidden autostart prepares backend, native tray and saved mobile gateway');
    await execute("showView('settings');refreshDesktopControls()");
    await until(()=>execute("Boolean($('saveDesktopStartup')&&!$('saveDesktopStartup').disabled)"),'startup controls');
    await execute("$('desktopAutoStart').checked=true;$('desktopAutoStart').dispatchEvent(new Event('change'));$('saveDesktopStartup').click()");
    await until(()=>startupManager.status().enabled,'real Windows startup registration');
    result.native_launch=readWindowsEntry(startupManager.status().launch_name);
    assert.ok(result.native_launch.args.includes(AUTO_FLAG)&&result.native_launch.args.includes(HIDDEN_FLAG));
    result.checks.push('UI registers actual current-user Windows entry with quoted source path');
    await until(()=>execute("!$('saveDesktopStartup').disabled"),'save finished');
    await execute("$('desktopStartHidden').checked=false;$('desktopStartHidden').dispatchEvent(new Event('change'));$('saveDesktopStartup').click()");
    await until(()=>startupManager.status().enabled&&!startupManager.status().start_hidden,'foreground choice saved');
    const foreground=readWindowsEntry(result.native_launch.name);
    assert.equal(foreground.args.includes(HIDDEN_FLAG),false);
    result.checks.push('foreground choice really changes Windows launch arguments');
    app.setLoginItemSettings({name:foreground.name,path:foreground.path,args:foreground.args,openAtLogin:true,enabled:false});
    await execute("$('refreshDesktopStartup').click()");
    await until(()=>execute("$('desktopStartupStatus').textContent.includes('Windows 已禁用')"),'Windows disabled status');
    assert.equal(startupManager.status().enabled,false);
    await execute("$('desktopAutoStart').checked=true;$('desktopAutoStart').dispatchEvent(new Event('change'));$('desktopStartHidden').checked=true;$('saveDesktopStartup').click()");
    await until(()=>startupManager.status().enabled&&startupManager.status().start_hidden,'re-enable in UI');
    result.checks.push('Windows Task Manager disablement is reflected and explicit re-enable works');
    await until(()=>execute("!$('saveDesktopStartup').disabled"),'UI ready');
    await execute("$('saveDesktopStartup').click()");
    await until(()=>execute("!$('saveDesktopStartup').disabled"),'repeat save');
    assert.equal(readWindowsEntry(foreground.name).enabled,true);
    await secondLaunch([AUTO_FLAG,HIDDEN_FLAG]);assert.equal(win.isVisible(),false);
    result.checks.push('repeated auto launch neither opens the hidden window nor duplicates the service');
    await secondLaunch([]);await until(()=>win.isVisible(),'manual launch opens existing window');
    assert.equal((await request('/api/health')).ok,true);
    result.checks.push('manual launch restores the same window and running backend');
    await execute("showView('settings');$('settings-tab-system').click();document.querySelector('.desktop-startup-card').scrollIntoView({block:'center'})");
    await sleep(300);
    assert.equal(await execute("!$('settings-system').hidden && document.querySelector('.desktop-startup-card').getBoundingClientRect().height>0"),true);
    fs.writeFileSync(path.join(path.dirname(report),'startup-settings.png'),(await win.webContents.capturePage()).toPNG());
    await clickVisible('desktopAutoStart');
    await until(()=>execute("!$('desktopAutoStart').checked"),'native checkbox click');
    await clickVisible('saveDesktopStartup');
    await until(()=>!startupManager.status().registered,'startup removed');
    result.checks.push('visible settings and native mouse clicks disable the owned Windows entry');
    const unicodeArgs=[path.join(path.dirname(report),'中文学习目录'),AUTO_FLAG,HIDDEN_FLAG];
    app.setLoginItemSettings({name:foreground.name,path:foreground.path,args:unicodeArgs,openAtLogin:true,enabled:true});
    assert.deepEqual(readWindowsEntry(foreground.name).args,unicodeArgs);
    result.checks.push('Windows entry lookup preserves Chinese directory names');result.ok=true;
  }catch(error){
    result.error=error.stack;
    result.native_debug=readWindowsEntry(startupManager.status().launch_name);
    result.ui_debug=await execute("({text:$('desktopStartupStatus').textContent,enabled:$('desktopAutoStart').checked,hidden:$('desktopStartHidden').checked})").catch(()=>null);
  }
  finally{
    try{startupManager.save({enabled:false,start_hidden:true});result.acceptance_entry_removed=true;}catch(error){result.cleanup_error=error.message;result.ok=false;}
    fs.writeFileSync(report,JSON.stringify(result,null,2));lifecycle.quit();
  }
};
