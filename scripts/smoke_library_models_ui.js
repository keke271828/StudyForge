/* Real Electron pages and paired HTTPS, isolated data and mocked providers. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-models'));app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
const pass=text=>{checks.push(text);fs.appendFileSync(path.join(folder,'models-ui-log.txt'),text+'\n');};
async function until(w,c){for(let i=0;i<350;i++){if(await run(w,c))return;await sleep(100);}throw new Error('UI wait failed: '+c);}
function watch(w){w.webContents.on('console-message',e=>{if(e.level==='error'&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const image=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(image.data,'base64'));}
function change(values){return `(()=>{const panel=document.querySelector('.book-model-settings');panel.open=true;for(const [key,value] of Object.entries(${JSON.stringify(values)})){const e=panel.querySelector('[data-field="'+key+'"]');e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}})()`;}
async function save(w){await run(w,"document.querySelector('[data-save-model]').click()");await until(w,"!document.querySelector('[data-model-summary]').textContent.includes('未保存')&&!document.querySelector('[data-model-status]').textContent.includes('正在保存')");}
async function choose(w){await run(w,`libraryOpen('${data.book_id}')`);await until(w,`studyforgeBookLibrary.loadedBook==='${data.book_id}'&&document.querySelector('[data-model-summary]').textContent.includes('跟随工作台')||studyforgeBookLibrary.loadedBook==='${data.book_id}'&&document.querySelector('[data-model-summary]').textContent.includes('独立设置')`);}
function read(w,node,focus=''){
 return run(w,`(()=>{studyforgeBookLibrary.selected=new Set(['${node}']);const box=document.querySelector('[data-book-select="${node}"]');box.checked=true;box.dispatchEvent(new Event('change'));$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));${focus?`$('bookReadingDepth').value='deep';$('bookReadingDepth').dispatchEvent(new Event('change'));$('bookReadingFocus').value=${JSON.stringify(focus)};$('bookReadingFocus').dispatchEvent(new Event('input'));`:''}$('readBookNodes').click();})()`);
}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc);
  assert(await run(pc,"document.querySelector('[data-field=mode]').value==='follow'&&document.querySelector('[data-model-preview]').textContent.includes('不')===false"));
  const chatBefore=await run(pc,"JSON.stringify({provider:$('provider').value,model:currentModel(),effort:currentEffort(),chat:state.conversation})");
  await run(pc,change({mode:'independent',provider:'deepseek',model:'library-reader',effort:'high',vision_mode:'custom',vision_model:'library-vision'}));await save(pc);
  assert.equal(await run(pc,"JSON.stringify({provider:$('provider').value,model:currentModel(),effort:currentEffort(),chat:state.conversation})"),chatBefore);
  assert(await run(pc,"document.querySelector('[data-model-preview]').textContent.includes('library-reader')&&document.querySelector('[data-model-preview]').textContent.includes('library-vision')"));
  pass('Independent reading and scan models save without changing the workbench conversation');
  await run(pc,"document.querySelector('[data-refresh-models]').click()");await until(pc,"!document.querySelector('[data-refresh-models]').disabled");
  assert(await run(pc,"[...$('bookReadingModelChoices').options].some(o=>o.value==='library-reader')"));
  assert.equal((await run(pc,"api('/__library_models_test__/state')")).calls.length,0);pass('Model catalog loads into the manual-compatible picker without a generation call');
  await read(pc,data.field_node_id,'ONLY_THIS_BOOK_FOCUS');await until(pc,"api('/__library_models_test__/state').then(r=>r.entered)");
  const job=await run(pc,"studyforgeBookLibrary.jobs.find(j=>j.kind==='read')");assert.equal(job.payload.model,'library-reader');assert.equal(job.payload.effort,'high');assert.equal(job.payload.vision_model,'library-vision');
  await until(pc,"document.querySelector('.book-job-model')?.textContent.includes('library-vision')");
  await run(pc,`api('/api/library/jobs/${job.id}/pause',{method:'POST'})`);
  await run(pc,"api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({deepseek_vision_model:'changed-global-vision'})})");
  await run(pc,change({model:'library-next-reader',vision_model:'library-next-vision',effort:'low'}));await save(pc);
  await run(pc,"api('/__library_models_test__/release',{method:'POST'})");await until(pc,`api('/api/library/jobs').then(r=>r.jobs.find(j=>j.id==='${job.id}').status==='paused')`);
  await run(pc,`api('/api/library/jobs/${job.id}/resume',{method:'POST'})`);await until(pc,`api('/api/library/jobs').then(r=>r.jobs.find(j=>j.id==='${job.id}').status==='completed')`);
  const calls=(await run(pc,"api('/__library_models_test__/state')")).calls;
  assert.equal(calls.length,1);assert.equal(calls[0].model,'library-reader');assert.equal(calls[0].reasoning_effort,'high');
  assert(calls[0].messages.at(-1).content.includes('ONLY_THIS_BOOK_FOCUS'));assert(!calls[0].messages.some(m=>String(m.content).includes('聊天记录')));
  pass('A live reading uses its selected model and isolated source context; changed settings and pause/resume do not change it or duplicate its model request');
  await pc.reload();await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc);
  assert(await run(pc,"document.querySelector('[data-field=model]').value==='library-next-reader'&&document.querySelector('[data-field=vision_model]').value==='library-next-vision'&&document.querySelector('[data-field=effort]').value==='low'"));
  pass('Independent library choices survive page reload');
  await run(pc,"document.querySelector('.book-model-settings').open=true");
  assert(await run(pc,"document.querySelector('.book-model-body').clientHeight>100&&$('bookShelf').clientHeight>=64&&$('bookDetail').clientHeight>100&&document.querySelector('.book-model-settings').scrollWidth<=document.querySelector('.book-model-settings').clientWidth+1"));
  await shot(pc,'desktop-library-models');pass('Desktop model settings scroll independently while the book list and directory remain usable');
  await run(pc,change({provider:data.third_party_provider,model:'third-party-reader'}));await save(pc);
  assert(await run(pc,"document.querySelector('[data-field=effort]').disabled&&document.querySelector('[data-vision]').hidden"));
  assert(await run(pc,"document.querySelector('[data-model-preview]').textContent.includes('未启用图片读取')"));
  await read(pc,data.polynomial_node_id);await until(pc,"api('/api/library/jobs').then(r=>r.jobs.some(j=>j.payload.model==='third-party-reader'&&j.status==='completed'))");
  assert((await run(pc,"api('/__library_models_test__/state')")).calls.some(c=>c.model==='third-party-reader'));
  pass('An independently selected third party service receives the actual library reading request');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='书库模型验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");await choose(phone);
  assert(await run(phone,`document.querySelector('[data-field=provider]').value==='${data.third_party_provider}'&&document.querySelector('[data-field=model]').value==='third-party-reader'`));
  pass('A genuinely paired HTTPS phone receives the same saved library configuration and available services');
  await run(phone,change({provider:'deepseek',model:'phone-reader',effort:'max',vision_mode:'same'}));await save(phone);
  assert(await run(phone,"document.querySelector('[data-model-preview]').textContent.includes('扫描页核对 phone-reader')"));
  await read(phone,data.polynomial_node_id);await until(phone,"api('/api/library/jobs').then(r=>r.jobs.some(j=>j.payload.model==='phone-reader'&&j.payload.vision_model==='phone-reader'&&j.status==='completed'))");
  const phoneCall=(await run(pc,"api('/__library_models_test__/state')")).calls.find(c=>c.model==='phone-reader');assert.equal(phoneCall.reasoning_effort,'max');
  pass('The phone can choose an independent model and strength; its actual new reading request uses them');
  for(const width of [390,320]){phone.setSize(width,844);await sleep(200);assert(await run(phone,"$('mobileBookLibrary').scrollWidth<=$('mobileBookLibrary').clientWidth+1&&document.querySelector('.book-model-settings').scrollWidth<=document.querySelector('.book-model-settings').clientWidth+1"));await shot(phone,'phone-library-models-'+width);}
  pass('Phone model controls stay readable and scrollable at 390 and 320 pixels');
  await run(pc,"document.querySelector('[data-reload-models]').click()");await until(pc,"document.querySelector('[data-field=model]').value==='phone-reader'");
  await run(pc,change({mode:'follow',vision_mode:'configured'}));await save(pc);
  const actual=await run(pc,"({model:currentModel(),effort:currentEffort()})");await read(pc,data.field_node_id,'FOLLOW_MODEL_NEW_FOCUS');
  await until(pc,"api('/api/library/jobs').then(r=>r.jobs.some(j=>j.payload.focus==='FOLLOW_MODEL_NEW_FOCUS'&&j.status==='completed'))");
  const follow=(await run(pc,"api('/__library_models_test__/state')")).calls.at(-1);assert.equal(follow.model,actual.model);
  assert.equal(follow.reasoning_effort??null,actual.effort==='none'?null:actual.effort);
  pass('Switching back to follow mode changes the actual subsequent model request, rather than just its label');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'models-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:4,external_model_requests:0},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(e){fs.writeFileSync(path.join(folder,'models-ui-report.json'),JSON.stringify({passed:false,error:e.stack||String(e),checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'models-failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
