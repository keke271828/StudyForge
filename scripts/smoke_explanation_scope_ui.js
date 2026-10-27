const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-review-scope'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<350;i++){if(await run(w,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function create(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
async function shot(w,name){await sleep(450);w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));w.webContents.debugger.detach();}
const scope=user=>JSON.parse(user.split('本次讲解交付约束（由本次生成任务提供，不属于原资料）：\n')[1].split('\n本次要求界定')[0]);
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert.equal(await run(pc,'state.conversation'),data.conversation_id);
  await run(pc,"$('reviewMode').value='fast';$('summaryLevel').value='1';$('outputFormat').value='docx';$('generationContent').value='explanation';$('withExercises').checked=false;$('prompt').value='DESKTOP_SCOPE：只讲第一节统一门槛，不重讲定义和第二节，不出题。';$('generate').click()");
  await until(pc,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.some(j=>j.kind==='generate'&&j.status==='completed'))`);
  let calls=(await run(pc,"api('/__library_test__/calls')")).calls;
  const audits=calls.filter(c=>c.response_format?.type==='json_object');assert.equal(audits.length,1);
  const audit=audits[0],contract=scope(audit.messages.at(-1).content);assert(contract.student_requirements.includes('DESKTOP_SCOPE'));assert(contract.detail_guidance.includes('概括性最强'));
  assert(audit.messages.some(m=>m.content.includes('EARLIER_SCOPE')));assert(audit.messages.at(-1).content.includes(data.original));assert(!JSON.stringify(audit).includes('PREVIEW_IS_NOT_THE_ORIGINAL'));
  pass('Desktop generate controls send current draft, inherited learner question, full original and detail level to the native audit, without preview substitution');
  let outputs=await run(pc,"api('/__scope_test__/outputs')");assert.equal(outputs.documents.length,1);let meta=JSON.parse(outputs.documents[0].metadata_json);assert.equal(meta.reviews.length,1);assert.equal(meta.reviews[0].teaching_scope.summary_level,1);
  await run(pc,"showView('artifacts');$('showJobHistory').checked=true;refreshArtifacts()");await until(pc,"document.querySelector('[data-task-timing]')");await shot(pc,'desktop-scoped-document');pass('Completed desktop Word lesson retains its task-scope audit receipt and is shown under its project');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='讲解范围验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');assert.equal(await run(phone,'mobile.chat.id'),data.conversation_id);
  await run(phone,"$('generateFromOptions').click();$('reviewMode').value='balanced';$('summaryLevel').value='2';$('outputFormat').value='docx';$('withExercises').checked=false;$('generationInstructions').value='PHONE_SCOPE：这次只改讲第一节的量词顺序，不增加第二节或习题。';$('generateForm').requestSubmit()");
  await until(pc,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.filter(j=>j.kind==='generate'&&j.status==='completed').length===2)`);
  calls=(await run(pc,"api('/__library_test__/calls')")).calls;
  const phoneAudit=calls.find(c=>c.response_format?.type==='json_object'&&c.messages.at(-1).content.includes('PHONE_SCOPE'));
  const revision=calls.find(c=>c.messages[0].content.includes('根据核查报告修订讲解'));
  assert(phoneAudit&&revision);assert(scope(phoneAudit.messages.at(-1).content).student_requirements.includes('PHONE_SCOPE'));assert(scope(revision.messages.at(-1).content).student_requirements.includes('PHONE_SCOPE'));assert(scope(revision.messages.at(-1).content).detail_guidance.includes('概括性较强'));
  pass('Paired phone generation supplies its own new instruction and level; the actual balanced revision receives the identical scope after the controlled audit defect');
  outputs=await run(pc,"api('/__scope_test__/outputs')");const fixed=outputs.documents.find(d=>d.content.includes('统一门槛的修订讲解'));assert(fixed&&!fixed.content.includes('DRAFT_NEEDS_FIX'));meta=JSON.parse(fixed.metadata_json);assert.equal(meta.reviews.length,2);assert(meta.reviews.every(r=>r.teaching_scope.summary_level===2));assert.equal(outputs.exercise_count,0);
  const artifacts=await run(phone,`api('/api/projects/${data.project_id}/artifacts')`),artifact=artifacts.find(a=>a.kind==='explanation'&&a.metadata.generation_job_id===fixed.job_id)||artifacts.find(a=>a.kind==='explanation'&&a.title.includes('修订'));
  assert(artifact);const download=await run(phone,`fetch('/api/artifacts/${artifact.id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  await run(phone,"openSheet('generateDialog')");await shot(phone,'phone-scoped-document');pass('Revised Word result downloads on the paired phone; both audit and revision have saved scope receipts, and neither workflow creates unsolicited exercises');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:calls.length,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
