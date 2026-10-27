const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-review-versions'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],completed=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<450;i++){if(await run(win,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const win=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(win);win.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return win;}
async function shot(win,name){await sleep(160);win.webContents.debugger.attach('1.3');const result=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));win.webContents.debugger.detach();}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,"showView('exercises');$('reviewQueuePanel').open=true;refreshReviews()");
  await until(pc,"$('reviewQueueItems').querySelectorAll('[data-review-select]').length===2");
  await run(pc,"api('/__review_versions_test__/change',{method:'POST'})");await run(pc,'refreshReviews()');
  await until(pc,"$('reviewQueueItems').textContent.includes('原题已更新')&&$('reviewQueueItems').textContent.includes('旧作答版本未核实')");
  assert(await run(pc,"$('reviewQueueItems').textContent.includes('高斯定律')&&!$('reviewQueueItems').textContent.includes('NEW_PARENT')"));
  await run(pc,"$('reviewQueuePanel').scrollIntoView({block:'start'})");await shot(pc,'desktop-saved-versions');
  pass('The native queue retains the saved topic after parent question, solution, rubric and difficulty change, and separately labels the unverified legacy baseline');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='原题版本验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  for(const [index,item] of data.version_cases.entries()){
   await run(pc,"practiceState.selected.clear();$('reviewQueuePanel').open=true;refreshReviews()");
   await until(pc,`Boolean($('reviewQueueItems').querySelector('[data-review-select="${item.item_id}"]:not(:disabled)'))`);
   await run(pc,`$('reviewQueueItems').querySelector('[data-review-select="${item.item_id}"]').click();$('startMixedReview').click()`);
   await until(pc,`api('/__review_versions_test__/state').then(s=>s.sessions.length===${index+1})`);
   let state=await run(pc,"api('/__review_versions_test__/state')");const active=state.sessions[index].exercise_set_id;
   await until(pc,`Boolean($('set-${active}'))`);
   const worksheet=await run(pc,`api('/api/exercises/${active}')`);assert.equal(worksheet.questions[0].question,item.question);assert(!worksheet.solutions);assert.equal(worksheet.difficulty,2);
   assert(worksheet.practice.version_notice.includes(item.verified?'保存':'旧版本未核实'));
   assert.equal(state.calls.length,index*3);
   await run(phone,`studyforgeMobileHomework.openSet('${active}')`);
   await until(phone,`$('homeworkQuestions').textContent.includes(${JSON.stringify(item.question)})`);
   assert(await run(phone,`$('homeworkQuestions').textContent.includes(${JSON.stringify(item.verified?'保存':'旧版本未核实')})&&!$('homeworkQuestions').textContent.includes('NEW_PARENT')`));
   if(!item.verified){await until(phone,"$('toast').hidden");await run(phone,"theme('dark')");phone.setSize(320,844);await shot(phone,'phone-legacy-version');}
   const answer=item.verified?'不能；净和可以由正负抵消，但我对局部量的完整论证还不确定。':'不能；相关可能来自共同原因，但我对排除替代解释的完整论证还不确定。';
   await run(phone,`$('homeworkQuestions').querySelector('[data-homework-answer]').value=${JSON.stringify(answer)};$('homeworkQuestions').querySelector('[data-homework-answer]').dispatchEvent(new Event('input',{bubbles:true}));$('homeworkComplete').checked=true;$('homeworkUsedNotes').value='false';$('homeworkAnswerForm').requestSubmit()`);
   await until(pc,`api('/__review_versions_test__/state').then(s=>s.attempts.length===${index+1}&&s.attempts.every(a=>a.status==='completed')&&s.jobs.every(j=>j.status==='completed'))`);
   state=await run(pc,"api('/__review_versions_test__/state')");const submission=state.submissions.find(s=>s.exercise_set_id===active),grade=JSON.parse(submission.grade_json),timing=grade.practice_context.timing[0];
   assert.equal(submission.score,90);assert.equal(timing.same_question_verified,item.verified);assert(timing.delay_hours>=72);
   const profile=state.profile.find(p=>p.topic===item.topic);assert.equal(profile.review_count,1);assert.equal(profile.delayed_count,item.verified?1:0);
   const attempt=state.attempts.find(a=>a.exercise_set_id===active);
   const download=await run(phone,`fetch('/api/artifacts/${attempt.feedback_artifact_id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
   await run(phone,`studyforgeMobileHomework.openSet('${active}')`);
   if(item.verified)await shot(phone,'phone-completed-known');
   completed.push({exercise_set_id:active,attempt_id:attempt.id,feedback_artifact_id:attempt.feedback_artifact_id,version_verified:item.verified});
   pass(item.verified?'A paired HTTPS phone receives and submits the saved original; both controlled scoring passes receive the saved rubric, and native feedback plus verified same-question timing are retained':
       'Legacy practice still completes and downloads feedback, but its first unknown baseline adds no verified same-question delayed evidence; the completed submission retains that explicit boundary');
  }
  const state=await run(pc,"api('/__review_versions_test__/state')");assert.equal(state.calls.length,6);assert.equal(state.submissions.length,4);assert.equal(state.events.length,2);assert.equal(state.sets.length,4);assert.equal(state.sessions.length,2);assert(state.queue.every(item=>item.active_set_id===null));assert(!state.calls.some(c=>c.changed_parent));
  const grades=state.calls.filter(c=>c.kind==='grade');assert.equal(grades.length,4);assert(grades.slice(0,2).every(c=>c.saved_question&&c.saved_rubric));
  const reused=await run(pc,`api('/api/exercises/${completed[0].exercise_set_id}')`);assert.equal(reused.questions[0].question,data.version_cases[0].question);
  assert(!errors.length,JSON.stringify(errors));pass('Both submissions preserve their own version evidence; reopening adds no model request or assessment, and no updated-parent solution reaches the graders');
  fs.writeFileSync(path.join(folder,'ui-state.json'),JSON.stringify(state,null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:state.calls.length,real_model_requests:0,physical_android:false,completed},null,2));
  windows.forEach(win=>win.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors,completed},null,2));for(const[i,win]of windows.entries())if(win.webContents.getURL())await shot(win,'failed-'+i);windows.forEach(win=>win.destroy());app.exit(1);}
});
