const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-recovery'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<400;i++){if(await run(win,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const win=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(win);win.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return win;}
async function shot(win,name){await sleep(150);win.webContents.debugger.attach('1.3');const result=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));win.webContents.debugger.detach();}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844),ids=data.exercise_ids;
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,'openHomework()');await until(pc,"$('homeworkSet').options.length===3");
  await run(pc,`$('homeworkSet').value='${ids.adaptive}';$('homeworkSet').dispatchEvent(new Event('change'))`);
  assert(await run(pc,"$('homeworkQuestions').querySelector('[data-recovery-mode]').value==='strict'"));
  await run(pc,"$('homeworkQuestions').querySelector('[data-recovery-mode]').value='adaptive';$('homeworkQuestions').querySelector('[data-recovery-mode]').dispatchEvent(new Event('change',{bubbles:true}));$('homeworkQuestions').querySelector('[data-homework-answer]').value='2+3=4，我从2开始加了三次。';$('homeworkQuestions').dispatchEvent(new Event('input'));$('closeHomework').click();openHomework()");
  await run(pc,`$('homeworkSet').value='${ids.adaptive}';$('homeworkSet').dispatchEvent(new Event('change'))`);
  await until(pc,"$('homeworkQuestions').querySelector('[data-recovery-mode]')?.value==='adaptive'");
  pass('Desktop keeps the worksheet default unless explicitly changed, then restores the selected mode with the answer draft');
  await run(pc,`$('homeworkSet').value='${ids.strict}';$('homeworkSet').dispatchEvent(new Event('change'));$('homeworkQuestions').querySelector('[data-homework-answer]').value='另一个题单的草稿';$('homeworkQuestions').querySelector('[data-recovery-mode]').value='strict';$('homeworkQuestions').dispatchEvent(new Event('input'));$('homeworkSet').value='${ids.adaptive}';$('homeworkSet').dispatchEvent(new Event('change'))`);
  assert(await run(pc,"$('homeworkQuestions').querySelector('[data-homework-answer]').value==='2+3=4，我从2开始加了三次。'&&$('homeworkQuestions').querySelector('[data-recovery-mode]').value==='adaptive'"));
  await run(pc,`$('homeworkSet').value='${ids.strict}';$('homeworkSet').dispatchEvent(new Event('change'))`);
  assert(await run(pc,"$('homeworkQuestions').querySelector('[data-homework-answer]').value==='另一个题单的草稿'&&$('homeworkQuestions').querySelector('[data-recovery-mode]').value==='strict'"));
  await run(pc,`$('homeworkSet').value='${ids.adaptive}';$('homeworkSet').dispatchEvent(new Event('change'))`);
  pass('Switching worksheet selections preserves each rendered worksheet draft and mode without assigning old inputs to the newly selected id');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='低分流程验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openSet('${ids.adaptive}')`);
  assert(await run(phone,"$('homeworkRecoveryMode').value==='strict'"));
  await run(phone,"$('homeworkAttemptOptions').open=true;$('homeworkRecoveryMode').value='adaptive';$('homeworkRecoveryMode').dispatchEvent(new Event('change'));$('homeworkUsedNotes').value='false';$('homeworkUsedNotes').dispatchEvent(new Event('change'));$('homeworkQuestions').querySelector('[data-homework-answer]').value='手机的未提交草稿';$('homeworkQuestions').querySelector('[data-homework-answer]').dispatchEvent(new Event('input'))");
  await run(phone,"window.dispatchEvent(new Event('pagehide'))");
  const reloaded=new Promise(resolve=>phone.webContents.once('did-finish-load',resolve));phone.reload();await reloaded;
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openSet('${ids.adaptive}')`);
  assert(await run(phone,"$('homeworkRecoveryMode').value==='adaptive'&&$('homeworkUsedNotes').value==='false'&&$('homeworkQuestions').querySelector('[data-homework-answer]').value==='手机的未提交草稿'"));
  assert.equal((await run(pc,"api('/__recovery_test__/state')")).calls,0);
  pass('Paired phone has the same default and saves an explicit mode, notes self-report and answer across reload without any model request');
  await run(pc,"$('homeworkComplete').checked=true;submitHomework()");
  await until(pc,"api('/__recovery_test__/state').then(s=>s.waiting)");
  await run(phone,`studyforgeMobileHomework.openSet('${ids.adaptive}')`);
  assert(await run(phone,"$('homeworkFeynman').hidden&&$('homeworkResult').textContent.includes('自主选择修复')"));
  assert(await run(pc,"$('homeworkResult').textContent.includes('自主选择修复')"));
  pass('Both result views report the accepted policy; while diagnosis is unfinished the phone does not offer a competing Feynman task');
  await run(pc,"api('/__recovery_test__/release',{method:'POST'})");
  await until(pc,`api('/__recovery_test__/state').then(s=>s.attempts.some(a=>a.exercise_set_id==='${ids.adaptive}'&&a.status==='completed'))`);
  await run(phone,`studyforgeMobileHomework.openSet('${ids.adaptive}')`);
  assert(await run(phone,"!$('homeworkFeynman').hidden&&!$('homeworkFeynmanPanel').open&&$('homeworkFeynmanHeading').textContent.startsWith('可选')&&$('homeworkResult').textContent.includes('同难度再练')"));
  assert(!(await run(pc,"api('/__recovery_test__/state')")).feynman_jobs.length);
  await run(phone,"$('homeworkFeynman').scrollIntoView({block:'start'})");await shot(phone,'phone-adaptive-optional');
  pass('At 79 the adaptive route offers same-difficulty repair, leaves self-explanation optional and collapsed, and creates no automatic follow-up task');
  await run(phone,`studyforgeMobileHomework.openSet('${ids.strict}')`);
  assert(await run(phone,"$('homeworkRecoveryMode').value==='adaptive'"));
  await run(phone,"$('homeworkRecoveryMode').value='strict';$('homeworkRecoveryMode').dispatchEvent(new Event('change'));$('homeworkUsedNotes').value='false';$('homeworkQuestions').querySelector('[data-homework-answer]').value='2+3=4，我从2开始加了三次。';$('homeworkQuestions').querySelector('[data-homework-answer]').dispatchEvent(new Event('input'));$('homeworkComplete').checked=true;$('homeworkAnswerForm').requestSubmit()");
  await until(pc,`api('/__recovery_test__/state').then(s=>s.attempts.some(a=>a.exercise_set_id==='${ids.strict}'&&a.status==='completed'))`);
  await run(phone,`studyforgeMobileHomework.openSet('${ids.strict}')`);
  assert(await run(phone,"!$('homeworkFeynman').hidden&&$('homeworkFeynmanPanel').open&&$('homeworkFeynmanToggle').hidden&&$('homeworkResult').textContent.includes('原有费曼')&&!$('homeworkResult').textContent.includes('同难度再练')"));
  await run(phone,"theme('dark')");phone.setSize(320,844);await run(phone,"$('homeworkFeynman').scrollIntoView({block:'start'})");await shot(phone,'phone-strict-required-320-dark');
  pass('The phone-selected strict route at the same 79 shows the required explanation form and withholds the direct repair action');
  const result=await run(pc,"api('/__recovery_test__/state')");
  assert.equal(result.submissions.length,2);assert(result.submissions.every(s=>s.score===79));assert.equal(result.sets.length,3);assert.equal(result.feynman_jobs.length,0);
  assert.equal(result.sets.find(s=>s.id===ids.adaptive).status,'repair_required');assert.equal(result.sets.find(s=>s.id===ids.strict).status,'feynman_required');
  for(const mode of ['adaptive','strict']){const a=result.attempts.find(a=>a.exercise_set_id===ids[mode]);assert.equal(a.options.recovery_mode,mode);assert.equal(a.grade.recovery_mode,mode);}
  pass('Stored choices and actual grading branches match across frontends, scores stay equal and neither route creates another worksheet automatically');
  await run(phone,`studyforgeMobileHomework.openSet('${ids.coding}')`);assert(await run(phone,"$('homeworkAttemptOptions').hidden"));
  pass('Coding homework does not expose ordinary-exercise recovery options');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:result.calls,real_model_requests:0,physical_android:false,exercise_ids:ids},null,2));
  windows.forEach(win=>win.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,win]of windows.entries())if(win.webContents.getURL())await shot(win,'failed-'+i);windows.forEach(win=>win.destroy());app.exit(1);}
});
