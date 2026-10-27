/* Actual Electron and HTTPS phone, with a controlled local preparation wait. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-preparation'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],latencies=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<350;n++){if(await run(w,c))return;await sleep(80);}throw new Error('UI wait failed: '+c);}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if(e.level==='error'&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const pic=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(pic.data,'base64'));}
async function measured(w,label,code){const start=Date.now();const result=await run(w,code);const elapsed=Date.now()-start;latencies.push({label,elapsed_ms:elapsed});assert(elapsed<2000,label+' blocked while local preparation was waiting');return result;}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='原文准备验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}});const d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');pass('Desktop and paired HTTPS phone load the real application');
  const job=await run(pc,"api('/__preparation_test__/launch',{method:'POST'})");
  await until(pc,"api('/__preparation_test__/state').then(s=>s.assembly_entered&&!s.released)");
  const status=await measured(pc,'desktop progress',`api('/api/jobs/${job.job_id}?view=progress')`);assert(['running','queued'].includes(status.status));
  await measured(pc,'desktop scheduling',"api('/api/scheduling')");
  await measured(phone,'phone project refresh','refreshProject({poll:true})');
  assert((await run(pc,"api('/__preparation_test__/state')")).model_calls===0);pass('Progress, scheduler and phone refresh respond while a real original-assembly thread is held; no model request has started');
  await measured(pc,'desktop conversation switch',`selectConversation('${data.second_conversation_id}')`);
  assert.equal(await run(pc,'state.conversation'),data.second_conversation_id);
  await measured(pc,'desktop conversation restore',`selectConversation('${data.conversation_id}')`);
  await measured(phone,'phone project switch',`selectProject('${data.other_project_id}')`);
  assert.equal(await run(phone,'mobile.project.id'),data.other_project_id);
  await measured(phone,'phone project restore',`selectProject('${data.project_id}')`);
  pass('Desktop switches and restores conversations; phone switches and restores projects before preparation finishes');
  await measured(pc,'pause',`api('/api/jobs/${job.job_id}/pause',{method:'POST'})`);
  await run(pc,"api('/__preparation_test__/release',{method:'POST'})");
  await until(pc,`api('/api/jobs/${job.job_id}?view=progress').then(j=>j.status==='paused')`);
  assert((await run(pc,"api('/__preparation_test__/state')")).model_calls===0);pass('Pause is accepted during local preparation and prevents the model from starting');
  await run(pc,`api('/api/jobs/${job.job_id}/resume',{method:'POST'})`);
  await until(pc,`api('/api/jobs/${job.job_id}?view=progress').then(j=>j.status==='completed')`);
  const rows=await run(pc,`api('/api/projects/${data.project_id}/artifacts')`);assert.equal(rows.length,1);assert.equal(rows[0].format,'docx');
  const requests=await run(pc,"api('/__library_test__/calls')");
  assert(requests.calls.some(r=>JSON.stringify(r).includes('原文末尾条件：除数不能为零。')));
  assert(requests.calls.every(r=>!JSON.stringify(r).includes('旧缓存不会代替完整原文件')));pass('Resuming generates one real DOCX; actual native request contains the complete original and excludes the obsolete preview');
  await run(pc,"showView('artifacts');refreshArtifacts()");
  await until(pc,`document.querySelector('[data-artifact="${rows[0].id}"]')`);
  await run(pc,`studyforgeTaskTiming.open('${job.job_id}')`);
  await until(pc,"document.querySelector('.task-timing-body')?.textContent.includes('原文范围、图像索引与分段准备')");
  await shot(pc,'desktop-preparation-timing');pass('Task diagnostics name the new source preparation phase in Chinese');
  await run(phone,'refreshProject()');
  const downloaded=await run(phone,`fetch('/api/artifacts/${rows[0].id}/download').then(async r=>({status:r.status,bytes:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);
  assert.equal(downloaded.status,200);assert.deepEqual(downloaded.bytes,[80,75]);pass('Paired phone downloads the completed Word file');
  await run(phone,"$('openArtifacts').click()");await shot(phone,'phone-completed-document');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,latencies,
    external_model_requests:0,fixture_note:'A deliberately held assembly thread tests responsiveness and pause; these latencies are not generation benchmarks.'},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){try{await run(pc,"api('/__preparation_test__/release',{method:'POST'})");}catch{}fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors,latencies},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
