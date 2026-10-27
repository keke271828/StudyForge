const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-regrade'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<400;i++){if(await run(win,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const win=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(win);win.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return win;}
async function shot(win,name){await sleep(180);win.webContents.debugger.attach('1.3');const result=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));win.webContents.debugger.detach();}
const readerReady="$('homeworkReader')?.open&&$('homeworkReaderContent').textContent.includes('作答条件')";
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844),items=data.regrade_items;
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  let initial=await run(pc,"api('/__regrade_test__/state')");assert.equal(initial.calls,0);assert.equal(initial.events.length,0);assert.equal(initial.profile.length,0);
  await run(pc,'openHomework({history:true})');
  await until(pc,`Boolean($('homeworkHistory').querySelector('[data-homework-retry="${items.supported.attempt_id}"]'))`);
  await run(pc,`$('homeworkHistory').querySelector('[data-homework-retry="${items.supported.attempt_id}"]').click()`);
  await until(pc,`api('/__regrade_test__/state').then(s=>s.attempts.some(a=>a.id==='${items.supported.attempt_id}'&&a.status==='completed'))`);
  await until(pc,"$('homeworkHistory').textContent.includes('评分复核 · 沿用原作答')");
  let value=await run(pc,"api('/__regrade_test__/state')"),support=value.submissions.find(s=>s.exercise_set_id===items.supported.set_id);
  assert.equal(support.id,items.supported.submission_id);assert.equal(support.grade.practice_context.used_notes,true);assert.equal(support.grade.recovery_mode,'adaptive');
  assert.equal(value.sets.find(s=>s.id===items.supported.set_id).status,'passed_with_support');assert.equal(value.calls,2);assert.equal(value.events.length,1);
  pass('Desktop rechecks the original submission through its history action, preserves the original notes self-report and adaptive policy, and labels the result as a recheck');
  await run(pc,`$('homeworkHistory').querySelector('[data-homework-read="${items.supported.attempt_id}"]').click()`);await until(pc,readerReady);
  assert(await run(pc,"$('homeworkReaderContent').textContent.includes('本次是对原作答的评分复核')&&$('homeworkReaderContent').textContent.includes('学生自报参考过笔记')"));
  await shot(pc,'desktop-rechecked-conditions');
  pass('The actual delivered per-question reader says this is a score recheck and keeps the original statement that notes were used');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='复核条件验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openAttempt('${items.partial.attempt_id}')`);
  await run(phone,"[...$('homeworkResult').querySelectorAll('button')].find(button=>button.textContent==='复核原评分').click()");
  await until(pc,`api('/__regrade_test__/state').then(s=>s.attempts.some(a=>a.id==='${items.partial.attempt_id}'&&a.status==='completed'))`);
  await run(phone,`studyforgeMobileHomework.openAttempt('${items.partial.attempt_id}')`);
  assert(await run(phone,"$('homeworkResult').textContent.includes('复核原作答的评分')"));
  pass('The paired HTTPS phone can recheck an older partial-condition record and shows that it remains the same original attempt');
  value=await run(pc,"api('/__regrade_test__/state')");const partial=value.submissions.find(s=>s.exercise_set_id===items.partial.set_id);
  assert.equal(partial.id,items.partial.submission_id);assert.equal(partial.grade.practice_context.recording_status,'partial');assert.equal(partial.grade.practice_context.used_notes,false);
  assert.equal(value.events.length,2);assert.equal(value.submissions.length,2);assert.equal(value.calls,4);
  for(const name of ['supported','partial']){const profile=value.profile.find(p=>p.topic===items[name].topic);assert.equal(profile.quiz_score,100);assert.equal(profile.unaided_quiz_score,null);assert.equal(profile.assisted_count,name==='supported'?1:0);}
  pass('Both scores become 100 exactly once; the known assisted result and the incomplete historical result are both excluded from unassisted-score evidence');
  await run(phone,"$('homeworkResult').querySelector('[data-homework-read]').click()");await until(phone,readerReady);
  assert(await run(phone,"$('homeworkReaderContent').textContent.includes('仅部分保存')&&!$('homeworkReaderContent').textContent.includes('本软件没有记录本题的提示请求')"));
  await run(phone,"theme('dark')");phone.setSize(320,844);await shot(phone,'phone-partial-conditions-320-dark');
  for(const name of ['supported','partial']){const attempt=value.attempts.find(a=>a.id===items[name].attempt_id);const file=await run(phone,`fetch('/api/artifacts/${attempt.feedback_artifact_id}/download').then(async response=>({status:response.status,prefix:[...new Uint8Array(await response.arrayBuffer())].slice(0,2)}))`);assert.equal(file.status,200);assert.deepEqual(file.prefix,[80,75]);}
  assert.equal((await run(pc,"api('/__regrade_test__/state')")).calls,4);
  pass('The 320px dark phone reader states which original conditions are missing, and both real feedback DOCX files download without another model request');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:4,real_model_requests:0,physical_android:false,items},null,2));
  windows.forEach(win=>win.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,win]of windows.entries())if(win.webContents.getURL())await shot(win,'failed-'+i);windows.forEach(win=>win.destroy());app.exit(1);}
});
