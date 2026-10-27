const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-review'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<400;i++){if(await run(win,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const win=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(win);win.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return win;}
async function shot(win,name){await sleep(160);win.webContents.debugger.attach('1.3');const result=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));win.webContents.debugger.detach();}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);let active;
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,"showView('exercises');$('reviewQueuePanel').open=true;refreshReviews()");
  assert(await run(pc,"$('reviewQueueItems').querySelectorAll('[data-review-select]').length===2&&$('reviewQueueCount').textContent.includes('2 项到期')"));
  await run(pc,`$('reviewQueueItems').querySelector('[data-review-select="${data.review_item_ids[0]}"]').click()`);
  await run(pc,`(async()=>{const originalApi=api;let release;const held=new Promise(resolve=>{release=resolve});let intercept=true;api=(url,...args)=>{if(intercept&&String(url).startsWith('/api/reviews?')){intercept=false;return held.then(()=>originalApi(url,...args))}return originalApi(url,...args)};try{const pending=refreshReviews();$('reviewQueueItems').querySelector('[data-review-select="${data.review_item_ids[1]}"]').click();release();await pending;}finally{api=originalApi}})()`);
  assert(await run(pc,"practiceState.selected.size===2&&$('reviewSelectedCount').textContent.includes('2/6')"));
  await run(pc,`api('/api/projects/${data.other_project_id}',{method:'DELETE'})`);await run(pc,'refreshReviews()');
  await until(pc,`$('reviewQueueItems').querySelectorAll('[data-review-select]').length===1&&practiceState.selected.size===1&&practiceState.selected.has('${data.review_item_ids[0]}')&&$('reviewQueueCount').textContent.includes('1 项到期')&&!$('reviewQueueItems').textContent.includes('高斯定律')`);
  const before=await run(pc,"api('/__review_test__/state')");assert.equal(before.queue.length,2);assert.equal(before.sessions.length,0);assert.equal(before.calls.length,0);
  pass('The native queue removes recycled-origin rows, due counts and stale selection, while preserving both saved plans; a delayed refresh keeps a newly selected valid item');
  await run(pc,`api('/api/projects/${data.other_project_id}/restore',{method:'POST'})`);
  await run(pc,`(async()=>{const projects=await api('/api/projects');await selectProject(projects.find(p=>p.id==='${data.review_target}'),{conversationId:'${data.review_chat}'});showView('exercises');$('reviewQueuePanel').open=true;await refreshReviews();$('reviewQueueItems').querySelector('[data-review-select="${data.review_item_ids[1]}"]').click();$('startMixedReview').click();})()`);
  await until(pc,"api('/__review_test__/state').then(s=>s.sessions.length===1)");
  let state=await run(pc,"api('/__review_test__/state')");active=state.sessions[0].exercise_set_id;
  await until(pc,`$('set-${active}')?.querySelectorAll('[data-answer]').length===2`);
  const partial=await run(pc,`fetch('/api/reviews/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:'${data.review_target}',item_ids:['${data.review_item_ids[0]}']})}).then(async r=>({status:r.status,text:await r.text()}))`);
  assert.equal(partial.status,400);assert(partial.text.includes('范围'));
  const original=await run(pc,`api('/api/exercises/${active}')`);assert.equal(original.questions.length,2);assert(!original.solutions);
  state=await run(pc,"api('/__review_test__/state')");assert.equal(state.sets.length,3);assert.equal(state.calls.length,0);
  pass('Restored origins create one explicitly selected two-question review; a one-item repeat request is rejected and the original worksheet stays unanswered with solutions hidden');
  await run(pc,`selectProject({id:'${data.project_id}',name:'书库引用验收'},{conversationId:'${data.conversation_id}'})`);
  await run(pc,`api('/api/projects/${data.review_target}',{method:'DELETE'})`);
  await run(pc,"showView('exercises');$('reviewQueuePanel').open=true;refreshReviews()");
  await until(pc,"!$('reviewQueueItems').querySelector('[data-open-review]')&&$('reviewQueueCount').textContent.includes('0 项到期')&&$('reviewQueueItems').textContent.includes('回收站')");
  await run(pc,`api('/api/projects/${data.review_target}/restore',{method:'POST'})`);await run(pc,'refreshReviews()');
  await until(pc,"$('reviewQueueItems').querySelectorAll('[data-open-review]').length===2");
  await run(pc,"$('reviewQueueItems').querySelector('[data-open-review]').click()");await until(pc,`state.project.id==='${data.review_target}'&&Boolean($('set-${active}'))`);
  const reused=await run(pc,`api('/api/reviews/start',jsonOptions('POST',{project_id:'${data.review_target}',item_ids:${JSON.stringify(data.review_item_ids)}}))`);assert(reused.reused&&reused.exercise_set.id===active);
  await run(pc,"$('reviewQueuePanel').open=true;refreshReviews()");await run(pc,"$('reviewQueuePanel').scrollIntoView({block:'start'})");await shot(pc,'desktop-restored-review');
  pass('Recycling the review destination hides its broken resume links; restoring it reopens the exact original worksheet with no duplicate task, score or model request');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='复习续接验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openSet('${active}')`);
  await run(phone,"$('homeworkQuestions').querySelectorAll('[data-homework-answer]').forEach((input,i)=>{input.value=i?'不能；净和可能由正负抵消，但我对局部量的完整论证还不确定。':'不能；相关可能来自共同原因，但我对排除替代解释的完整论证还不确定。';input.dispatchEvent(new Event('input',{bubbles:true}))});$('homeworkComplete').checked=true;$('homeworkUsedNotes').value='false';$('homeworkAnswerForm').requestSubmit()");
  await until(pc,"api('/__review_test__/state').then(s=>s.attempt?.status==='completed'&&s.job.status==='completed')");
  state=await run(pc,"api('/__review_test__/state')");assert.equal(state.submissions.length,3);assert.equal(state.events.length,2);assert.equal(state.calls.length,3);assert.equal(state.sets.length,3);
  const mixed=state.submissions.find(s=>s.exercise_set_id===active),grade=JSON.parse(mixed.grade_json);assert.equal(mixed.score,90);assert(grade.practice_context.timing.every(t=>t.delay_hours>=72));
  assert(state.queue.every(item=>item.active_set_id===null));assert.deepEqual(new Set(state.queue.map(x=>x.id)),new Set(data.review_item_ids));
  assert(state.profile.every(item=>item.review_count===1&&item.delayed_count===1));
  await run(phone,`studyforgeMobileHomework.openSet('${active}')`);await run(phone,"theme('dark')");phone.setSize(320,844);await shot(phone,'phone-completed-review');
  const download=await run(phone,`fetch('/api/artifacts/${state.attempt.feedback_artifact_id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  pass('A paired HTTPS phone completes the same two-question review and downloads native feedback Word; each measured topic retains its original spacing and no extra assessment is recorded');
  await run(pc,"$('reviewDueOnly').checked=false;refreshReviews()");await until(pc,"$('reviewQueueCount').textContent.includes('0 项到期')&&$('reviewQueueItems').querySelectorAll('[data-review-select]').length===2&&!$('reviewQueueItems').querySelector('[data-open-review]')");
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-state.json'),JSON.stringify(state,null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:state.calls.length,real_model_requests:0,physical_android:false,review_set_id:active,attempt_id:state.attempt.id,feedback_artifact_id:state.attempt.feedback_artifact_id},null,2));
  windows.forEach(win=>win.destroy());app.exit(0);
 }catch(error){const diagnostics=await run(pc,"({selected:[...practiceState.selected],count:$('reviewQueueCount').textContent,rows:[...$('reviewQueueItems').querySelectorAll('[data-review-select]')].map(x=>({id:x.dataset.reviewSelect,checked:x.checked,disabled:x.disabled}))})").catch(()=>null);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors,diagnostics},null,2));for(const[i,win]of windows.entries())if(win.webContents.getURL())await shot(win,'failed-'+i);windows.forEach(win=>win.destroy());app.exit(1);}
});
