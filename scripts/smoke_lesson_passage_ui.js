/* Real desktop, paired TLS phone, exact Unicode/CRLF selection and isolation. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-passage'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<300;n++){if(await run(w,c))return;await sleep(60);}throw new Error('UI wait failed: '+c);}
function pass(s){checks.push(s);fs.appendFileSync(path.join(folder,'ui-log.txt'),s+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const pic=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(pic.data,'base64'));}
function cardCode(id){return `document.querySelector('[data-lesson-feedback="${id}"]')`;}
async function choose(w,root,expected){
 await run(w,`(()=>{const d=(${root}).querySelector('[data-passage-open]').closest('details');if(!d.open)d.querySelector('summary').click()})()`);
 assert(await run(w,`(${root}).querySelector('[data-passage-open]').closest('details').open`),'The actual passage selector must be expanded');
 await run(w,`(()=>{const h=${root};h.querySelector('[data-passage-open]').click()})()`);
 await until(w,`!(${root}).querySelector('[data-passage-reader]').hidden`);
 await run(w,`(()=>{const h=${root};h.querySelector('[data-passage-next]').click()})()`);
 await until(w,`(${root}).querySelector('[data-passage-range]').textContent.includes('4001')`);
 await run(w,`(()=>{const h=${root};h.querySelector('[data-passage-next]').click()})()`);
 await until(w,`(${root}).querySelector('[data-passage-text]').value.includes(${JSON.stringify(expected.text.split('😀')[0])})`);
 await run(w,`(()=>{const h=${root};h.querySelector('[data-passage-source]').click();const t=h.querySelector('[data-passage-text]'),quote=${JSON.stringify(expected.text.replace(/\r\n/g,'\n'))},start=t.value.indexOf(quote);if(start<0)throw Error('Exact quote not visible');t.setSelectionRange(start,start+quote.length);h.querySelector('[data-passage-use]').click()})()`);
}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const id=data.old_questionnaire.id,root=cardCode(id);
  await run(pc,`openLessonFeedback('${id}')`);
  await run(pc,`(()=>{const c=${root};c.querySelector('details').open=true;const s=c.querySelector('[data-feedback-focus]');s.value=[...s.options].find(o=>o.textContent.endsWith('长证明')).value;s.dispatchEvent(new Event('change',{bubbles:true}));c.querySelector('[name="other_text"]').value='我只卡在后面的这一句，为什么等号可以？';c.querySelector('[name="other_text"]').dispatchEvent(new Event('input',{bubbles:true}));c.querySelector('input[value="motivation"]').click();})()`);
  await choose(pc,root,data.pc_selection);
  assert.deepEqual(await run(pc,`(${root}).querySelector('[data-feedback-passage]').passageControl.value()`),data.pc_selection);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  pass('Desktop pages beyond 7000 characters and selects the exact original emoji/CRLF passage with zero model requests');
  await run(pc,`(${root}).querySelector('[data-passage-chosen]').scrollIntoView({block:'center',behavior:'instant'})`);await shot(pc,'desktop-selected-passage');
  await run(pc,`selectConversation('${data.phone_conversation_id}')`);await run(pc,`openLessonFeedback('${id}')`);
  assert.deepEqual(await run(pc,`(${root}).querySelector('[data-feedback-passage]').passageControl.value()`),data.pc_selection);
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await run(pc,`openLessonFeedback('${id}')`);
  assert.deepEqual(await run(pc,`(${root}).querySelector('[data-feedback-passage]').passageControl.value()`),data.pc_selection);
  pass('Desktop retains exact selected passage and question through conversation switching and reload');
  await run(pc,`(()=>{const c=${root},s=c.querySelector('[data-feedback-focus]');s.value=[...s.options].find(o=>o.textContent.endsWith('另一节')).value;s.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  assert.equal(await run(pc,`(${root}).querySelector('[data-feedback-passage]').passageControl.value()`),null);
  assert(await run(pc,`(${root}).querySelector('[name="other_text"]').value.includes('只卡在后面')`));
  await run(pc,`(()=>{const c=${root},s=c.querySelector('[data-feedback-focus]');s.value=[...s.options].find(o=>o.textContent.endsWith('长证明')).value;s.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await choose(pc,root,data.pc_selection);pass('Changing section clears its selected passage while retaining the student question');
  await run(pc,`(${root}).querySelector('[data-feedback-action="save"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(r=>r.id==='${id}')?.status==='submitted')`);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  await until(pc,`document.querySelector('[data-feedback-retry="${id}"]')`);await run(pc,`document.querySelector('[data-feedback-retry="${id}"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(r=>r.id==='${id}')?.reply_status==='completed')`);
  let calls=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(calls.length,1);assert(calls[0].messages[0].content.includes('学生选中的历史AI原句，不是学生作答'));assert(calls[0].messages[0].content.includes(data.pc_selection.text));
  pass('Save alone makes no AI call; followup sends the frozen original passage as AI context in the existing single tutor request');
  // A delayed old response must not paint a new section. Exercise the actual
  // shared widget with a controlled promise, without any service/model call.
  const stale=await run(pc,`(async()=>{const h=document.createElement('div');document.body.append(h);let section='old',resolve;const control=studyforgeLessonPassage.create(h,{getId:()=> 'q',getSection:()=>section,api:()=>new Promise(r=>resolve=r),onChange:()=>{}});control.setSection('old');h.querySelector('[data-passage-open]').click();section='new';control.setSection('new');resolve({text:'OLD_RESPONSE',offset:0,end:12,total:12,previous_offset:null,next_offset:null});await Promise.resolve();await Promise.resolve();const safe=h.querySelector('[data-passage-reader]').hidden&&!h.textContent.includes('OLD_RESPONSE');h.remove();return safe})()`);
  assert(stale);pass('Delayed passage responses cannot repopulate a different section');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='原句补讲验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  const pid=data.phone_questionnaire.id,proot="document.getElementById('lessonFeedbackPassage')";
  await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  await run(phone,`(()=>{const s=$('lessonFeedbackFocus');s.closest('details').open=true;s.value=[...s.options].find(o=>o.textContent.endsWith('长证明')).value;s.dispatchEvent(new Event('change'));$('lessonFeedbackChoices').querySelector('input[value="motivation"]').click();$('lessonFeedbackOther').value='我不明白所选原句为什么成立。';$('lessonFeedbackOther').dispatchEvent(new Event('input'));})()`);
  fs.writeFileSync(path.join(folder,'phone-details-before.json'),JSON.stringify(await run(phone,"[...document.querySelectorAll('.questionnaire-focus')].map(n=>({open:n.open,parent:n.parentElement.id,html:n.outerHTML.slice(0,250)}))"),null,2));
  await choose(phone,proot,data.phone_selection);
  assert.equal(await run(phone,`${proot}.querySelector('[data-passage-quote]').dataset.rawText`),data.phone_selection.text);
  assert(await run(phone,`${proot}.closest('details').open`),'Phone passage must remain expanded after selection');
  await run(phone,`${proot}.querySelector('[data-passage-chosen]').scrollIntoView({block:'center',behavior:'instant'})`);await shot(phone,'phone-selected-passage');
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileLessonFeedback.open('${pid}')`);
  assert.equal(await run(phone,`${proot}.querySelector('[data-passage-quote]').dataset.rawText`),data.phone_selection.text);
  pass('Paired HTTPS phone loads long-lesson windows, selects exact Unicode/CRLF text, and restores the selection after reload');
  await run(phone,"$('lessonFeedbackSubmit').click()");
  await until(pc,`api('/api/projects/${data.project_id}/lesson-feedback').then(rows=>rows.find(r=>r.id==='${pid}')?.reply_status==='completed')`);
  calls=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(calls.length,2);assert(calls[1].messages[0].content.includes(data.phone_selection.text));assert(!calls[1].messages[0].content.includes('PC_PASSAGE_TAIL'));
  const memory=await run(pc,"api('/api/profile/memory')");assert(!JSON.stringify(memory.insights).includes('PASSAGE_TAIL'));assert.equal((await run(pc,"api('/api/profile')")).length,0);
  assert.equal((await run(pc,`api('/api/projects/${data.project_id}/exercises')`)).length,0);
  pass('Phone followup uses its own selected lesson; AI quotations are excluded from learner evidence, scores and automatic exercises');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:2,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
