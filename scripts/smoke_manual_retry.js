const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate,createHash}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-manual-retry'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,code)=>w.webContents.executeJavaScript(code);
function create(width,height,partition){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false,partition}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function until(w,code){for(let i=0;i<850;i++){if(await run(w,code))return;await sleep(70);}throw Error('Wait failed: '+code);}
async function shot(w,name){await sleep(100);w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});w.webContents.debugger.detach();fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
const pass=text=>{checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify(checks,null,2));};
async function generate(pc){await run(pc,"$('generationParallel').checked=false;$('generationParallel').dispatchEvent(new Event('change'));$('reviewMode').value='fast';$('outputFormat').value='docx';$('withExercises').checked=false;$('prompt').value='原要求：讲清所选资料的推导，不布置习题。';$('generate').click()");}
function verify(state,id){const job=state.jobs.find(j=>j.id===id);assert.equal(job.status,'completed');assert(job.artifact.words.includes('DRAFT_PART_1')&&job.artifact.words.includes('DRAFT_PART_2'));
 for(const role of ['draft','review'])assert.equal(state.events.filter(e=>e.job_id===id&&e.role===role&&e.part===1&&e.phase==='start').length,1);
 assert.equal(state.receipts.filter(r=>r.job_id===id).length,1);assert.equal(state.mastery,0);assert.equal(state.learning_events,0);return job;}
async function download(w,artifact,name){const response=await run(w,`fetch('/api/artifacts/${artifact.id}/download').then(async r=>({ok:r.ok,name:r.headers.get('Content-Disposition'),bytes:Array.from(new Uint8Array(await r.arrayBuffer()))}))`);assert(response.ok&&response.name.includes('.docx'));const bytes=Buffer.from(response.bytes);assert.equal(bytes.subarray(0,2).toString(),'PK');assert.equal(createHash('sha256').update(bytes).digest('hex'),artifact.sha256);fs.writeFileSync(path.join(folder,name+'.docx'),bytes);}
app.whenReady().then(async()=>{
 try{
  const pc=create(1440,1000,'manual-pc');await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await generate(pc);
  await until(pc,"api('/__manual_ui__/state').then(s=>s.jobs.some(j=>j.status==='failed'))");
  let state=await run(pc,"api('/__manual_ui__/state')");const first=state.jobs[0].id;assert.equal(state.calls,2);assert.equal(state.failures,1);assert.equal(state.jobs[0].artifact,null);
  const savedBefore=state.saved.find(row=>row.id===first).payload;
  await run(pc,"showView('artifacts')");await until(pc,`document.querySelector('[data-local-job="${first}"] [data-action=retry]')`);await shot(pc,'desktop-failed-retry');
  pass('A real second-chapter failure leaves the first draft and review saved, publishes no incomplete Word file, and exposes the recovery action');
  await run(pc,"api('/__manual_ui__/later',{method:'POST'})");await run(pc,"showView('study');$('clearSources').click();$('prompt').value='后来的草稿不要覆盖原任务';showView('artifacts');window.manualFetchOriginal=window.fetch;window.lastManualPacket=null;window.fetch=(...args)=>{if(String(args[0]).endsWith('/retry'))window.lastManualPacket={url:String(args[0]),options:args[1]};return window.manualFetchOriginal(...args)};void 0");
  await until(pc,`document.querySelector('[data-local-job="${first}"] [data-action=retry]')`);await run(pc,`document.querySelector('[data-local-job="${first}"] [data-action=retry]').click()`);
  await until(pc,`api('/__manual_ui__/state').then(s=>s.jobs.find(j=>j.id==='${first}').status==='completed')`);state=await run(pc,"api('/__manual_ui__/state')");const firstJob=verify(state,first);assert.equal(state.calls,5);assert.deepEqual(state.saved.find(row=>row.id===first).payload,savedBefore);assert.equal(state.jobs.length,1);
  const replay=await run(pc,"api(lastManualPacket.url,lastManualPacket.options)");assert(replay.reused);assert.equal((await run(pc,"api('/__manual_ui__/state')")).calls,5);await run(pc,"window.fetch=window.manualFetchOriginal;void 0");
  await download(pc,firstJob.artifact,'desktop-recovered');await shot(pc,'desktop-recovered');
  pass('Retry from the desktop keeps the same job, original source and instructions despite later chat and cleared selection; cached first chapter is reused and an identical request cannot restart a completed task');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.independent.project_id}'),'${data.independent.conversation_id}')`);await until(pc,`state.conversation==='${data.independent.conversation_id}'&&!conversationUI.restoring`);await generate(pc);
  await until(pc,"api('/__manual_ui__/state').then(s=>s.jobs.length===2&&s.jobs.every(j=>['completed','failed'].includes(j.status)))");state=await run(pc,"api('/__manual_ui__/state')");const second=state.jobs.find(j=>j.id!==first).id;assert.equal(state.calls,7);assert.equal(state.failures,2);
  const phone=create(390,844,'manual-phone'),ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((r,callback)=>{let ok=false;try{ok=r.hostname==='127.0.0.1'&&new X509Certificate(r.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='任务恢复手机验收 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat");await run(phone,"openSheet('tasksDialog')");
  await until(phone,`[...$('taskList').querySelectorAll('[data-task-id="${second}"] button')].some(b=>b.textContent==='重试未完成步骤')`);await shot(phone,'phone-failed-retry');
  await run(phone,`[...$('taskList').querySelectorAll('[data-task-id="${second}"] button')].find(b=>b.textContent==='重试未完成步骤').click()`);
  await until(pc,"api('/__manual_ui__/state').then(s=>s.jobs.length===2&&s.jobs.every(j=>j.status==='completed'))");state=await run(pc,"api('/__manual_ui__/state')");const secondJob=verify(state,second);assert.equal(state.calls,10);assert.equal(state.receipts.length,2);
  await until(phone,`mobile.artifacts.some(row=>row.id==='${secondJob.artifact.id}')`);assert(!(await run(phone,"mobile.artifacts")).some(row=>row.id===firstJob.artifact.id));await download(phone,secondJob.artifact,'phone-recovered');
  pass('The paired HTTPS phone recovers a second project through the actual task button, gets its Word document, and does not mix in the first project output');
  for(const width of [390,320]){phone.setSize(width,844);await sleep(100);assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth+1"));await shot(phone,'phone-task-'+width);}
  await phone.reload();await until(phone,"mobile.authenticated&&mobile.jobs.filter(j=>j.kind==='generate').every(j=>j.status==='completed')");
  const final=await run(pc,"api('/__manual_ui__/state')");assert.equal(final.calls,10);assert.equal(final.jobs.length,2);assert.equal(final.receipts.length,2);assert.equal(final.mastery,0);assert.equal(final.learning_events,0);
  pass('Reload keeps both original jobs and their recovery receipts without more model requests or learning scores; task controls fit 390 and 320 pixels');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'flow.json'),JSON.stringify(final,null,2));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_model_requests:10,controlled_interruptions:2,external_model_requests:0,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const[i,w]of windows.entries())if(!w.isDestroyed())await shot(w,'failed-'+i);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.filter(w=>!w.isDestroyed()).forEach(w=>w.destroy());app.exit(1);}
});
