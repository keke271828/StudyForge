const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-recency'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<400;i++){if(await run(win,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const win=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(win);win.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return win;}
async function shot(win,name){await sleep(160);win.webContents.debugger.attach('1.3');const result=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));win.webContents.debugger.detach();}
const card="document.querySelector('[data-profile-topic=高斯定律]')";
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert.equal(await run(pc,'state.project.id'),data.project_id);
  await run(pc,"showView('profile');refreshProfile()");
  assert(await run(pc,`${card}.querySelectorAll('.profile-recent-assessments li').length===1&&${card}.textContent.includes('帮助条件未完整记录')`));
  let state=await run(pc,"api('/__recency_test__/state')");assert.equal(state.profile[0].score,40);assert.equal(state.calls.length,0);
  pass('Desktop distinguishes the historical 40-point record and unknown assistance conditions before a new submission, without model calls');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='近期画像验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openSet('${data.exercise_id}')`);
  await run(phone,"$('homeworkQuestions').querySelector('[data-homework-answer]').value='不能这样推断；净通量为零可以来自正负抵消。但我还不能独立解释抵消为什么不要求各点为零。';$('homeworkQuestions').dispatchEvent(new Event('input',{bubbles:true}));$('homeworkComplete').checked=true;$('homeworkUsedNotes').value='true';$('homeworkAnswerForm').requestSubmit()");
  await until(pc,"api('/__recency_test__/state').then(s=>s.attempt?.status==='completed'&&s.job.status==='completed')");
  state=await run(pc,"api('/__recency_test__/state')");let score=state.profile.find(x=>x.topic==='高斯定律');
  assert.equal(score.score,55);assert.deepEqual(score.recent_assessments.map(x=>x.score),[90,40]);assert.equal(score.recent_assessments[0].aid_status,'assisted');
  assert.equal(state.submissions.length,1);assert.equal(state.events.length,2);assert.equal(state.calls.length,3);
  await run(pc,'refreshProfile(false)');assert(await run(pc,`${card}.querySelectorAll('.profile-recent-assessments li').length===2&&${card}.querySelector('.profile-combined-score').textContent.includes('55.0')&&${card}.textContent.includes('记录到提示或参考笔记')`));
  await run(pc,`${card}.scrollIntoView({block:'center'})`);await shot(pc,'desktop-recent-records');
  pass('Native phone submission produces one 90-point assessment with notes disclosed; desktop shows 90 then 40 while retaining the 55-point weighted reference and original submission');
  await run(pc,`openProfileInsight(${state.new_insight.id})`);await run(pc,"$('removeProfileInsight').click();$('confirmProfileRemoval').click()");
  await until(pc,'!profileState.saving&&profileState.editor?.deleted');assert(await run(pc,`${card}.querySelectorAll('.profile-recent-assessments li').length===1`));
  assert.equal((await run(pc,"api('/__recency_test__/state')")).submissions[0].score,90);
  await run(pc,"$('restoreProfileInsight').click()");await until(pc,'!profileState.saving&&profileState.editor&&!profileState.editor.deleted');
  assert(await run(pc,`${card}.querySelectorAll('.profile-recent-assessments li').length===2`));await run(pc,"$('profileEvidenceDialog').close()");
  state=await run(pc,"api('/__recency_test__/state')");assert.equal(state.calls.length,3);assert(state.packet.topics[0].history_notice.includes('核对当前卡点'));
  pass('Removing and restoring the new assessment through desktop controls recomputes recent records without changing the actual worksheet score or requesting AI');
  await run(phone,"$('homeworkDialog').close();$('prompt').value='请根据我的学习画像说明高斯定律当前有哪些证据和待核对之处。';$('prompt').dispatchEvent(new Event('input'));$('composer').requestSubmit()");
  await until(pc,"api('/__recency_test__/state').then(s=>s.requests.length===1)");await until(phone,"!mobile.sending?.has(mobile.chat.id)&&!['queued','running'].includes(mobile.runs.get(mobile.chat.id)?.status)&&$('messages').textContent.includes('旧疑问需要结合')");
  state=await run(pc,"api('/__recency_test__/state')");let packet=JSON.stringify(state.requests[0]);
  assert(packet.includes('近期评估')&&packet.includes('90')&&packet.includes('40')&&packet.includes('历史疑问'));
  assert(!packet.includes('RAW_OTHER_CHAT')&&!packet.includes('PRIVATE_OLD_ANSWER'));
  await run(phone,"theme('dark')");phone.setSize(320,844);await shot(phone,'phone-profile-summary');
  pass('A phone tutor request receives recent grades, disclosed help and a recheck notice for the older doubt, with no original foreign chat or answer');
  await run(pc,`(async()=>{await selectProject((await api('/api/projects')).find(x=>x.id==='${data.other_project_id}'),{conversationId:'${data.cross_conversation_id}'});showView('study');$('prompt').value='请结合我的学习画像核对高斯定律当前的学习状态。';$('prompt').dispatchEvent(new Event('input'));$('sendMessage').click();})()`);
  await until(pc,"api('/__recency_test__/state').then(s=>s.requests.length===2)");await until(pc,'!state.busy');
  state=await run(pc,"api('/__recency_test__/state')");packet=JSON.stringify(state.requests[1]);assert(packet.includes('近期评估')&&packet.includes('历史疑问'));
  assert(!packet.includes('RAW_OTHER_CHAT')&&!packet.includes('PRIVATE_OLD_ANSWER'));
  assert.equal(state.submissions.length,1);assert.equal(state.events.length,2);assert.equal(state.calls.length,3);
  const download=await run(phone,`fetch('/api/artifacts/${state.attempt.feedback_artifact_id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  pass('Another project and independent chat receive the shared numeric learning evidence without foreign history; phone downloads the native feedback Word and no extra assessment is recorded');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:state.calls.length+state.requests.length,grading_calls:state.calls.filter(x=>x==='grade').length,analysis_calls:state.calls.filter(x=>x==='analysis').length,tutor_calls:state.requests.length,real_model_requests:0,physical_android:false,attempt_id:state.attempt.id,feedback_artifact_id:state.attempt.feedback_artifact_id},null,2));
  windows.forEach(win=>win.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,win]of windows.entries())if(win.webContents.getURL())await shot(win,'failed-'+i);windows.forEach(win=>win.destroy());app.exit(1);}
});
