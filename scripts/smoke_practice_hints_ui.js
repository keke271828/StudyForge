const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-hints'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(window,code)=>window.webContents.executeJavaScript(code);
async function until(window,code){for(let i=0;i<400;i++){if(await run(window,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const window=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(window);window.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return window;}
async function shot(window,name){await sleep(200);if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const image=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(image.data,'base64'));window.webContents.debugger.detach();}
const panel="document.querySelector('[data-practice-hint=\"0\"]')";
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,'openHomework()');await until(pc,"$('homeworkQuestions').querySelectorAll('[data-practice-hint]').length===2");
  await run(pc,`${panel}.open=true;${panel}.querySelector('select').value='motivation';${panel}.querySelector('select').dispatchEvent(new Event('change'))`);
  let before=await run(pc,"api('/__hint_test__/snapshot')");assert.equal(before.hints.length,0);assert.equal(before.teacher_calls,0);
  pass('Workbench submission shows per-question scaffolds; opening and changing direction makes no hint record or model request');
  await run(pc,"$('homeworkQuestions').querySelector('[data-homework-answer=\"0\"]').value='我的未提交草稿';"+panel+".querySelector('.practice-scaffold-actions>button').click()");
  await until(pc,panel+".querySelector('.practice-scaffold-text').textContent.includes('障碍')");
  await run(pc,panel+".querySelector('.practice-scaffold-actions>button').click()");
  await until(pc,panel+".querySelector('.practice-scaffold-status').textContent.includes('第 2 层')");
  await run(pc,panel+".querySelector('.practice-scaffold-previous button').click()");
  await until(pc,panel+".querySelector('.practice-scaffold-text').textContent.includes('障碍')");
  assert(await run(pc,"$('homeworkQuestions').querySelector('[data-homework-answer=\"0\"]').value==='我的未提交草稿'"));
  before=await run(pc,"api('/__hint_test__/snapshot')");assert.equal(before.hints.length,2);assert.equal(before.submissions.length,0);assert.equal(before.mastery.length,0);assert.equal(before.teacher_calls,0);
  assert(!await run(pc,"$('homeworkQuestions').textContent.includes('PRIVATE_REFERENCE')"));
  pass('Two levels can be revealed and the first revisited without overwriting the answer draft, releasing solutions, scoring, or calling a model');await shot(pc,'desktop-hint');
  await run(pc,"$('closeHomework').click();openHomework()");await until(pc,"$('homeworkQuestions').querySelectorAll('[data-practice-hint]').length===2");
  await run(pc,panel+'.open=true');assert(await run(pc,panel+".querySelector('.practice-scaffold-actions>button').textContent.includes('第 3 层')"));
  pass('Closing and reopening the workbench restores the saved highest level and retains the answer draft');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='提示验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openSet('${data.exercise_id}')`);
  await until(phone,panel);await run(phone,panel+'.open=true');
  assert(await run(phone,panel+".querySelector('.practice-scaffold-actions>button').textContent.includes('第 3 层')"));
  await run(phone,panel+".querySelector('.practice-scaffold-actions>button').click()");
  await until(phone,panel+".querySelector('.practice-scaffold-status').textContent.includes('第 3 层')");
  assert.equal((await run(pc,"api('/__hint_test__/snapshot')")).hints.length,3);
  pass('Paired HTTPS phone sees the desktop-used levels and can explicitly request the next level through the same server record');
  await run(phone,"theme('dark')");phone.setSize(320,844);await sleep(200);
  assert(await run(phone,panel+'.scrollWidth<='+panel+'.clientWidth+1'));
  await run(phone,panel+".scrollIntoView({block:'start'})");await shot(phone,'phone-hint-320-dark');
  pass('The 320px dark phone sheet keeps the hint controls within its width');
  await run(phone,"$('homeworkQuestions').querySelectorAll('[data-homework-answer]').forEach((input,i)=>{input.value=i?'从2依次加三个1得到5。':'净通量是整体有符号求和，各点电场是局部矢量。';input.dispatchEvent(new Event('input'))});$('homeworkComplete').checked=true;$('homeworkUsedNotes').value='false';$('homeworkAnswerForm').requestSubmit()");
  await until(pc,"api('/__hint_test__/snapshot').then(result=>result.attempt?.solution_artifact_id&&result.teacher_calls===1)");
  const denied=await run(phone,`fetch('/api/exercises/${data.exercise_id}/hint',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question_index:0,kind:'terminology',level:1})}).then(async response=>({status:response.status,text:await response.text()}))`);
  assert.equal(denied.status,400);assert(denied.text.includes('完整提交'));
  assert.equal((await run(pc,"api('/__hint_test__/snapshot')")).hints.length,3);
  pass('After phone submission, solutions are released while grading is held, and further hint requests are rejected without changing the attempt record');
  await run(pc,"api('/__hint_test__/release',{method:'POST'})");
  await until(pc,"api('/__hint_test__/snapshot').then(result=>result.attempt?.status==='completed')");
  const finished=await run(pc,"api('/__hint_test__/snapshot')"),grade=JSON.parse(finished.submissions[0].grade_json);
  assert.deepEqual(grade.practice_context.hint_levels,{'0':3});assert.equal(grade.scores[0],100);
  const download=await run(phone,`fetch('/api/artifacts/${finished.attempt.feedback_artifact_id}/download').then(async response=>({status:response.status,prefix:[...new Uint8Array(await response.arrayBuffer())].slice(0,2)}))`);
  assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  pass('Completed grading keeps the pre-submission maximum hint level and original score; the paired phone downloads the actual feedback DOCX');
  await run(phone,`studyforgeMobileHomework.openSet('${data.exercise_id}')`);
  await until(phone,"$('homeworkDetail').textContent.includes('按题提示验收')&&!$('homeworkQuestions').querySelector('[data-practice-hint]')");
  pass('The completed phone worksheet does not offer pre-submission hint controls');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_grading_calls:finished.teacher_calls,real_model_requests:0,exercise_id:data.exercise_id,feedback_artifact_id:finished.attempt.feedback_artifact_id,physical_android:false},null,2));
  windows.forEach(window=>window.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,window]of windows.entries())if(window.webContents.getURL())await shot(window,'failed-'+i);windows.forEach(window=>window.destroy());app.exit(1);}
});
