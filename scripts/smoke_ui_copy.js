const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-copy'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,code)=>w.webContents.executeJavaScript(code);
function create(width,height,partition){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false,partition}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function until(w,code){for(let i=0;i<450;i++){if(await run(w,code))return;await sleep(80);}throw Error('Wait failed: '+code);}
async function shot(w,name){await sleep(120);w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});w.webContents.debugger.detach();fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
const pass=value=>{checks.push(value);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify(checks,null,2));};
async function library(w){await run(w,"window.libraryOpen()");await until(w,"document.querySelector('[data-book-open]')");await run(w,`document.querySelector('[data-book-open="${data.book_id}"]').click()`);await until(w,"$('bookReadingNotice')&&$('bookNodes').children.length>0");}
app.whenReady().then(async()=>{
 try{
  const old=create(1440,1000,'copy-before');old.webContents.session.webRequest.onBeforeRequest({urls:[data.desktop_url+'/library.js']},(details,callback)=>callback({redirectURL:data.desktop_url+'/__copy_test__/before-library.js'}));
  await old.loadURL(data.desktop_url);await until(old,'state.ready&&state.conversation&&!conversationUI.restoring');await library(old);
  await run(old,"$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'))");await shot(old,'before-library');
  const oldText=await run(old,"$('bookReadingNotice').textContent");
  const pc=create(1440,1000,'copy-current');old.destroy();await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const original=await run(pc,"api('/__copy_test__/state')");await library(pc);
  await run(pc,"$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'))");
  assert(await run(pc,"$('bookReadingNotice').textContent.includes('先勾选')&&$('bookReadingNotice').textContent.includes('继续聊天')"));
  const shortText=await run(pc,"$('bookReadingNotice').textContent");assert(shortText.length<oldText.length/2);
  assert(await run(pc,"!$('bookReadingDetails').closest('details').open"));await shot(pc,'after-library');
  await run(pc,"const summary=$('bookReadingDetails').closest('details').querySelector('summary');summary.focus();summary.click()");
  await until(pc,"$('bookReadingDetails').closest('details').open");assert(await run(pc,"$('bookReadingDetails').textContent.includes('阅读模型')"));await shot(pc,'desktop-reading-help');
  await run(pc,"$('bookReadingDetails').closest('details').open=false;$('bookReadingDepth').value='deep';$('bookReadingDepth').dispatchEvent(new Event('change'))");
  assert(await run(pc,"$('readBookNodes').textContent==='详细阅读所选章节'&&!$('bookReadingFocusLabel').hidden&&$('bookReadingNotice').textContent.includes('详细阅读所选章节')"));
  await run(pc,"$('bookReadingDepth').value='index';$('bookReadingDepth').dispatchEvent(new Event('change'));$('bookReadingPriority').value='background';$('bookReadingPriority').dispatchEvent(new Event('change'))");
  assert(await run(pc,"$('bookReadingFocusLabel').hidden&&$('bookReadingNotice').textContent.includes('空闲后再读')"));
  pass('Library defaults show a short next action; settings changes update actual labels and the native explanatory disclosure opens');
  await run(pc,`document.querySelector('[data-book-select="${data.nodes[1].id}"]').click()`);
  assert(await run(pc,"$('readBookNodes').disabled&&!$('bookShowProgress').hidden"));await run(pc,"$('bookShowProgress').click()");
  assert(await run(pc,"document.activeElement.id==='bookJobs'&&$('bookJobs').textContent.includes('已暂停')"));
  await run(pc,"$('clearBookSelection').click();$('selectAllBookNodes').click()");assert.equal(await run(pc,"studyforgeBookLibrary.selected.size"),data.nodes.length);await run(pc,"$('clearBookSelection').click()");
  pass('Busy selection explains why Start is unavailable, jumps to the paused job, and Select all/Clear still change the actual selection');
  for(const view of ['sources','artifacts','exercises','profile','goals','study']){await run(pc,`showView('${view}')`);await until(pc,`$('view-${view}').classList.contains('active')`);await shot(pc,'desktop-'+view);}
  await run(pc,"showView('settings')");
  for(const section of ['models','generation','tools','notifications','system','appearance']){await run(pc,`showSettingsSection('${section}')`);assert(await run(pc,`!$('settings-${section}').hidden`));await shot(pc,'desktop-settings-'+section);}
  await run(pc,"showAppearanceTab('surfaces')");assert(await run(pc,"$('appearance-tab-surfaces').textContent==='各区域外观'"));await shot(pc,'desktop-region-help');
  pass('All main desktop views and six settings groups open with rewritten help and no UI errors');
  await run(pc,`showView('study');studyforgeSourceScope.open({id:'${data.stored_source_id}',kind:'.pdf',name:'只想读一页.pdf'})`);
  await until(pc,"$('sourceScopeDialog').open");assert(await run(pc,"$('scopeMode').value==='pages'&&$('scopeStatus').textContent.includes('选好')"));await shot(pc,'desktop-select-pages');await run(pc,"$('closeSourceScope').click()");
  await run(pc,"studyforgeUserGuide.open('library')");await until(pc,"$('userGuideDialog').open&&$('userGuideDialog').querySelector('iframe').contentDocument?.querySelector('#library')");
  assert(await run(pc,"$('userGuideDialog').querySelector('iframe').contentDocument.querySelector('#library').textContent.includes('优先开始')"));await shot(pc,'desktop-guide');
  await run(pc,"$('userGuideDialog').querySelector('header button').click()");
  const afterHelp=await run(pc,"api('/__copy_test__/state')");assert.equal(afterHelp.model_requests,0);assert.equal(afterHelp.messages,original.messages);assert(afterHelp.sources.some(s=>s.id===data.stored_source_id&&s.status==='stored'));
  pass('Source guidance opens before parsing; the offline guide and all help leave chat, model requests and unparsed originals untouched');
  // Exercise the real action behind the renamed reading button using a controlled model.
  await library(pc);await run(pc,`document.querySelector('[data-book-select="${data.nodes[2].id}"]').click();$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));$('readBookNodes').click()`);
  await until(pc,"studyforgeBookLibrary.jobs.some(j=>j.id!=='"+data.paused_job_id+"'&&j.kind==='read'&&['completed','failed'].includes(j.status))");
  assert(await run(pc,"studyforgeBookLibrary.jobs.some(j=>j.id!=='"+data.paused_job_id+"'&&j.kind==='read'&&j.status==='completed')"));
  const withReading=await run(pc,"api('/__copy_test__/state')");assert(withReading.model_requests>0);pass('The renamed Start button completes a real chapter-reading job and saves its result with an offline controlled model');
  const phone=create(390,844,'copy-phone'),ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((r,callback)=>{let ok=false;try{ok=r.hostname==='127.0.0.1'&&new X509Certificate(r.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='界面说明手机验收 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat");
  for(const id of ['optionsDialog','materialsDialog','generateDialog','artifactsDialog']){await run(phone,`openSheet('${id}')`);await shot(phone,'phone-'+id);assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth+1"));await run(phone,`$('${id}').close()`);}
  await library(phone);assert(await run(phone,"$('bookReadingDetails')&&!$('bookReadingDetails').closest('details').open"));
  for(const width of [390,320]){phone.setSize(width,844);await sleep(120);assert(await run(phone,"$('mobileBookLibrary').scrollWidth<=$('mobileBookLibrary').clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1"));await shot(phone,'phone-library-'+width);}
  pass('Actual HTTPS pairing succeeds; mobile options, material upload help, generation and artifacts open, and library help fits at 390 and 320 pixels');
  await run(phone,"$('mobileBookLibrary').close();studyforgeUserGuide.open('homework')");await until(phone,"$('userGuideDialog').querySelector('iframe').contentDocument?.querySelector('#homework')");await shot(phone,'phone-guide');
  const final=await run(pc,"api('/__copy_test__/state')");assert.equal(final.model_requests,withReading.model_requests);assert.equal(final.messages,original.messages);
  pass('Phone help uses the same guide without new model calls or chat messages');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,before_notice:oldText,after_notice:shortText,controlled_model_requests:final.model_requests,external_model_requests:0,console_errors:errors},null,2));
  windows.filter(w=>!w.isDestroyed()).forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const[i,w]of windows.entries())if(!w.isDestroyed())await shot(w,'failed-'+i);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.filter(w=>!w.isDestroyed()).forEach(w=>w.destroy());app.exit(1);}
});
