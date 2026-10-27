const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-network'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<350;i++){if(await run(w,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function create(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|503|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
async function shot(w,name){await sleep(350);w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));w.webContents.debugger.detach();}
async function choose(pc,mode){await run(pc,`$('apiConnectionMode').value='${mode}';$('apiConnectionMode').dispatchEvent(new Event('change'));`);await until(pc,`!apiNetworkSettings.pending&&apiNetworkSettings.confirmed==='${mode}'`);}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,"api('/api/settings',jsonOptions('PUT',{api_connection_mode:'system'})).then(config=>applyApiNetworkSettings(config))");
  await run(pc,"showView('settings');$('settings-tab-models').click()");assert.equal(await run(pc,"$('apiConnectionMode').value"),'system');
  assert(await run(pc,"$('apiConnectionMode').checkVisibility()"));
  await choose(pc,'direct');assert.equal(await run(pc,"api('/api/settings').then(s=>s.api_connection_mode)"),'direct');
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&!conversationUI.restoring&&apiNetworkSettings.confirmed==='direct'");await run(pc,"showView('settings');$('settings-tab-models').click()");
  assert.equal(await run(pc,"$('apiConnectionMode').value"),'direct');pass('Desktop API route selection saves immediately and survives a full reload');
  await run(pc,`window.realNetworkFetch=window.fetch;window.staleCaptured=false;window.captureStale=true;window.fetch=async(...args)=>{const response=await realNetworkFetch(...args);if(window.captureStale&&args[0]==='/api/settings'&&(!args[1]||!args[1].method||args[1].method==='GET')){window.captureStale=false;window.staleCaptured=true;await new Promise(resolve=>window.releaseStale=resolve);}return response;};window.staleRefresh=refreshSettings();true;`);
  await until(pc,'window.staleCaptured');await choose(pc,'system');await run(pc,'releaseStale();window.staleRefresh');
  assert.equal(await run(pc,"$('apiConnectionMode').value"),'system');assert.equal(await run(pc,'state.settings.api_connection_mode'),'system');
  await run(pc,'window.fetch=window.realNetworkFetch;true;');pass('An older settings response cannot overwrite the route selected while it was in flight');
  await run(pc,`window.fetch=async(...args)=>{if(args[0]==='/api/settings'&&args[1]?.method==='PUT'&&JSON.parse(args[1].body||'{}').api_connection_mode==='direct')return new Response(JSON.stringify({detail:'Controlled save failure'}),{status:503,headers:{'Content-Type':'application/json'}});return realNetworkFetch(...args);};$('apiConnectionMode').value='direct';$('apiConnectionMode').dispatchEvent(new Event('change'));`);
  await until(pc,'!apiNetworkSettings.pending');assert.equal(await run(pc,"$('apiConnectionMode').value"),'system');assert.equal(await run(pc,'state.settings.api_connection_mode'),'system');
  assert.equal(await run(pc,"api('/api/settings').then(s=>s.api_connection_mode)"),'system');await run(pc,'window.fetch=window.realNetworkFetch;true;');
  pass('A controlled settings-save failure restores the confirmed selection and leaves persisted configuration intact');
  await choose(pc,'direct');await run(pc,"api('/__network_test__/routes/reset',{method:'POST'})");
  await run(pc,"$('loadDeepSeekModels').click()");await until(pc,"!$('loadDeepSeekModels').disabled");
  await run(pc,"api('/api/diagnostics/deepseek',{method:'POST'})");
  await run(pc,"showView('study');$('reviewMode').value='fast';$('summaryLevel').value='1';$('outputFormat').value='docx';$('generationContent').value='explanation';$('withExercises').checked=false;$('prompt').value='DESKTOP_NET：只解释第一节统一门槛，不出题。';$('generate').click()");
  await until(pc,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.some(j=>j.kind==='generate'&&j.status==='completed'))`);
  let routes=await run(pc,"api('/__network_test__/routes')");assert(routes.routes.length>=3);assert(routes.routes.every(r=>r.trust_env===false&&r.verify_enabled));
  pass('Catalog refresh, connection diagnosis and native desktop lecture/audit use direct mode with certificate verification enabled');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='连接方式验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  await run(pc,"api('/__network_test__/routes/reset',{method:'POST'})");
  await run(phone,"$('generateFromOptions').click();$('reviewMode').value='express';$('outputFormat').value='docx';$('withExercises').checked=false;$('generationInstructions').value='PHONE_NET：只解释第一节统一门槛，不出题。';$('generateForm').requestSubmit()");
  await until(pc,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.filter(j=>j.kind==='generate'&&j.status==='completed').length===2)`);
  routes=await run(pc,"api('/__network_test__/routes')");assert(routes.routes.length>0);assert(routes.routes.every(r=>r.trust_env===false&&r.verify_enabled));
  const artifacts=await run(phone,`api('/api/projects/${data.project_id}/artifacts')`),artifact=artifacts.find(a=>a.kind==='explanation');assert(artifact);
  const file=await run(phone,`fetch('/api/artifacts/${artifact.id}/download').then(async r=>({status:r.status,bytes:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(file.status,200);assert.deepEqual(file.bytes,[80,75]);
  pass('A genuinely paired HTTPS phone generates and downloads a Word result through the same selected API route');
  await run(pc,"showView('settings');$('settings-tab-models').click();$('apiConnectionMode').scrollIntoView({block:'center'})");assert(await run(pc,"$('apiConnectionMode').checkVisibility()"));await shot(pc,'desktop-api-route');await shot(phone,'phone-api-result');
  await choose(pc,'system');await run(pc,"api('/__network_test__/routes/reset',{method:'POST'});api('/api/diagnostics/deepseek',{method:'POST'})");
  routes=await run(pc,"api('/__network_test__/routes')");assert(routes.routes.some(r=>r.trust_env===true&&r.verify_enabled));pass('Switching back to environment mode changes the next real transport rather than just the label');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
