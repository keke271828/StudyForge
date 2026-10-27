const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate,createHash}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-chapter-continuity'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<600;i++){if(await run(w,code))return;await sleep(80);}throw Error('UI wait failed: '+code);}
const pass=text=>checks.push(text);
function watch(w){w.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const value=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(value.data,'base64'));}
function verify(state,kind,parallel=true,jobId=null){const job=state.jobs.find(row=>jobId?row.id===jobId:row.project_id===data[kind].project_id);assert.equal(job.status,'completed');assert.equal(job.parallel,parallel);
 assert.deepEqual(job.plan.map(row=>row.after),kind==='dependent'?[null,0]:[null,null]);assert.equal(job.plan.length,2);
 const events=state.events.filter(row=>row.job_id===job.id),event=(role,part,phase)=>events.find(row=>row.role===role&&row.part===part&&row.phase===phase);
 assert.equal(events.filter(row=>row.phase==='start').length,5);assert(!events.some(row=>row.role==='reading'));
 if(kind==='dependent'||!parallel){assert(event('draft',2,'start').at>=event('review',1,'end').at);assert(event('draft',2,'start').previous);}
 else{assert(events.indexOf(event('draft',2,'start'))<events.indexOf(event('draft',1,'end')));assert(!event('draft',2,'start').previous);}
 assert(job.artifact.words.includes('DRAFT_PART_1')&&job.artifact.words.includes('DRAFT_PART_2')&&job.artifact.words.includes('系统性总结'));
 assert.deepEqual(job.artifact.metadata.chapter_dependencies,job.plan);assert.equal(state.mastery,0);assert.equal(state.learning_events,0);return job;
}
async function generate(pc,parallel=true){await run(pc,`$('generationParallel').checked=${parallel};$('generationParallel').dispatchEvent(new Event('change'));$('reviewMode').value='fast';$('outputFormat').value='docx';$('withExercises').checked=false;$('prompt').value='请继续当前资料的完整讲解，保留前提和证明思路，不布置习题。';$('generate').onclick();true`);}
app.whenReady().then(async()=>{
 const options={sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true};
 const pc=new BrowserWindow({show:false,width:1440,height:980,webPreferences:options});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert(await run(pc,`state.selected.has('${data.dependent.source_ids[0]}')`));await generate(pc);
  await until(pc,"api('/__chapter_test__/state').then(s=>s.jobs.some(j=>['failed','completed'].includes(j.status)))");
  let state=await run(pc,"api('/__chapter_test__/state')");const dependent=verify(state,'dependent');
  await until(pc,"$('messages').textContent.includes('DRAFT_PART_2')&&$('messages').querySelectorAll('.katex').length>3");
  await shot(pc,'desktop-dependent-chapters');pass('Desktop generation waits for the preceding reviewed chapter and supplies its completed draft to the continuation');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.independent.project_id}'),'${data.independent.conversation_id}')`);
  await until(pc,`state.conversation==='${data.independent.conversation_id}'&&!state.projectLoading&&!conversationUI.restoring`);
  await generate(pc);await until(pc,"api('/__chapter_test__/state').then(s=>s.jobs.length===2&&s.jobs.every(j=>['failed','completed'].includes(j.status)))");
  state=await run(pc,"api('/__chapter_test__/state')");const independent=verify(state,'independent');assert.equal(state.calls,10);
  await until(pc,"$('messages').textContent.includes('DRAFT_PART_2')");await shot(pc,'desktop-independent-chapters');
  pass('An independent artifact whose filename mentions continuing a proof actually overlaps the other draft with internal parallelism enabled');
  await generate(pc,false);await until(pc,"api('/__chapter_test__/state').then(s=>s.jobs.length===3&&s.jobs.every(j=>['failed','completed'].includes(j.status)))");
  state=await run(pc,"api('/__chapter_test__/state')");const serial=verify(state,'independent',false,state.jobs.at(-1).id);assert.equal(state.calls,15);
  pass('Turning internal parallelism off in the same UI actually makes the independent second chapter wait for the first review');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:options});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='章节讲解手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&$('messages').textContent.includes('DRAFT_PART_2')");
  assert(await run(phone,"$('messages').querySelectorAll('.katex').length>3"));
  pass('The paired HTTPS phone sees the delivered full lesson and rendered formulas');
  for(const [kind,job]of [['dependent',dependent],['independent',independent],['serial',serial]]){
   const result=await run(phone,`fetch('/api/artifacts/${job.artifact.id}/download').then(async r=>({ok:r.ok,disposition:r.headers.get('Content-Disposition'),bytes:Array.from(new Uint8Array(await r.arrayBuffer()))}))`);
   assert(result.ok&&result.disposition.includes('.docx'));const bytes=Buffer.from(result.bytes);assert.equal(bytes.subarray(0,2).toString(),'PK');
   assert.equal(createHash('sha256').update(bytes).digest('hex'),job.artifact.sha256);fs.writeFileSync(path.join(folder,kind+'.docx'),bytes);
  }pass('All three complete Word files download through the paired phone with exact file hashes and readable filenames');
  for(const width of [390,320]){phone.setSize(width,844);await sleep(120);assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth+1"));await shot(phone,'phone-chapters-'+width);}
  pass('The delivered lesson remains readable at 390 and 320 pixels without page overflow');
  await phone.reload();await until(phone,"mobile.authenticated&&$('messages').textContent.includes('DRAFT_PART_2')");
  state=await run(pc,"api('/__chapter_test__/state')");assert.equal(state.calls,15);verify(state,'dependent');verify(state,'independent');verify(state,'independent',false,serial.id);
  pass('Reload retains both jobs and their complete outputs without repeating model calls or creating learning scores');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'flow.json'),JSON.stringify(state,null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_model_requests:15,external_model_requests:0,console_errors:errors},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
