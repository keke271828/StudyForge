const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-voice'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(window,code)=>window.webContents.executeJavaScript(code);
async function until(window,code){for(let i=0;i<400;i++){if(await run(window,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(text){checks.push(text);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks},null,2));}
function create(width,height){const window=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(window);window.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});return window;}
async function shot(window,name){await sleep(200);if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const image=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(image.data,'base64'));window.webContents.debugger.detach();}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const baseline=await run(pc,"api('/__voice_test__/snapshot')");
  await run(pc,"showView('profile');refreshProfile()");
  await until(pc,"$('learningMemory').textContent.includes('OWN_QUESTION')");
  assert(await run(pc,"!$('learningMemory').textContent.includes('COPIED_CLAIM_NO_TEACHING')"));
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  pass('Desktop migration retains the learner question and hides only the copied judgment without any model request');await shot(pc,'desktop-own-profile');
  await run(pc,"$('profileStatus').value='removed';refreshProfile(false)");
  await until(pc,"$('learningMemory').textContent.includes('COPIED_CLAIM_NO_TEACHING')");
  await run(pc,`document.querySelector('[data-profile-insight="${data.profile_wrong_id}"]').click()`);
  await until(pc,"$('profileEvidenceDialog').open&&!$('profileEvidenceBody').hidden");
  assert(await run(pc,`$('profileEvidenceQuote').textContent===${JSON.stringify(data.external_quote)}&&$('profileEvidenceText').textContent.includes(${JSON.stringify(data.own_question)})`));
  assert(await run(pc,"$('profileEvidenceNotice').textContent.includes('明确引用')&&!$('restoreProfileInsight').hidden"));
  pass('Excluded history explains the attribution reason and preserves the full original message and judgment for inspection');await shot(pc,'desktop-excluded-evidence');
  await run(pc,"$('restoreProfileInsight').click()");
  await until(pc,"!profileState.saving&&$('profileEvidenceStatus').textContent.includes('恢复')");
  assert(!(await run(pc,`api('/api/profile/insights/${data.profile_wrong_id}/evidence')`)).insight.deleted);
  pass('The user can explicitly restore the excluded record without deleting or rewriting its original evidence');
  await run(pc,"$('removeProfileInsight').click();$('confirmProfileRemoval').click()");
  await until(pc,"!profileState.saving&&$('profileEvidenceStatus').textContent.includes('已移出')");
  await run(pc,"$('closeProfileEvidence').click();$('profileStatus').value='active';refreshProfile(false)");
  await until(pc,"$('learningMemory').textContent.includes('OWN_QUESTION')&&!$('learningMemory').textContent.includes('COPIED_CLAIM_NO_TEACHING')");
  assert.deepEqual(await run(pc,"api('/__voice_test__/snapshot')"),baseline);
  pass('Restore/remove controls leave original messages, both stored judgments, submissions, and mastery scores unchanged');
  await run(pc,"showView('study')");
  const send=`fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:'${data.project_id}',conversation_id:'${data.conversation_id}',provider:'deepseek',model:'deepseek-flash',source_ids:[],text:'请解释高斯定律的净通量。'})}).then(async response=>({status:response.status,text:await response.text()}))`;
  const desktop=await run(pc,send);assert.equal(desktop.status,200);assert(!desktop.text.includes('"error"'));
  let requests=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(requests.length,1);
  const context=JSON.stringify(requests[0].messages.filter(item=>item.role==='system'));
  assert(context.includes('OWN_QUESTION')&&!context.includes('COPIED_CLAIM_NO_TEACHING'));
  pass('The native desktop tutor request receives the valid learning summary and excludes the rejected copied claim');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='画像归属验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(result=>result.devices.some(item=>item.status==='pending'&&item.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const result=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=result.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  await run(phone,"$('prompt').value='请解释高斯定律的净通量。';$('composer').requestSubmit()");
  await until(pc,"api('/__library_test__/calls').then(result=>result.calls.length===2)");
  await until(phone,"!mobile.runs.has(mobile.chat?.id)");
  requests=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(requests.length,2);
  const mobileContext=JSON.stringify(requests[1].messages.filter(item=>item.role==='system'));
  assert(mobileContext.includes('OWN_QUESTION')&&!mobileContext.includes('COPIED_CLAIM_NO_TEACHING'));
  pass('The paired HTTPS phone tutor uses the same filtered profile without exposing another chat transcript');await shot(phone,'phone-tutor');
  assert.equal((await run(pc,"api('/__voice_test__/snapshot')")).mastery.length,0);
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_requests:2,external_model_requests:0,physical_android:false},null,2));
  windows.forEach(window=>window.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const [i,window]of windows.entries())if(window.webContents.getURL())await shot(window,'failed-'+i);windows.forEach(window=>window.destroy());app.exit(1);}
});
