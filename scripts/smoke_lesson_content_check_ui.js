/* Actual desktop, paired HTTPS phone, save/reload and source-scoped followup. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-content-check'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<400;n++){if(await run(w,c))return;await sleep(60);}throw Error('UI wait failed: '+c);}
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'ui-log.txt'),text+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const pic=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(pic.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const id=data.pc.questionnaire_id,root=`document.querySelector('[data-lesson-feedback="${id}"]')`;
  await run(pc,`openLessonFeedback('${id}')`);
  assert.equal(await run(pc,`${root}.querySelectorAll('input[name="difficulty"]').length`),7);
  await run(pc,`(()=>{const c=${root};c.querySelector('details').open=true;const s=c.querySelector('[data-feedback-focus]');s.value=[...s.options].find(o=>o.textContent.endsWith('为什么可以取距离的一半')).value;s.dispatchEvent(new Event('change',{bubbles:true}));c.querySelector('input[value="content_accuracy"]').click();const t=c.querySelector('[name="other_text"]');t.value='PC_CONTENT_CRITIQUE：讲解说必须严格小于，却取了等号，请核对原文。';t.dispatchEvent(new Event('input',{bubbles:true}));c.querySelector('[data-passage-open]').click();})()`);
  await until(pc,`!${root}.querySelector('[data-passage-reader]').hidden`);
  await run(pc,`(()=>{const c=${root},t=c.querySelector('[data-passage-text]'),quote='为了让两个邻域不相交，需要半径严格小于距离的一半，所以直接取等号。',start=t.value.indexOf(quote);if(start<0)throw Error('Fixture quote missing');t.setSelectionRange(start,start+quote.length);c.querySelector('[data-passage-use]').click();})()`);
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await run(pc,`openLessonFeedback('${id}')`);
  assert(await run(pc,`${root}.querySelector('input[value="content_accuracy"]').checked`));
  assert((await run(pc,`${root}.querySelector('[data-feedback-passage]').passageControl.value()`)).text.includes('所以直接取等号'));
  pass('Desktop retains all six learning choices plus content-check choice and restores exact passage and critique draft after reload');
  await run(pc,`${root}.querySelector('[data-feedback-action="save"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(q=>q.id==='${id}')?.status==='submitted')`);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  assert.deepEqual(await run(pc,"api('/__content_check__/state')"),{events:[],insights:[],scores:[],exercises:[]});
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await run(pc,`openLessonFeedback('${id}')`);
  assert(await run(pc,`${root}.textContent.includes('不记成知识薄弱项')&&${root}.textContent.includes('PC_CONTENT_CRITIQUE')`));
  assert(await run(pc,`document.querySelector('[data-feedback-retry="${id}"]').textContent.includes('核对')`));
  pass('Save-only content criticism makes no model request, profile event, score or exercise; submitted choice and critique survive reload');
  await run(pc,`document.querySelector('[data-feedback-retry="${id}"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(q=>q.id==='${id}')?.reply_status==='completed')`);
  await until(pc,"!isChatBusy()");
  const pcCalls=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(pcCalls.length,1);
  const first=JSON.stringify(pcCalls[0]);assert(first.includes('收敛数列若有两个极限')&&first.includes('先处理内容疑点'));
  assert.deepEqual(await run(pc,'[...state.selected]'),[data.phone.source_id]);
  assert.deepEqual(await run(pc,"api('/__content_check__/state')"),{events:[],insights:[],scores:[],exercises:[]});
  await run(pc,`openLessonFeedback('${id}')`);await shot(pc,'desktop-content-check');
  pass('Explicit tutor followup uses the original lesson/source and model, preserves newer selected materials and does not profile the critique twice');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='讲解核对验收 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  const pid=data.phone.questionnaire_id;await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  await until(phone,"$('lessonFeedbackDialog').open&&document.querySelectorAll('dialog[open]').length===1");await sleep(350);
  assert.equal(await run(phone,"$('lessonFeedbackChoices').querySelectorAll('input').length"),7);
  await run(phone,"$('lessonFeedbackChoices').querySelector('input[value=content_accuracy]').click();$('lessonFeedbackChoices').querySelector('input[value=motivation]').click();$('lessonFeedbackOther').value='PHONE_CONTENT_CRITIQUE：原讲解把大样本说成因果证据，请核对。';$('lessonFeedbackOther').dispatchEvent(new Event('input',{bubbles:true}))");
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  assert.equal(await run(phone,"$('lessonFeedbackChoices').querySelectorAll('input:checked').length"),2);
  await until(phone,"$('lessonFeedbackDialog').open&&document.querySelectorAll('dialog[open]').length===1");await sleep(350);
  await run(phone,"$('lessonFeedbackSave').click()");
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(q=>q.id==='${pid}')?.status==='submitted')`);
  let profile=await run(pc,"api('/__content_check__/state')");
  assert.equal(profile.events.length,1);assert.equal(profile.insights.length,1);assert.equal(profile.insights[0].dimension,'reasoning');
  assert(!JSON.stringify(profile).includes('CONTENT_CRITIQUE')&&!JSON.stringify(profile).includes('content_accuracy'));
  assert.deepEqual(profile.scores,[]);assert.deepEqual(profile.exercises,[]);assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,1);
  await run(phone,'studyforgeMobileLessonFeedback.refresh()');await until(phone,"!$('lessonFeedbackRetry').hidden");await shot(phone,'phone-mixed-content-check');
  assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth+1"));
  pass('Paired HTTPS phone restores mixed feedback; only the explicitly selected motivation difficulty enters the profile, excluding criticism text and scores');
  await run(phone,"$('lessonFeedbackRetry').click()");
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(q=>q.id==='${pid}')?.reply_status==='completed')`);
  const records=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(records.length,2);
  assert(JSON.stringify(records[1]).includes('观察调查发现')&&!JSON.stringify(records[1]).includes('PC_CONTENT_CRITIQUE'));
  profile=await run(pc,"api('/__content_check__/state')");assert.equal(profile.events.length,1);assert.equal(profile.insights.length,1);assert.deepEqual(profile.scores,[]);assert.deepEqual(profile.exercises,[]);
  pass('Phone followup completes in its own conversation and source scope without leaking the other critique, creating a score or automatically generating questions');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_calls:2,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
