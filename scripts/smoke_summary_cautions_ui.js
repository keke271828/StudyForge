const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-summary-cautions'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<350;i++){if(await run(w,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function create(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function shot(w,name){await sleep(250);w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));w.webContents.debugger.detach();}
const evidence="document.querySelector('.source-evidence-body')?.textContent";
function verify(text){assert(text.includes('全文总结的核查记录'));assert(/共\s*2\s*段核查记录/.test(text));assert(/保留\s*1\s*段/.test(text));assert(/另有\s*1\s*段未列入/.test(text));assert(text.includes('不是已确认错误数'));}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,"showView('artifacts');refreshArtifacts()");await until(pc,"document.querySelector('.source-evidence')");
  await run(pc,"document.querySelector('.source-evidence > summary').click()");await until(pc,evidence);verify(await run(pc,evidence));
  checks.push('Desktop artifact panel displays actual summary receipt: 2 records, 1 included, 1 omitted, distinguished from confirmed errors');await shot(pc,'desktop-summary-cautions');
  await run(pc,"refreshArtifacts()");await until(pc,"document.querySelector('.source-evidence[open] .source-evidence-body')");verify(await run(pc,evidence));checks.push('Desktop refresh keeps evidence expanded with the same saved counts');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='总结核查验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,"$('openArtifacts').click()");await until(phone,"document.querySelector('#artifactList .source-evidence')");
  await run(phone,"document.querySelector('#artifactList .source-evidence > summary').click()");await until(phone,evidence);verify(await run(phone,evidence));checks.push('Paired HTTPS phone shows the same saved receipt in its artifact sheet');await shot(phone,'phone-summary-cautions');
  const downloaded=await run(phone,`fetch('/api/artifacts/${data.artifact_id}/download').then(async r=>({status:r.status,bytes:(await r.arrayBuffer()).byteLength}))`);assert.equal(downloaded.status,200);assert(downloaded.bytes>1000);checks.push('Paired phone can download the actual local Word file');
  const calls=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(calls.length,0);assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,external_model_requests:0,model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
