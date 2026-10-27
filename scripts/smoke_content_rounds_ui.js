const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.resolve(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-content-rounds'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],wait=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c),q=s=>`document.querySelector(${JSON.stringify(s)})`;
async function until(w,c){for(let i=0;i<250;i++){if(await run(w,c))return;await wait(100);}throw Error('UI wait: '+c);}
function win(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
const record=(w,id)=>run(w,`api('/api/lesson-feedback/${id}/dialogue').then(r=>r.questionnaire)`);
app.whenReady().then(async()=>{
 const pc=win(1440,960),root=data.root_feedback_id;
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation');
  const selected=await run(pc,'[...state.selected].sort().join(",")');
  await run(pc,`openLessonFeedback('${root}')`);await until(pc,q(`[data-feedback-content-check="${root}"]`));
  await run(pc,`${q(`[data-feedback-content-check="${root}"]`)}.click()`);
  await until(pc,"document.querySelector('.questionnaire-form [name=difficulty][type=hidden]')");
  const first=await run(pc,"document.querySelector('.questionnaire-form').dataset.questionnaireId");assert.notEqual(first,root);
  const form=`.questionnaire-form[data-questionnaire-id="${first}"]`;
  await run(pc,`const form1=${q(form)},select1=form1.querySelector('[data-feedback-focus]');select1.value=select1.options[1].value;select1.dispatchEvent(new Event('change',{bubbles:true}));form1.querySelector('textarea[name=other_text]').value='PC_ROUND：为什么更大的N也可以？只核对，不出题。';form1.querySelector('textarea[name=other_text]').dispatchEvent(new Event('input',{bubbles:true}))`);
  const section=await run(pc,`${q(form)}.querySelector('[data-feedback-focus]').value`);
  await run(pc,`showView('artifacts');openLessonFeedback('${first}')`);
  await until(pc,`${q(form)}?.querySelector('textarea[name=other_text]')?.value.includes('PC_ROUND')`);
  assert.equal(await run(pc,`${q(form)}.querySelector('[data-feedback-focus]').value`),section);
  assert.equal(await run(pc,'[...state.selected].sort().join(",")'),selected);
  checks.push('Desktop skipped feedback opens an independent content-only draft; text/section recover, current source selection stays unchanged');
  await run(pc,`${q(form)}.requestSubmit(${q(form)}.querySelector('[data-feedback-action=save]'))`);
  await until(pc,`${q(`[data-feedback-retry="${first}"]`)}`);
  let state=await run(pc,"fetch('/__content_rounds_test__/state').then(r=>r.json())");assert.equal(state.requests,2);assert.equal((await record(pc,root)).status,'skipped');
  checks.push('Save-only adds no model call and preserves the skipped original questionnaire');
  await run(pc,`${q(`[data-feedback-retry="${first}"]`)}.click()`);
  await until(pc,`api('/api/lesson-feedback/${first}/dialogue').then(r=>r.questionnaire.reply_status==='completed')`);
  await until(pc,q(`[data-feedback-content-check="${first}"]`));
  assert.equal(await run(pc,q(`[data-feedback-check="${first}"]`)),null);
  await shot(pc,'电脑继续核对讲解');
  await run(pc,`${q(`[data-feedback-content-check="${first}"]`)}.click()`);
  await until(pc,"document.querySelector('.questionnaire-form [name=difficulty][type=hidden]')");
  const second=await run(pc,"document.querySelector('.questionnaire-form').dataset.questionnaireId");assert.notEqual(second,first);
  assert.equal((await record(pc,first)).reply_status,'completed');
  checks.push('Completed desktop check retains its original question/reply and starts another draft without adding a check exercise');
  const phone=win(390,844),ca=new X509Certificate(fs.readFileSync(data.certificate));
  phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='继续核对验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()),d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileLessonFeedback.open('${root}')`);
  await until(phone,"!$('lessonFeedbackContinue').hidden");await run(phone,"$('lessonFeedbackContinue').click()");
  await until(phone,"!$('lessonFeedbackForm').hidden");
  const identity=await run(phone,"$('lessonFeedbackPassage').passageControl?.id||document.querySelector('#lessonFeedbackChoices input').value");assert.equal(identity,'content_accuracy');
  assert.equal(await run(phone,"document.querySelectorAll('#lessonFeedbackChoices input').length"),1);
  assert(await run(phone,"document.querySelector('#lessonFeedbackChoices input').disabled&&document.querySelector('#lessonFeedbackChoices input').checked"));
  await run(phone,"$('lessonFeedbackOther').value='PHONE_ROUND：原文为什么没有排除N=10？请核对。';$('lessonFeedbackOther').dispatchEvent(new Event('input',{bubbles:true}));$('lessonFeedbackSave').click()");
  await until(phone,"!$('lessonFeedbackRetry').hidden");assert.equal((await record(pc,second)).status,'submitted');
  state=await run(pc,"fetch('/__content_rounds_test__/state').then(r=>r.json())");assert.equal(state.requests,3);
  checks.push('Paired phone reuses the desktop pending round; only a content doubt is selectable and save-only does not call AI');
  await run(phone,"$('lessonFeedbackRetry').click()");
  await until(phone,`api('/api/lesson-feedback/${second}/dialogue').then(r=>r.questionnaire.reply_status==='completed')`);
  await run(phone,`studyforgeMobileLessonFeedback.open('${second}')`);
  await until(phone,"!$('lessonFeedbackContinue').hidden&&$('lessonFeedbackCheck').hidden");
  for(const width of [390,320]){phone.setSize(width,844);await wait(100);assert(await run(phone,'document.documentElement.scrollWidth<=innerWidth+1'));await shot(phone,'手机继续核对-'+width);}
  checks.push('Phone background check completes in its original conversation, restores completed content and offers another round at 390/320 px');
  state=await run(pc,"fetch('/__content_rounds_test__/state').then(r=>r.json())");
  assert.deepEqual(state,{requests:4,learning_events:0,learning_insights:0,mastery:0,jobs:1,exercises:0});
  const rows=await run(pc,`api('/api/projects/${data.project_id}/lesson-feedback')`);
  assert.equal(rows.length,3);assert.equal(rows.find(r=>r.id===root).status,'skipped');assert.equal(rows.filter(r=>r.kind==='content_check'&&r.reply_status==='completed').length,2);
  assert(!errors.length,JSON.stringify(errors));checks.push('Two completed rounds preserve original history; zero profile events, scores, exercises or extra generation jobs, exactly four controlled requests');
  fs.writeFileSync(path.join(folder,'content-rounds-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_requests:4,external_model_requests:0,final_state:state},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const [i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'界面检查失败-'+i);fs.writeFileSync(path.join(folder,'content-rounds-ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
