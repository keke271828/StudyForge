const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-selected-repair'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(window,code)=>window.webContents.executeJavaScript(code);
async function until(window,code){for(let i=0;i<400;i++){if(await run(window,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(value){checks.push(value);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks,console_errors:errors},null,2));}
function create(width,height){const window=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(window);window.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return window;}
async function shot(window,name){await sleep(200);if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const data=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(data.data,'base64'));window.webContents.debugger.detach();}
const ready="$('repairPicker')?.open&&$('repairPickerList').querySelectorAll('input').length===2";
const chosen="[...$('repairPickerList').querySelectorAll('input:checked')].map(input=>Number(input.value))";
async function generate(window,indices,count){
  await run(window,`$('repairPickerList').querySelectorAll('input').forEach(input=>input.checked=${JSON.stringify(indices)}.includes(Number(input.value)));$('repairPickerList').dispatchEvent(new Event('change'));$('startSelectedRepair').click()`);
  await until(window,"!$('repairPicker').open");
  await until(window,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.filter(row=>row.kind==='repair'&&row.status==='completed').length===${count})`);
  const jobs=await run(window,`api('/api/projects/${data.project_id}/jobs')`),job=jobs.filter(row=>row.kind==='repair').sort((a,b)=>b.created_at.localeCompare(a.created_at))[0];
  return (await run(window,`api('/api/jobs/${job.id}')`)).result.output;
}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert.equal(await run(pc,'state.conversation'),data.conversation_id);
  const before=await run(pc,"api('/__repair_test__/snapshot')");
  await run(pc,`studyforgeHomeworkReader.open('${data.attempt_id}')`);
  await until(pc,"$('homeworkReader')?.open&&!document.querySelector('.homework-reader .primary').disabled");
  await run(pc,"$('homeworkReaderQuestion').value='2';$('homeworkReaderQuestion').dispatchEvent(new Event('change'))");
  await until(pc,"!document.querySelector('.homework-reader .primary').disabled&&!document.querySelector('.homework-reader footer button:nth-of-type(3)').hidden");
  await run(pc,"document.querySelector('.homework-reader footer button:nth-of-type(3)').click()");await until(pc,ready);
  assert.deepEqual(await run(pc,chosen),[1]);assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  pass('Reader opens the selection modal with only original question 2 selected; opening and choosing make no model request');await shot(pc,'desktop-selected-one');
  await run(pc,"document.querySelectorAll('.repair-picker-tools button')[1].click()");
  assert(await run(pc,"$('startSelectedRepair').disabled"));
  pass('Clearing the selection disables generation instead of falling back to the whole paper');
  const first=await generate(pc,[1],1);
  assert.equal(first.exercise_set.questions.length,1);assert.deepEqual(first.exercise_set.repair.targets.map(item=>item.index),[1]);
  assert(!JSON.stringify(first).includes('PRIVATE_'));assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,4);
  pass('Actual background task receives only the selected original index, generates one new question, and hides private answers');
  await run(pc,"studyforgeHomeworkReader.close();openHomework({history:true})");
  await until(pc,`$('homeworkDialog').querySelector('[data-repair-set="${data.set_id}"]')`);
  await run(pc,`$('homeworkDialog').querySelector('[data-repair-set="${data.set_id}"]').click()`);await until(pc,ready);
  assert.deepEqual(await run(pc,chosen),[0,1]);
  const second=await generate(pc,[0],2);
  assert.notEqual(second.exercise_set.id,first.exercise_set.id);assert.deepEqual(second.exercise_set.repair.targets.map(item=>item.index),[0]);
  pass('The existing whole-paper entry now lets the learner choose original question 1 independently');
  await run(pc,`studyforgeRepairPicker.open('${data.set_id}')`);await until(pc,ready);await shot(pc,'desktop-selected-all');
  const both=await generate(pc,[0,1],3);assert.equal(both.exercise_set.questions.length,2);
  assert.notEqual(both.exercise_set.id,first.exercise_set.id);assert.notEqual(both.exercise_set.id,second.exercise_set.id);
  await run(pc,`studyforgeRepairPicker.open('${data.set_id}',[1])`);await until(pc,ready);
  const repeat=await generate(pc,[1],4);assert(repeat.cached&&repeat.exercise_set.id===first.exercise_set.id);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,12);
  pass('One-question and two-question scopes remain independently reusable; returning to question 2 adds no new model call');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='单题再练验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.openAttempt('${data.attempt_id}')`);
  await until(phone,"[...$('homeworkResult').querySelectorAll('button')].some(button=>button.textContent==='按本次错因同难度再练')");
  await run(phone,"[...$('homeworkResult').querySelectorAll('button')].find(button=>button.textContent==='按本次错因同难度再练').click()");await until(phone,ready);
  assert.deepEqual(await run(phone,chosen),[0,1]);await shot(phone,'phone-select-390');
  pass('The authenticated HTTPS phone opens the same selection interface from its homework entry');
  await run(phone,"theme('dark')");phone.setSize(320,844);await sleep(200);
  assert(await run(phone,"$('repairPicker').scrollWidth<=$('repairPicker').clientWidth+1"));await shot(phone,'phone-select-320-dark');
  pass('The 320px dark viewport keeps both target labels and the generation action readable without horizontal overflow');
  const fromPhone=await generate(phone,[0],5);
  assert(fromPhone.cached&&fromPhone.exercise_set.id===second.exercise_set.id);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,12);
  const download=await run(phone,`fetch('/api/artifacts/${fromPhone.artifact.id}/download').then(async result=>({status:result.status,prefix:[...new Uint8Array(await result.arrayBuffer())].slice(0,2)}))`);
  assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);
  pass('Phone submits only its selected target, reuses the matching existing group, and downloads the actual DOCX');
  assert.deepEqual(await run(pc,"api('/__repair_test__/snapshot')"),before);
  pass('Choosing and generating repair worksheets does not duplicate the original submission, alter its score, or add mastery/profile evidence');
  const requests=(await run(pc,"api('/__library_test__/calls')")).calls;
  const audits=requests.filter(item=>item.messages[0].content.includes('习题审查员'));
  const solvers=requests.filter(item=>item.messages[0].content.includes('独立解题员'));
  assert.equal(audits.length,6);assert.equal(solvers.length,3);
  assert(audits.every(item=>item.messages.at(-1).content.includes('修复练习的原始教学范围')));
  assert(solvers.every(item=>!item.messages.at(-1).content.includes('修复练习的原始教学范围')));
  pass('Both auditors receive the original selected teaching scope; the independent solver still receives only the new question and source');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_requests:12,external_model_requests:0,synthetic_content:true,physical_android:false,exercise_ids:[first.exercise_set.id,second.exercise_set.id,both.exercise_set.id],artifact_ids:[first.artifact.id,second.artifact.id,both.artifact.id]},null,2));
  windows.forEach(window=>window.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [index,window]of windows.entries())if(window.webContents.getURL())await shot(window,'failed-'+index);windows.forEach(window=>window.destroy());app.exit(1);}
});
