// Actual desktop and paired HTTPS phone: hints do not alter model choices.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-hints'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<400;n++){if(await run(w,c))return;await sleep(60);}throw Error('UI wait failed: '+c);}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const before=await run(pc,'generationSelection()');await run(pc,"applyReviewMode('fast',false)");
  assert.deepEqual(await run(pc,'generationSelection()'),before);
  assert(await run(pc,"$('reviewModeHint').textContent.includes('不会自动降低模型推理强度')"));
  checks.push('Desktop review hint explains request count versus reasoning strength; selected model and effort are unchanged');
  assert(await run(pc,"fetch('/help/guide.html').then(r=>r.text()).then(s=>s.includes('原文准备、讲解撰写、讲解审查与本机排版')&&s.includes('另存格式'))"));
  checks.push('Offline guide contains stage diagnosis and reuse of delivered lecture text');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='Review hint phone '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  const choice=await run(phone,'[mobile.chat.model,mobile.chat.reasoning_effort]');await run(phone,"$('openGenerate').click()");
  await until(phone,"$('generateDialog').open&&document.querySelectorAll('dialog[open]').length===1");await sleep(350);
  assert(await run(phone,"$('reviewModeHint').getBoundingClientRect().height>0&&$('reviewModeHint').textContent.includes('高推理核查')"));
  assert.deepEqual(await run(phone,'[mobile.chat.model,mobile.chat.reasoning_effort]'),choice);
  checks.push('Paired HTTPS phone shows the same explanation inside the actual generation sheet without changing saved choices');await shot(phone,'phone-review-hint');
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  checks.push('Opening hints and reading the guide make zero model requests');assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,external_model_requests:0,controlled_model_calls:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
