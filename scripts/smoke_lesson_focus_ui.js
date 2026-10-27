/* Run real desktop and secure phone against isolated, synthetic lessons. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-focus'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<300;n++){if(await run(w,c))return;await sleep(80);}throw new Error('UI wait failed: '+c);}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const pic=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(pic.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const id=data.old_questionnaire.id;
  await run(pc,`openLessonFeedback('${id}')`);
  await sleep(250);
  const geometry=await run(pc,`(()=>{const c=document.querySelector('[data-lesson-feedback="${id}"]'),h=$('messages'),r=c.querySelector('.questionnaire-heading').getBoundingClientRect(),b=h.getBoundingClientRect();return {card:{top:r.top,bottom:r.bottom},host:{top:b.top,bottom:b.bottom,scroll:h.scrollTop,height:h.clientHeight,extent:h.scrollHeight},attached:c.parentNode===h,visible:r.top>=b.top&&r.top<b.bottom,card_style:{display:getComputedStyle(c).display,flex:getComputedStyle(c).flex},cards:[...h.querySelectorAll('.lesson-questionnaire')].map(n=>({id:n.dataset.lessonFeedback,top:n.getBoundingClientRect().top,height:n.getBoundingClientRect().height}))};})()`);
  fs.writeFileSync(path.join(folder,'ui-geometry.json'),JSON.stringify(geometry,null,2));
  assert(geometry.visible,'Opening a questionnaire must actually show its heading in the reading viewport');
  assert(await run(pc,`(()=>{const c=document.querySelector('[data-lesson-feedback="${id}"]');return [...c.querySelector('[data-feedback-focus]').options].some(o=>o.textContent.includes('怎样想到取距离的一半'))&&!c.querySelector('select').textContent.includes('完全不同的章节');})()`));
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  pass('Desktop lists the old lecture headings without a model call or confusing the later lecture');
  await run(pc,`(()=>{const c=document.querySelector('[data-lesson-feedback="${id}"]');c.querySelector('.questionnaire-focus').open=true;const s=c.querySelector('select');s.value=[...s.options].find(o=>o.textContent.includes('怎样想到取距离的一半')).value;s.dispatchEvent(new Event('change',{bubbles:true}));c.querySelector('input[value="motivation"]').click();const t=c.querySelector('textarea');t.value='我还是不明白为什么能取等号，先只记录这个疑问。';t.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await run(pc,`(()=>{const c=document.querySelector('[data-lesson-feedback="${id}"]'),h=$('messages');h.scrollTo({top:h.scrollTop+c.querySelector('.questionnaire-focus').getBoundingClientRect().top-h.getBoundingClientRect().top-8,behavior:'instant'});})()`);
  await sleep(150);await shot(pc,'desktop-focus-draft');
  await run(pc,`selectConversation('${data.phone_conversation_id}');`);
  await run(pc,`openLessonFeedback('${id}')`);
  assert(await run(pc,`(()=>{const c=document.querySelector('[data-lesson-feedback="${id}"]');return c.querySelector('input[value="motivation"]').checked&&c.querySelector('select').selectedOptions[0].textContent.includes('怎样想到')&&c.querySelector('textarea').value.includes('取等号');})()`));
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await run(pc,`openLessonFeedback('${id}')`);
  assert(await run(pc,`(()=>{const c=document.querySelector('[data-lesson-feedback="${id}"]');return c.querySelector('select').value&&c.querySelector('textarea').value.includes('取等号');})()`));
  pass('Desktop preserves selected section and optional comments across conversation switching and page reload');
  await run(pc,`document.querySelector('[data-lesson-feedback="${id}"] [data-feedback-action="save"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(r=>r.id==='${id}')?.status==='submitted')`);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  assert((await run(pc,`api('/api/projects/${data.project_id}/lesson-feedback')`)).find(r=>r.id===id).focus.title.includes('怎样想到'));
  pass('Save feedback alone records its scope without calling the model or grading');
  await until(pc,`document.querySelector('[data-feedback-retry="${id}"]')`);
  await run(pc,`document.querySelector('[data-feedback-retry="${id}"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(r=>r.id==='${id}')?.reply_status==='completed')`);
  let requests=await run(pc,"api('/__library_test__/calls')");assert.equal(requests.calls.length,1);
  assert(requests.calls[0].messages[0].content.includes('FOCUS_OLD_MARKER'));assert(!requests.calls[0].messages[0].content.includes('NEWER_DOCUMENT_MARKER'));
  pass('Actual native followup receives the selected old excerpt in its policy and makes one model request');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='补讲定位验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}});const d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  const pid=data.phone_questionnaire.id;
  await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  await run(phone,`(()=>{document.querySelector('.questionnaire-focus').open=true;const s=$('lessonFeedbackFocus');s.value=[...s.options].find(o=>o.textContent.includes('单点非负')).value;s.dispatchEvent(new Event('change'));const input=$('lessonFeedbackChoices').querySelector('input[value="motivation"]');input.click();$('lessonFeedbackOther').value='我不明白为什么一个点不够。';$('lessonFeedbackOther').dispatchEvent(new Event('input'));})()`);
  await run(phone,"document.querySelector('.questionnaire-focus').scrollIntoView({block:'start',behavior:'instant'})");
  await sleep(150);await shot(phone,'phone-focus-draft');
  await run(phone,'refreshProject({poll:true})');await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  assert(await run(phone,"$('lessonFeedbackFocus').value&&$('lessonFeedbackOther').value.includes('一个点不够')"));
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  assert(await run(phone,"$('lessonFeedbackFocus').value&&$('lessonFeedbackChoices').querySelector('input[value=\"motivation\"]').checked"));
  pass('Paired phone retains its selected location and draft through polling and reload');
  await run(phone,"$('lessonFeedbackSubmit').click()");
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(r=>r.id==='${pid}')?.reply_status==='completed')`);
  requests=await run(pc,"api('/__library_test__/calls')");assert.equal(requests.calls.length,2);
  const last=requests.calls[1].messages[0].content;assert(last.includes('FOCUS_PHONE_MARKER'));assert(!last.includes('FOCUS_OLD_MARKER'));
  pass('Phone submits to its original chat; actual native request contains the phone section and excludes the other chat');
  const memory=await run(pc,"api('/api/profile/memory')"),profile=await run(pc,"api('/api/profile')");assert.equal(profile.length,0);
  assert(memory.insights.every(i=>i.kind==='self_report'&&i.confidence==='自评（未验证）'));
  assert(!JSON.stringify(memory.insights).includes('FOCUS_OLD_MARKER')&&!JSON.stringify(memory.insights).includes('FOCUS_PHONE_MARKER'));
  assert.equal((await run(pc,`api('/api/projects/${data.project_id}/exercises')`)).length,0);
  pass('Learning profile records literal self reports and scope, without copying AI excerpts, creating scores or assigning exercises');
  const zip=await run(phone,`fetch('/api/artifacts/${data.phone_questionnaire.artifact.id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);
  assert.equal(zip.status,200);assert.deepEqual(zip.prefix,[80,75]);pass('Phone still downloads the actual original Word lesson');
  await run(pc,`openLessonFeedback('${id}')`);await sleep(150);await shot(pc,'desktop-focus-completed');
  await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);await shot(phone,'phone-focus-completed');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:2,external_model_requests:0},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
