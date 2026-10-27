/* Exercise local help in real desktop and phone renderers, with no paid AI. */
const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const caseFile=process.env.STUDYFORGE_MOBILE_CASE,root=path.dirname(caseFile),data=JSON.parse(fs.readFileSync(caseFile,'utf8'));
app.setPath('userData',path.join(root,'electron-guide-profile'));app.disableHardwareAcceleration();
let desktop,phone;const errors=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.on('window-all-closed',()=>{});
async function run(win,code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,200)+'\n'+error.message);}}
async function until(win,code){for(let n=0;n<160;n++){if(await run(win,code))return;await pause(100);}throw new Error('Timed out: '+code);}
const guideExpression=code=>`(()=>{const doc=document.querySelector('#userGuideDialog iframe').contentDocument;return (${code});})()`;
async function inside(win,code){return run(win,guideExpression(code));}
async function ready(win){await until(win,`$('userGuideDialog').open && $('userGuideDialog').querySelector('iframe').contentDocument?.getElementById('guideSearch') && $('userGuideDialog').querySelector('.user-guide-loading').hidden`);await pause(150);}
async function screenshot(win,name){await run(win,'new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');win.webContents.invalidate();await pause(250);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
function windowFor(width,height,preload=false){
  const win=new BrowserWindow({show:false,width,height,webPreferences:{...(preload?{preload:path.resolve('desktop/preload.js')}:{ }),contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|ERR_CERT|IPC channel/i.test(event.message))errors.push(event.message);});return win;
}
app.on('certificate-error',(event,_contents,_url,_error,_certificate,callback)=>{event.preventDefault();callback(true);});
app.whenReady().then(async()=>{
  try {
    for(const [channel,value] of [['desktop-status',{tray_available:false}],['window-state',{fullscreen:false}],['update-status',{state:'idle'}],['notification-status',{supported:false}],['startup-status',{available:false,enabled:false,start_hidden:true}],['mobile-status',{running:false,interfaces:[]}]] ) ipcMain.handle('studyforge:'+channel,()=>value);
    desktop=windowFor(1440,960,true);await desktop.loadURL(data.desktop_url);await until(desktop,'state.ready && state.conversation && !conversationUI.restoring');
    await run(desktop,`(async()=>{const body=new FormData();body.append('project_id',state.project.id);body.append('file',new File(['原文件仍然待解析。'],'指南验收.txt'));await api('/api/import/file',{method:'POST',body});await refreshSources();$('prompt').value='这条未发送的问题必须保留';})()`);
    const snapshotCode=`JSON.stringify({chat:state.conversation,project:state.project.id,selected:[...state.selected],draft:$('prompt').value,html:[...$('messages').children].filter(x=>x.id!=='agentApprovalRequests').map(x=>x.outerHTML),sources:state.sources.map(x=>[x.id,x.status])})`;
    const snapshot=await run(desktop,snapshotCode);
    await run(desktop,"$('openUserGuide').click()");await ready(desktop);
    const sectionCount=19;
    assert.equal(await inside(desktop,"doc.querySelectorAll('.guide-section').length"),sectionCount);
    assert.ok(await inside(desktop,"doc.getElementById('library').textContent.includes('自动定位')"));
    await screenshot(desktop,'guide-desktop-light');
    await run(desktop,guideExpression(`(()=>{doc.querySelector('.guide-task-grid a[href="#start"]').click();return true;})()`));
    assert.ok(await inside(desktop,"doc.getElementById('guideMain').scrollTop > 100"),'The first-use card must move to the steps');
    await run(desktop,"$('userGuideDialog').querySelector('iframe').contentWindow.document.querySelector('[href=\"#materials\"]').click()");
    assert.equal(await inside(desktop,"doc.defaultView.location.hash"),'#materials');
    await pause(400);assert.equal(await inside(desktop,"doc.defaultView.location.hash"),'#materials','Background settings refresh reset the reading position');
    assert.ok(await inside(desktop,"doc.getElementById('materials').textContent.includes('3-5,8')"));
    await screenshot(desktop,'guide-reading-scope');
    // Task cards and in-text links use the same navigation as the directory.
    await run(desktop,guideExpression(`(()=>{doc.querySelector('.guide-task-grid a[href="#outputs"]').click();return true;})()`));
    assert.equal(await inside(desktop,"doc.defaultView.location.hash"),'#outputs');
    assert.equal(await inside(desktop,"doc.querySelector('#guideContents a[href=\"#outputs\"]').getAttribute('aria-current')"),'true');
    await run(desktop,guideExpression(`(()=>{doc.querySelector('#guideContents a[href="#materials"]').click();return true;})()`));
    // Search must reveal a matching answer inside a collapsed disclosure.
    await run(desktop,guideExpression(`(()=>{doc.getElementById('guideSearch').value='429';doc.getElementById('guideSearch').dispatchEvent(new Event('input'));return true;})()`));
    assert.equal(await inside(desktop,"[...doc.querySelectorAll('#troubleshooting details')].find(x=>x.textContent.includes('Too Many Requests')).open"),true);
    await run(desktop,guideExpression(`(()=>{doc.getElementById('clearGuideSearch').click();return true;})()`));
    assert.equal(await inside(desktop,"[...doc.querySelectorAll('#troubleshooting details')].find(x=>x.textContent.includes('Too Many Requests')).open"),false);
    await run(desktop,guideExpression(`(()=>{doc.getElementById('guideSearch').value='费曼';doc.getElementById('guideSearch').dispatchEvent(new Event('input'));return true;})()`));
    assert.ok(await inside(desktop,`doc.querySelectorAll('.guide-section:not([hidden])').length < ${sectionCount}`));
    assert.ok(await inside(desktop,"!doc.getElementById('homework').hidden"));
    await run(desktop,guideExpression(`(()=>{doc.getElementById('guideSearch').value='[unlikely-no-result]';doc.getElementById('guideSearch').dispatchEvent(new Event('input'));return true;})()`));
    assert.equal(await inside(desktop,"doc.getElementById('guideNoResults').hidden"),false);
    await run(desktop,guideExpression(`(()=>{doc.getElementById('clearGuideSearch').click();return true;})()`));
    assert.equal(await inside(desktop,"doc.querySelectorAll('.guide-section:not([hidden])').length"),sectionCount);
    await run(desktop,"document.documentElement.dataset.theme='forest'");await pause(150);
    assert.equal(await inside(desktop,"doc.defaultView.location.hash"),'#materials','A theme update reset the guide chapter');
    // Untrusted windows cannot drive help navigation.
    await run(desktop,"window.dispatchEvent(new MessageEvent('message',{origin:location.origin,data:{type:'studyforge-guide-action',action:'profile'},source:window}))");
    assert.equal(await run(desktop,'state.view'),'study');assert.equal(await run(desktop,"$('userGuideDialog').open"),true);
    // Clipboard denial must still leave a usable, selected example.
    await run(desktop,guideExpression(`(()=>{Object.defineProperty(doc.defaultView.navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied');}}});doc.execCommand=()=>false;doc.querySelector('[data-copy-example=firstQuestion]').click();return true;})()`));
    await until(desktop,guideExpression("doc.getElementById('guideCopyStatus').textContent.includes('已选中')"));
    assert.ok(await inside(desktop,"doc.defaultView.getSelection().toString().includes('请只使用我选中的资料')"));
    await run(desktop,guideExpression(`(()=>{doc.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;})()`));await until(desktop,"!$('userGuideDialog').open");
    assert.equal(await run(desktop,snapshotCode),snapshot);
    // Local, contextual help starts at the actual operation, not the cover page.
    await run(desktop,"document.querySelector('.context-toolbar [data-open-user-guide=materials]').click()");await ready(desktop);
    assert.equal(await inside(desktop,"doc.defaultView.location.hash"),'#materials');
    await run(desktop,"$('userGuideDialog').close();window.studyforgeUserGuide.open('teaching-review')");await ready(desktop);
    assert.equal(await inside(desktop,"doc.defaultView.location.hash"),'#teaching-review');
    await run(desktop,"$('userGuideDialog').close()");
    await run(desktop,"document.dispatchEvent(new KeyboardEvent('keydown',{key:'F1',bubbles:true,cancelable:true}))");await ready(desktop);
    await run(desktop,"document.documentElement.dataset.theme='night'");await until(desktop,guideExpression("doc.documentElement.dataset.theme==='dark'"));await screenshot(desktop,'guide-desktop-dark');
    await run(desktop,guideExpression(`(()=>{doc.querySelector('[data-guide-action=models]').click();return true;})()`));await until(desktop,"!$('userGuideDialog').open && state.view==='settings' && !$('settings-models').hidden");
    assert.equal(await run(desktop,"$('prompt').value"),'这条未发送的问题必须保留');
    phone=windowFor(390,844);await phone.loadURL(data.mobile_url);await until(phone,"Boolean(document.querySelector('#pairScreen [data-open-user-guide]') && window.studyforgeUserGuide)");
    await run(phone,"document.querySelector('#pairScreen [data-open-user-guide]').click()");await ready(phone);
    assert.equal(await inside(phone,"doc.defaultView.location.hash"),'#phone');
    assert.equal(await inside(phone,"doc.querySelectorAll('[data-guide-action]:not([hidden])').length"),0,'An unpaired phone should not open authenticated controls');
    const layout=await inside(phone,"({overflow:doc.documentElement.scrollWidth-doc.defaultView.innerWidth,width:doc.defaultView.innerWidth})");assert.ok(layout.overflow<=1,JSON.stringify(layout));await screenshot(phone,'guide-phone-connection');
    await run(phone,guideExpression(`(()=>{doc.getElementById('mobileGuideNav').click();return true;})()`));
    assert.equal(await inside(phone,"doc.activeElement.id"),'guideSearch');
    await run(phone,guideExpression(`(()=>{doc.getElementById('guideSearch').value='提交';doc.getElementById('guideSearch').dispatchEvent(new Event('input'));return true;})()`));
    assert.equal(await inside(phone,"doc.getElementById('homework').hidden"),false);
    await run(phone,"$('userGuideDialog').close()");
    // Pair through the actual gateway, then exercise an in-app help jump.
    const pairing=await run(phone,`api('/mobile/pair',json('POST',{code:'${data.pairing_code}',name:'指南验收手机'}))`);
    const decision=await fetch(data.desktop_url+`/api/mobile/devices/${pairing.device_id}/approve`,{method:'POST',headers:{'Content-Type':'application/json','X-StudyForge-Desktop-Token':data.token},body:JSON.stringify({approved:true})});assert.equal(decision.ok,true,await decision.text());
    await run(phone,`api('/mobile/pair/${pairing.device_id}',{headers:{'X-Mobile-Pair-Ticket':'${pairing.ticket}'}})`);
    await phone.reload();await until(phone,'mobile.authenticated && mobile.chat');
    await run(phone,"$('prompt').value='手机草稿不能丢';$('prompt').dispatchEvent(new Event('input'));$('openOptions').click();document.querySelector('#optionsDialog [data-open-user-guide]').click()");await ready(phone);
    await run(phone,"document.documentElement.dataset.theme='dark'");await until(phone,guideExpression("doc.documentElement.dataset.theme==='dark'"));await screenshot(phone,'guide-phone-dark');
    phone.setSize(320,760);await pause(150);
    assert.ok(await inside(phone,"doc.documentElement.scrollWidth-doc.defaultView.innerWidth<=1"));
    await run(phone,guideExpression(`(()=>{doc.querySelector('[data-guide-action=sources]').click();return true;})()`));await until(phone,"!$('userGuideDialog').open && $('materialsDialog').open");assert.equal(await run(phone,"$('prompt').value"),'手机草稿不能丢');
    const calls=path.join(root,'requests.json');assert.equal(fs.existsSync(calls),false,'Opening help must not trigger a model request');
    assert.deepEqual(errors,[]);
    const checks=['19 task-oriented topics and exact scope instructions','desktop help entry and F1','task cards and inline section navigation','search reveals collapsed answers and restores disclosure states','contextual materials help and review-record help','literal keyword search and empty results','guarded action navigation','clipboard denial and manual-copy fallback','Esc from embedded guide','draft/history/selection/parse status preserved','light and dark readability','HTTPS phone help before pairing','no authenticated shortcuts before pairing','remembered device help navigation','390px and 320px without overflow','phone draft preserved','no model calls'];
    fs.writeFileSync(path.join(root,'ui-report.json'),JSON.stringify({passed:true,checks},null,2));console.log('USER_GUIDE_UI_PASS '+root);app.exit(0);
  }catch(error){console.error(error.stack);fs.writeFileSync(path.join(root,'ui-errors.json'),JSON.stringify({error:String(error.stack),console:errors},null,2));if(desktop)await screenshot(desktop,'desktop-failure');if(phone)await screenshot(phone,'phone-failure');app.exit(1);}
});
