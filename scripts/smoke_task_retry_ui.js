/* Real Electron renderers and a paired HTTPS mobile browser. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-retry'));app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<500;n++){if(await run(w,c))return;await sleep(80);}throw new Error('UI wait failed: '+c);}
const pass=s=>checks.push(s);
function watch(w){w.webContents.on('console-message',e=>{if(e.level==='error'&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const pic=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(pic.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&Boolean(window.studyforgeTaskRetry)");
  await run(pc,"showView('settings');showSettingsSection('generation')");
  assert(await run(pc,"$('taskAutoRetry').checked&&$('taskRetryLimit').value==='5'"));
  await run(pc,"$('taskRetryLimit').value='8';$('saveScheduling').click()");
  await until(pc,"api('/api/settings').then(s=>s.task_retry_limit===8)");
  await pc.reload();await until(pc,"state.ready&&$('taskRetryLimit').value==='8'");
  pass('Default retry switch and 5-attempt setting are visible; saved 8 persists after reload');
  await run(pc,"showView('settings');showSettingsSection('generation');$('taskRetryLimit').value='5';$('saveScheduling').click()");
  await until(pc,"api('/api/settings').then(s=>s.task_retry_limit===5)");
  const project=await run(pc,"api('/__retry_test__/project',{method:'POST'})");
  await run(pc,"showView('artifacts');refreshArtifacts()");
  await until(pc,`api('/api/jobs/${project.job_id}').then(j=>j.retry.state==='waiting')`);
  await run(pc,"refreshArtifacts()");
  await until(pc,"document.querySelector('.task-retry-status')?.textContent.includes('1/5')");
  await shot(pc,'desktop-waiting-retry');pass('A genuine failed generation displays its retry count and delay instead of a terminal failure');
  await run(pc,`api('/api/jobs/${project.job_id}/pause',{method:'POST'})`);
  await until(pc,`api('/api/jobs/${project.job_id}').then(j=>j.status==='paused')`);
  await sleep(1700);assert.equal((await run(pc,"api('/__retry_test__/state')")).failures['retry-project'],1);
  await run(pc,`api('/api/jobs/${project.job_id}/resume',{method:'POST'})`);
  await until(pc,`api('/api/jobs/${project.job_id}').then(j=>j.status==='completed'&&j.retry.retry_count===5)`);
  const files=await run(pc,`api('/api/projects/${data.project_id}/artifacts')`);assert.equal(files.length,1);assert.equal(files[0].format,'docx');
  assert.equal((await run(pc,"api('/__retry_test__/state')")).failures['retry-project'],5);
  pass('Pausing stops retries; resuming the same task recovers after exactly five retry cycles and produces one DOCX');
  const book=await run(pc,"api('/__retry_test__/book',{method:'POST'})");
  await run(pc,`libraryOpen('${data.book_id}')`);await until(pc,"document.querySelector('#bookJobs .task-retry-status')?.textContent.includes('1/5')");
  await shot(pc,'desktop-book-retry');pass('The real library task card shows the retry rather than losing its pending state');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='重试验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&Boolean(window.studyforgeTaskRetry)");
  await run(phone,"refreshProject()");assert(await run(phone,"mobile.jobs.some(j=>j.retry?.retry_count===5)&&typeof window.studyforgeTaskRetry.summary==='function'"));
  pass('A paired HTTPS phone receives persistent retries and the shared status formatter');
  await until(pc,`api('/api/library/jobs').then(r=>r.jobs.find(j=>j.id==='${book.id}').status==='completed')`);
  const final=await run(pc,`api('/api/library/jobs').then(r=>r.jobs.find(j=>j.id==='${book.id}'))`);assert.equal(final.retry.retry_count,5);
  assert.equal((await run(pc,"api('/__retry_test__/state')")).failures['retry-book'],5);
  await run(phone,`libraryOpen('${data.book_id}')`);await until(phone,"document.querySelector('#bookJobs .task-retry-status')?.textContent.includes('5 次自动重试完成')");
  await run(phone,"document.querySelector('#bookJobs .task-retry-status').scrollIntoView({block:'center'})");await sleep(120);
  await shot(phone,'phone-retry-completed');assert(await run(phone,"$('mobileBookLibrary').scrollWidth<=$('mobileBookLibrary').clientWidth+1"));
  pass('Phone and desktop show the same completed library task after five retries without horizontal overflow');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'retry-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,external_model_requests:0},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'retry-ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'retry-failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
