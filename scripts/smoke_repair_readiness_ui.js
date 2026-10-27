const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-readiness'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<400;i++){if(await run(win,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const win=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(win);win.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return win;}
async function shot(win,name){await sleep(160);win.webContents.debugger.attach('1.3');const result=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));win.webContents.debugger.detach();}
const box=`$('set-${data.exercise_id}')`;
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,'openHomework()');await until(pc,"$('homeworkQuestions').querySelectorAll('[data-homework-answer]').length===2");
  await run(pc,"$('homeworkQuestions').querySelectorAll('[data-homework-answer]').forEach((input,i)=>{input.value=i?'从2依次加三个1，得到5。':'我认为内部净电荷为零就能推出里面每个点的电场为零。';input.dispatchEvent(new Event('input',{bubbles:true}))});$('homeworkQuestions').querySelector('[data-recovery-mode]').value='adaptive';$('homeworkComplete').checked=true;submitHomework()");
  await until(pc,"api('/__readiness_test__/state').then(s=>s.waiting&&s.submissions.length===1)");
  await run(pc,"$('closeHomework').click();showView('exercises');refreshExercises()");await run(pc,`openSet('${data.exercise_id}')`);
  assert(await run(pc,`${box}.querySelectorAll('.practice-diagnosis').length===1&&${box}.querySelector('.practice-diagnosis').textContent.includes('第1题')&&!${box}.querySelector('[data-repair-set]')&&Boolean(${box}.querySelector('[data-repair-readiness]'))`));
  assert(await run(pc,`${box}.querySelector('[data-review-question][value="0"]').checked&&!${box}.querySelector('[data-review-question][value="1"]').checked`));
  const denied=await run(pc,`fetch('/api/exercises/${data.exercise_id}/repair-options').then(async r=>({status:r.status,text:await r.text()}))`);
  assert.equal(denied.status,400);assert(denied.text.includes('补讲'));
  await run(pc,`${box}.querySelector('.practice-followup').scrollIntoView({block:'center'})`);await shot(pc,'desktop-wait-for-teaching');
  pass('A 90-point item keeps its tentative diagnosis and review selection visible, while unfinished detailed teaching has no repair action and the API rejects premature targets');
  await run(pc,`(async()=>{await api('/api/projects/${data.project_id}',{method:'DELETE'});await api('/api/projects/${data.project_id}/restore',{method:'POST'});const p=await api('/api/projects');await selectProject(p.find(x=>x.id==='${data.other_project_id}'));await selectProject(p.find(x=>x.id==='${data.project_id}'),{conversationId:'${data.conversation_id}'});})()`);
  let current=await run(pc,"api('/__readiness_test__/state')");assert.equal(current.job.status,'cancelled');assert.equal(current.submissions[0].score,95);assert.equal(current.calls.filter(x=>x==='grade').length,2);
  await run(pc,"openHomework({history:true})");
  assert(await run(pc,"[...$('homeworkHistory').querySelectorAll('[data-homework-retry]')].some(b=>b.textContent==='继续原批改')&&!$('homeworkHistory').querySelector('[data-repair-set]')"));
  await shot(pc,'desktop-cancelled-recovery');await run(pc,"$('closeHomework').click()");
  pass('Moving the isolated project to the recycle bin and restoring it cancels unfinished diagnosis but preserves its original score and submission; desktop history offers explicit recovery without premature repair');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='补讲续接验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openSet('${data.exercise_id}')`);
  assert(await run(phone,"[...$('homeworkResult').querySelectorAll('button')].some(b=>b.textContent==='继续原批改')&&![...$('homeworkResult').querySelectorAll('button')].some(b=>b.textContent.includes('按本次错因'))"));
  await run(phone,"[...$('homeworkResult').querySelectorAll('button')].find(b=>b.textContent==='继续原批改').click()");
  await until(pc,"api('/__readiness_test__/state').then(s=>s.attempt?.status==='awaiting_causes'&&s.job.status==='paused')");
  await run(phone,`studyforgeMobileHomework.openSet('${data.exercise_id}')`);
  assert(await run(phone,"!$('homeworkCauses').hidden&&![...$('homeworkResult').querySelectorAll('button')].some(b=>b.textContent.includes('按本次错因'))"));
  current=await run(pc,"api('/__readiness_test__/state')");assert.equal(current.calls.filter(x=>x==='grade').length,2);assert.equal(current.submissions.length,1);
  pass('The phone explicitly resumes the preserved cancelled work, reuses the two grading reviews, and waits for the original cause questionnaire instead of bypassing it');
  await run(phone,"const card=$('homeworkCauseQuestions').querySelector('[data-cause-index]');card.querySelector('input[value=terminology]').checked=true;card.querySelector('textarea').value='我把净通量误当成了各点的电场，没有区分整体求和与局部量。';$('homeworkCauseQuestions').dispatchEvent(new Event('input',{bubbles:true}));$('homeworkCausesForm').requestSubmit()");
  await until(pc,"api('/__readiness_test__/state').then(s=>s.attempt?.status==='completed'&&s.job.status==='completed')");
  await run(phone,`studyforgeMobileHomework.openSet('${data.exercise_id}')`);
  assert(await run(phone,"[...$('homeworkResult').querySelectorAll('button')].some(b=>b.textContent.includes('按本次错因'))"));
  await run(phone,"[...$('homeworkResult').querySelectorAll('button')].find(b=>b.textContent.includes('按本次错因')).click()");await until(phone,"$('repairPicker')?.open&&$('repairPickerList').querySelectorAll('input').length===1");
  assert(await run(phone,"$('repairPickerList').querySelector('input').value==='0'&&$('repairPickerList').textContent.includes('学生自报')"));
  const spec=await run(phone,`api('/api/exercises/${data.exercise_id}/repair-options')`);assert.equal(spec.targets[0].basis,'student_self_report');
  await run(phone,"theme('dark')");phone.setSize(320,844);await shot(phone,'phone-ready-selected-target');
  current=await run(pc,"api('/__readiness_test__/state')");assert.equal(current.submissions.length,1);assert.equal(current.submissions[0].score,95);assert.equal(current.new_practice_jobs.length,0);assert.equal(current.sets.length,2);
  pass('After the submitted clarification and completed teaching, the phone offers only the actual lost item with its self-report boundary; opening the picker creates no task or extra score');
  await run(pc,"showView('exercises');refreshExercises()");await run(pc,`openSet('${data.legacy_set_id}')`);
  assert(await run(pc,`!$('set-${data.legacy_set_id}').querySelector('[data-repair-set]')&&$('set-${data.legacy_set_id}').textContent.includes('没有已确认的失分项')`));
  pass('A full-credit legacy worksheet does not advertise error-repair practice');
  const download=await run(phone,`fetch('/api/artifacts/${current.attempt.feedback_artifact_id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:current.calls.length,grading_calls:current.calls.filter(x=>x==='grade').length,interrupted_analysis_calls:1,real_model_requests:0,physical_android:false,attempt_id:current.attempt.id,feedback_artifact_id:current.attempt.feedback_artifact_id},null,2));
  windows.forEach(win=>win.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,win]of windows.entries())if(win.webContents.getURL())await shot(win,'failed-'+i);windows.forEach(win=>win.destroy());app.exit(1);}
});
