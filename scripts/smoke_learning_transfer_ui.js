const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-transfer'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<400;n++){if(await run(w,c))return;await sleep(80);}throw new Error('UI wait failed: '+c);}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const pic=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(pic.data,'base64'));}
async function jobs(w){return run(w,`api('/api/projects/${data.project_id}/jobs')`);}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1460,height:1100,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert.equal(await run(pc,'state.conversation'),data.conversation_id);
  await run(pc,"$('openLearningGoals').click()");await until(pc,`document.querySelector('[data-context-check-goal="${data.goal_id}"]')&&!document.querySelector('[data-context-check-goal="${data.goal_id}"]').disabled`);
  assert.equal((await run(pc,"api('/__transfer_test__/state')")).model_requests,0);pass('Desktop shows voluntary standard and new-context checks; viewing evidence makes no model request');
  await run(pc,`document.querySelector('[data-check-goal="${data.goal_id}"]').click()`);
  await until(pc,"api('/__transfer_test__/state').then(s=>s.standard_waiting)");
  const standard=(await jobs(pc)).find(j=>j.kind==='generate');assert(standard);
  await until(pc,`!document.querySelector('[data-context-check-goal="${data.goal_id}"]').disabled`);
  await run(pc,`document.querySelector('[data-context-check-goal="${data.goal_id}"]').click()`);
  let changed;
  for(let i=0;i<200;i++){const rows=await jobs(pc);changed=rows.find(j=>j.kind==='generate'&&j.id!==standard.id);if(changed?.status==='completed')break;await sleep(100);}
  assert.equal(changed?.status,'completed');assert.equal((await run(pc,"api('/__transfer_test__/state')")).released,false);
  const changedJob=await run(pc,`api('/api/jobs/${changed.id}')`);assert.equal(changedJob.payload.goal_check.kind,'new_context');assert.equal(changedJob.payload.goal_check.baseline.exercise_set_id,data.baseline_set_id);
  pass('New-context check completes while the separate standard task is held; snapshots keep distinct kinds and the correct reference');
  await run(pc,`api('/api/jobs/${standard.id}/pause',{method:'POST'})`);await run(pc,"api('/__transfer_test__/release',{method:'POST'})");
  await until(pc,`api('/api/jobs/${standard.id}?view=progress').then(j=>j.status==='paused')`);
  assert.equal((await run(pc,"api('/__transfer_test__/state')")).model_requests,5);
  await run(pc,`api('/api/jobs/${standard.id}/resume',{method:'POST'})`);
  await until(pc,`api('/api/jobs/${standard.id}?view=progress').then(j=>j.status==='completed')`);
  assert.equal((await run(pc,"api('/__transfer_test__/state')")).model_requests,8);pass('Pausing the in-flight standard task prevents its remaining audits; resuming reuses the first response without touching the completed new-context check');
  const artifacts=await run(pc,`api('/api/projects/${data.project_id}/artifacts')`);assert.equal(artifacts.length,2);
  const publicSets=new Map();
  for(const item of artifacts){const set=await run(pc,`api('/api/exercises/${item.metadata.exercise_set_id}')`);publicSets.set(item.id,set);assert.equal(set.questions.length,3);assert(!JSON.stringify(set).includes('ANSWER_PRIVATE'));assert(!JSON.stringify(set).includes('CHANGE_PRIVATE'));assert(!set.solutions);}
  const contextArtifact=artifacts.find(a=>publicSets.get(a.id).learning_check.kind==='new_context'),standardArtifact=artifacts.find(a=>publicSets.get(a.id).learning_check.kind==='standard');assert(contextArtifact&&standardArtifact);
  pass('Both actual DOCX worksheets remain separate; public sets hide answers and private explanations of context changes');
  const calls=(await run(pc,"api('/__library_test__/calls')")).calls;
  assert(calls.every(c=>!JSON.stringify(c).includes('BASE_STUDENT_PRIVATE')&&!JSON.stringify(c).includes('FOREIGN_DIALOGUE_PRIVATE')));
  const designs=calls.filter(c=>c.messages[0].content.includes('严谨的习题设计者'));assert.equal(designs.length,2);
  assert(designs[1].messages.at(-1).content.includes('难度级别：2/5'));assert.equal(designs[1].messages.at(-1).content.split('"questions_sha256"').length-1,1);
  pass('Native requests retain reference difficulty and original source; the reference appears once and private student/other-chat content stays out');
  await run(pc,"showView('goals');refreshLearningGoals()");await shot(pc,'desktop-voluntary-checks');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='新情境检查验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  await run(phone,"$('openOptions').click();$('mobileGoalCheck').open=true");await until(phone,`$('mobileGoalCheckSelect').value==='${data.goal_id}'&&!$('mobileGoalCheckTransfer').disabled`);
  assert.equal((await run(pc,"api('/__transfer_test__/state')")).model_requests,8);await shot(phone,'phone-voluntary-checks');pass('Paired phone loads goal selection on demand, with no model call and an available new-context entry');
  await run(phone,"$('mobileGoalCheckTransfer').click()");let phoneJob;
  for(let i=0;i<200;i++){const rows=await jobs(pc);phoneJob=rows.find(j=>j.kind==='generate'&&j.id!==standard.id&&j.id!==changed.id);if(phoneJob?.status==='completed')break;await sleep(100);}
  assert.equal(phoneJob?.status,'completed');const saved=await run(pc,`api('/api/jobs/${phoneJob.id}')`);assert.equal(saved.payload.goal_check.kind,'new_context');assert.equal(saved.payload.goal_check.baseline.exercise_set_id,data.baseline_set_id);
  const doc=(await run(pc,`api('/api/projects/${data.project_id}/artifacts')`)).find(a=>!publicSets.has(a.id));assert(doc);
  const phoneSet=await run(pc,`api('/api/exercises/${doc.metadata.exercise_set_id}')`);assert.equal(phoneSet.learning_check.kind,'new_context');assert.equal(phoneSet.learning_check.baseline_set_id,data.baseline_set_id);
  const download=await run(phone,`fetch('/api/artifacts/${doc.id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  assert.equal((await run(pc,"api('/__transfer_test__/state')")).model_requests,12);pass('Phone launches a real persistent task using its selected model/settings and downloads its completed Word worksheet');
  await run(phone,`selectChat('${data.second_conversation_id}')`);assert(await run(phone,"!$('mobileGoalCheck').open&&$('mobileGoalCheckSelect').options.length===0"));pass('Switching phone conversations clears stale planning controls');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:12,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){try{await run(pc,"api('/__transfer_test__/release',{method:'POST'})");}catch{}fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
