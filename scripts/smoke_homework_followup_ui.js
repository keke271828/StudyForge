const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-homework-followup'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<400;i++){if(await run(w,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function create(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function shot(w,name){await sleep(250);w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));w.webContents.debugger.detach();}
const answer="$('messages').textContent.includes('恢复了原来的2')";
function toolResults(calls){return calls.filter(c=>c.messages.at(-1)?.role==='tool').map(c=>JSON.parse(c.messages.at(-1).content));}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,"$('prompt').value='第2题我为什么算错？只解释这一题，不出新题。';$('sendMessage').click()");
  await until(pc,answer+"&&!liveChats.size");
  let calls=(await run(pc,"api('/__library_test__/calls')")).calls;
  assert.equal(calls.length,2);let results=toolResults(calls);assert.equal(results.length,1);
  assert(results[0].text.includes('2+3=4')&&results[0].text.includes('FEEDBACK_ADD'));
  assert(!results[0].text.includes('FEEDBACK_GAUSS'));assert(await run(pc,"$('messages').querySelectorAll('.katex').length>0"));
  checks.push('Desktop real chat round-trip reads only question 2 and renders its follow-up with math');await shot(pc,'desktop-homework-followup');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='作业追问验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await until(phone,answer);
  await run(phone,"$('prompt').value='第2题的逆运算为什么能核对？只补这一步。';send()");
  await until(phone,"!mobile.runs.size&&!mobile.sending?.size&&$('messages').querySelectorAll('.message.assistant').length>=3");
  await until(pc,"api('/__library_test__/calls').then(r=>r.calls.length===4)");
  calls=(await run(pc,"api('/__library_test__/calls')")).calls;results=toolResults(calls);assert.equal(results.length,2);
  assert(results.every(r=>r.question_number===2&&r.attempt_id===data.homework_attempt_id));
  checks.push('Paired HTTPS phone starts its own real chat round-trip and reads the same selected question');await shot(phone,'phone-homework-followup');
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');await until(phone,answer);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,4);
  checks.push('Phone reload restores the follow-up without repeating model or grading requests');
  const downloaded=await run(phone,`fetch('/api/artifacts/${data.artifact_id}/download').then(async r=>({status:r.status,bytes:(await r.arrayBuffer()).byteLength}))`);
  assert.equal(downloaded.status,200);assert(downloaded.bytes>1000);checks.push('Phone can still download the actual DOCX feedback');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'),{conversationId:'${data.other_conversation_id}'})`);
  await until(pc,`state.conversation==='${data.other_conversation_id}'&&!conversationUI.restoring`);
  await run(pc,"$('prompt').value='第2题为什么错了？';$('sendMessage').click()");
  await until(pc,"!liveChats.size&&$('messages').textContent.includes('本对话没有已关联的作业记录')");
  calls=(await run(pc,"api('/__library_test__/calls')")).calls;
  assert.equal(calls.length,5);assert(!calls.at(-1).messages[0].content.includes(data.homework_attempt_id));
  checks.push('Switching to a different project does not inject the original homework or its answers');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_requests:5,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
