/* Actual API, files, pause/reuse, desktop and paired HTTPS phone. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-check'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<400;n++){if(await run(w,c))return;await sleep(70);}throw Error('UI wait failed: '+c);}
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'ui-log.txt'),text+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(picture.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const id=data.pc.questionnaire_id;await run(pc,`openLessonFeedback('${id}')`);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  assert(await run(pc,`document.querySelector('[data-feedback-check="${id}"]').textContent.includes('检查 1 题')`));
  pass('Completed followup shows an optional one-question action without starting any model call');
  await run(pc,"$('generationParallel').checked=true;$('generationParallel').dispatchEvent(new Event('change'))");
  assert(await run(pc,"$('generationParallelHint').textContent.includes('核查')"));
  await run(pc,`document.querySelector('[data-feedback-check="${id}"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>Boolean(rows.find(q=>q.id==='${id}')?.understanding_check))`);
  const check=(await run(pc,`api('/api/projects/${data.project_id}/lesson-feedback')`)).find(q=>q.id===id).understanding_check;
  await until(pc,"api('/__library_test__/calls').then(x=>x.calls.length>=1)");
  await run(pc,`api('/api/jobs/${check.job_id}/pause',{method:'POST'})`);
  await until(pc,`api('/api/jobs/${check.job_id}').then(x=>x.status==='paused')`);
  const repeated=await run(pc,`api('/api/lesson-feedback/${id}/check',jsonOptions('POST',{project_id:'${data.project_id}',conversation_id:'${data.conversation_id}'}))`);
  assert.equal(repeated.job_id,check.job_id);assert(repeated.reused);
  assert(await run(pc,'!isChatBusy()'));assert.deepEqual(await run(pc,'[...state.selected]'),[data.phone.source_id]);
  pass('Check pauses after the active model step; repeat click reuses it and keeps current source selection and chat availability');
  await run(pc,`api('/api/jobs/${check.job_id}/resume',{method:'POST'})`);
  await until(pc,`api('/api/jobs/${check.job_id}').then(x=>x.status==='completed')`);
  assert.equal((await run(pc,"api('/__lesson_review__/state')")).peak.math,2);
  let records=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(records.length,4,'Resume must reuse the saved writer response');
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(q=>q.id==='${id}')?.understanding_check?.status==='completed')`);
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await run(pc,`openLessonFeedback('${id}')`);
  assert(await run(pc,`document.querySelector('[data-feedback-check="${id}"]').textContent.includes('查看这道')`));
  await run(pc,`document.querySelector('[data-feedback-check="${id}"]').click()`);
  await until(pc,"document.querySelector('[data-answer]')&&document.body.textContent.includes('UI_CHECK_MATH')");
  assert(!await run(pc,"document.body.textContent.includes('PRIVATE_CHECK_')"));
  const saved=(await run(pc,`api('/api/projects/${data.project_id}/lesson-feedback')`)).find(q=>q.id===id).understanding_check;
  const publicSet=await run(pc,`api('/api/exercises/${saved.exercise_set_id}?reveal=true')`);
  assert.equal(publicSet.questions.length,1);assert(!publicSet.solutions);assert(!JSON.stringify(publicSet).includes('PRIVATE_CHECK_'));
  pass('Reload restores the delivered check and opens the exact worksheet; public API and visible question hide reference answers and private design notes');
  await shot(pc,'desktop-one-question');
  const artifacts=await run(pc,`api('/api/projects/${data.project_id}/artifacts')`),artifact=artifacts.find(a=>a.metadata?.exercise_set_id===saved.exercise_set_id);
  assert(artifact&&artifact.format==='docx');
  const zip=await run(pc,`fetch('/api/artifacts/${artifact.id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(zip.status,200);assert.deepEqual(zip.prefix,[80,75]);
  pass('One-question worksheet is a downloadable real DOCX under its original project and conversation');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='补讲1题验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  const pid=data.phone.questionnaire_id;await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  assert(await run(phone,"!$('lessonFeedbackCheck').hidden&&!$('lessonFeedbackCheck').disabled"));
  await run(phone,"$('lessonFeedbackCheck').click()");
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(q=>q.id==='${pid}')?.understanding_check?.status==='completed')`);
  await run(phone,'studyforgeMobileLessonFeedback.refresh()');await until(phone,"$('lessonFeedbackCheck').textContent.includes('查看这道')");await shot(phone,'phone-check-ready');
  await run(phone,"$('lessonFeedbackCheck').click()");await until(phone,"$('homeworkDialog').open&&$('homeworkTitle').textContent.includes('大样本')");
  assert(await run(phone,"$('homeworkQuestions').textContent.includes('UI_CHECK_CAUSAL')"));
  assert(!await run(phone,"$('homeworkDialog').textContent.includes('PRIVATE_CHECK_')"));
  pass('Paired HTTPS phone creates a separate check for its own followup and opens that exact worksheet');
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  assert(await run(phone,"$('lessonFeedbackCheck').textContent.includes('查看这道')"));
  records=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(records.length,8);
  const auditState=await run(pc,"api('/__lesson_review__/state')");
  assert.deepEqual(auditState.peak,{math:2,causal:1});assert.deepEqual(auditState.active,{math:0,causal:0});
  pass('Desktop internal-parallel checkbox overlaps both audits; phone inherits the saved serial default, with both audits retained and no leaked active requests');
  const memory=await run(pc,"api('/api/profile/memory')");assert(memory.insights.every(x=>x.kind==='self_report'));assert.equal((await run(pc,"api('/api/profile')")).length,0);
  pass('Phone refresh reuses the existing check; reading and question generation do not turn self reports into scored mastery');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:8,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
