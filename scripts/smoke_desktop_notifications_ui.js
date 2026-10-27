const {app,BrowserWindow,Notification,ipcMain,shell}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {createNotificationManager,registerNotificationHandlers}=require('../desktop/notifications');
const {ensureNotificationIdentity}=require('../desktop/notification_identity');
const {registerWindowHandlers,attachWindowControls}=require('../desktop/window_controls');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_PERMISSION_CASE,'utf8'));
const root=path.dirname(process.env.STUDYFORGE_PERMISSION_CASE),repo=path.resolve(__dirname,'..');
app.setName('StudyForge');app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win,manager,identity,updater;const errors=[],created=[],nativeEvents=[],targets=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=async code=>{try{return await win.webContents.executeJavaScript(code,true);}catch(error){throw Error('Renderer command failed: '+code+'\n'+error.message+'\n'+JSON.stringify(errors));}};
async function until(code){for(let n=0;n<160;n++){if(await run(`(async()=>Boolean(${code}))()`))return;await sleep(50);}throw Error('Timeout: '+code);}
async function nativeUntil(predicate){for(let n=0;n<100;n++){if(predicate())return;await sleep(60);}throw Error('Timeout waiting for Windows notification event: '+JSON.stringify(nativeEvents));}
async function api(resource,method='GET',body){const r=await fetch(input.url+resource,{method,headers:{'X-StudyForge-Desktop-Token':input.owner_token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});if(!r.ok)throw Error(resource+' '+r.status+' '+await r.text());return r.json();}
async function click(selector){await until(`document.querySelector(${JSON.stringify(selector)})`);await run(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);await sleep(150);
  const r=await run(`(()=>{const el=document.querySelector(${JSON.stringify(selector)}),r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(!el||!(hit===el||el.contains(hit)))throw Error('Button is covered or hidden: '+${JSON.stringify(selector)});return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
  win.webContents.sendInputEvent({type:'mouseDown',...r,button:'left',clickCount:1});await sleep(30);win.webContents.sendInputEvent({type:'mouseUp',...r,button:'left',clickCount:1});await sleep(100);}
async function snapshot(name){win.webContents.invalidate();await sleep(180);fs.writeFileSync(path.join(root,name),(await win.webContents.capturePage()).toPNG());}
async function activateNotification(note){note.emit('click');await sleep(100);await run('desktopNoticeNavigation.then(()=>true)');}
function cleanup(){manager?.dispose();updater?.dispose();if(identity?.shortcut&&fs.existsSync(identity.shortcut))fs.unlinkSync(identity.shortcut);if(win&&!win.isDestroyed())win.destroy();}
app.whenReady().then(async()=>{
  try{
    identity=ensureNotificationIdentity({app,shell,root:repo,icon:path.join(repo,'desktop/assets/studyforge.ico'),
      appId:'org.studyforge.desktop.acceptance.'+randomUUID(),shortcutName:'StudyForge 通知验收-'+randomUUID()+'.lnk'});
    function Native(options){const notification=new Notification(options);created.push({notification,options});
      for(const event of ['show','click','failed'])notification.on(event,(_e,error)=>nativeEvents.push({event,title:options.title,error}));return notification;}
    Native.isSupported=()=>Notification.isSupported();
    win=new BrowserWindow({show:false,width:1480,height:960,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,
      backgroundThrottling:false,preload:path.join(repo,'desktop/preload.js')}});
    win.setPosition(-30000,-30000);
    win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    manager=createNotificationManager({Notification:Native,icon:path.join(repo,'desktop/assets/studyforge.ico'),getWindow:()=>win,
      showWindow:async target=>{targets.push(target);win.show();win.webContents.send('studyforge:desktop-navigate',target);},
      readFeed:()=>api('/api/desktop/notifications'),acknowledge:(ids,status)=>api('/api/desktop/notifications/ack','POST',{ids,status}),
      notify:value=>win.webContents.send('studyforge:notification-changed',value)});
    registerNotificationHandlers(ipcMain,new URL(input.url).origin,()=>win,manager);
    registerWindowHandlers(ipcMain,new URL(input.url).origin,()=>win);attachWindowControls(win);
    ipcMain.handle('studyforge:desktop-status',()=>({tray_available:true,quitting:false,window_visible:win.isVisible()}));
    updater=createUpdateManager({currentVersion:'0.3.5',packaged:false,storageDirectory:path.join(root,'updates'),
      publishers:[],initialFeed:'',createUpdater:()=>{throw Error('Source acceptance does not install updates');},
      notify:value=>win.webContents.send('studyforge:update-changed',value)});
    registerUpdateHandlers(ipcMain,new URL(input.url).origin,()=>win,updater,async()=>true,async()=>false);
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring');
    await manager.poll();
    await run(`showView('settings');showSettingsSection('notifications')`);
    await click('#testDesktopNotification');await nativeUntil(()=>nativeEvents.some(x=>x.event==='show'&&x.title.includes('桌面通知测试')));
    const osClick=JSON.parse(execFileSync('powershell',['-NoProfile','-ExecutionPolicy','Bypass','-File','scripts/click_native_notification.ps1',
      '-Title','StudyForge · Windows 桌面通知测试','-ScreenshotOut',path.join(root,'Windows原生通知.png')],{cwd:repo,windowsHide:true,encoding:'utf8',timeout:12000}));
    fs.writeFileSync(path.join(root,'os_click.json'),JSON.stringify(osClick,null,2));
    await sleep(200);
    if(osClick.clicked){await nativeUntil(()=>nativeEvents.some(x=>x.event==='click'));await until(`state.view==='settings'&&studioSettingsSection==='notifications'`);}

    await run(`selectProject(navigationUI.projects.find(x=>x.id===${JSON.stringify(input.project)}),{conversationId:${JSON.stringify(input.chat)}})`);
    const count=created.length;win.hide();const output=await api('/__desktop_notice_test__/output','POST');
    await manager.poll();assert.equal(created.length,count+1);assert.equal(win.isVisible(),false,'notification must not steal focus');
    await activateNotification(created.at(-1).notification);await until(`state.project?.id===${JSON.stringify(input.output_project)}&&state.conversation===${JSON.stringify(input.output_chat)}&&state.view==='artifacts'`);
    await until(`document.querySelector('[data-artifact="${output.id}"]')`);
    await snapshot('通知定位到另一项目成果.png');
    await manager.poll();assert.equal(created.length,count+1);

    await run(`selectProject(navigationUI.projects.find(x=>x.id===${JSON.stringify(input.project)}),{conversationId:${JSON.stringify(input.chat)}})`);
    await run(`showView('study');$('prompt').value='批准测试';$('sendMessage').click();`);
    await until(`$('agentApprovalRequests')?.querySelector('[data-approval-id]')`);win.hide();await manager.poll();
    const note=created.findLast(row=>row.options.title.includes('等待你的审批'));assert.ok(note);
    assert.equal((await api('/__chat_approval_test__/state')).files.target,'原内容');
    assert.ok((await api('/__chat_approval_test__/state')).active_chats.includes(input.chat));
    await activateNotification(note.notification);await until(`state.project?.id===${JSON.stringify(input.project)}&&state.conversation===${JSON.stringify(input.chat)}&&$('agentApprovalRequests')?.querySelector('.primary')`);
    await sleep(600);assert.equal((await api('/__chat_approval_test__/state')).files.target,'原内容');
    await snapshot('通知回到悬置审批.png');
    await click('#agentApprovalRequests .approval-actions .primary');await until(`(await api('/__chat_approval_test__/state')).files.target==='批准后自动完成'&&!isChatBusy()`);
    await manager.poll();assert.equal((await api('/__chat_approval_test__/state')).files.target,'批准后自动完成');

    const quiz=await api('/__desktop_notice_test__/questionnaire','POST');win.hide();await manager.poll();
    const causeNote=created.findLast(row=>row.options.title.includes('错因问卷'));assert.ok(causeNote);await activateNotification(causeNote.notification);
    await until(`state.project?.id===${JSON.stringify(input.output_project)}&&document.querySelector('[data-homework-questionnaire="${quiz.attempt}"]')`);
    assert.equal(await run(`$('messages').querySelector('[data-homework-questionnaire]').dataset.homeworkQuestionnaire`),quiz.attempt);

    await api('/__desktop_notice_test__/failure','POST');await manager.poll();assert.ok(created.some(row=>row.options.title.includes('未完成')));
    // Native delivery/callback checks are finished. Dismiss the fixture's
    // remaining OS banners before mouse-testing settings and dialog controls.
    for(const row of created)row.notification.close();await sleep(150);
    const beforeDisable=created.length;await run(`showView('settings');showSettingsSection('notifications');`);await sleep(300);await click('#desktopNotifyEnabled');
    await click('#saveDesktopNotifications');await until(`(await api('/api/settings')).desktop_notifications_enabled===false`);
    await api('/__desktop_notice_test__/output','POST');await manager.poll();assert.equal(created.length,beforeDisable);
    await click('#desktopNoticeBell');await until(`$('desktopNoticesDialog').open&&$('desktopNoticeList').children.length>=4`);
    await snapshot('软件内最近通知.png');
    await click('#closeDesktopNotices');
    await click('#desktopNotifyEnabled');
    assert.equal(await run(`applyDesktopNotificationSettings({desktop_notifications_enabled:false});$('desktopNotifyEnabled').checked`),true,'late reads must not overwrite an unsaved choice');
    await click('#saveDesktopNotifications');await until(`(await api('/api/settings')).desktop_notifications_enabled===true`);
    await manager.poll();assert.equal(created.length,beforeDisable,'reenabling must not replay old notices');
    await snapshot('桌面通知设置.png');
    assert.equal(nativeEvents.filter(x=>x.event==='failed').length,0);assert.deepEqual(errors,[]);
    const report={passed:true,windows_native_show:nativeEvents.some(x=>x.event==='show'),windows_banner_clicked:osClick.clicked,
      os_click:osClick,background_output:true,cross_project_and_chat_navigation:true,approval_waits_for_explicit_decision:true,
      questionnaire_opens_original_chat:true,no_duplicate_notification:true,settings_change_delivery:true,recent_notifications:true,
      paid_model_calls:0,native_events:nativeEvents,notification_count:created.length,console_errors:errors};
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(report,null,2));cleanup();app.exit(0);
  }catch(error){fs.writeFileSync(path.join(root,'failure.txt'),error.stack+'\n'+JSON.stringify({nativeEvents,errors}));console.error(error);cleanup();app.exit(1);}
});
