process.env.ELECTRON_DISABLE_SECURITY_WARNINGS='true';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]||'document-exports-ui-20261011-1');
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-profile'));app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'ui-log.txt'),text+'\n');}
async function until(win,code){for(let i=0;i<250;i++){if(await run(win,`(async()=>Boolean(await (${code})))()`))return;await sleep(80);}throw new Error('UI timeout: '+code);}
async function shot(win,name){await sleep(150);if(!win.webContents.debugger.isAttached())win.webContents.debugger.attach('1.3');const p=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
async function finished(win,format,count){await until(win,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.filter(r=>r.kind==='export'&&r.status==='completed').length>=${count})`);const rows=await run(win,`api('/api/projects/${data.project_id}/artifacts')`);const item=rows.find(r=>r.format===format&&r.metadata.reexport);assert(item);return item;}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({width:1320,height:960,show:false,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false}});
 const phone=new BrowserWindow({width:390,height:844,show:false,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false}});
 for(const [name,win] of [['desktop',pc],['phone',phone]])win.webContents.on('console-message',(event,level,message)=>{if(level>=2)errors.push(name+': '+message);});
 try{
  await pc.loadURL(data.desktop_url);await until(pc,`state.ready&&state.conversation==='${data.conversation_id}'&&window.studyforgeDocumentExports`);
  await run(pc,"showView('artifacts');refreshArtifacts()");
  await until(pc,`document.querySelector('[data-artifact="${data.artifact_id}"] [data-local-export]')`);
  await run(pc,`document.querySelector('[data-artifact="${data.artifact_id}"] [data-local-export]').click()`);
  assert(await run(pc,"$('documentExportDialog').open&&$('documentExportFormat').options.length===6"));
  await shot(pc,'desktop-local-export');
  await run(pc,"$('documentExportDialog').querySelector('[data-export-close]').click()");
  assert(await run(pc,`api('/api/projects/${data.project_id}/jobs').then(r=>!r.some(x=>x.kind==='export'))`));
  pass('Desktop artifact offers six local formats; cancelling the dialog starts no job');
  await run(pc,`document.querySelector('[data-artifact="${data.artifact_id}"] [data-local-export]').click();$('documentExportFormat').value='pdf';$('documentExportDialog').querySelector('form').requestSubmit()`);
  const pdf=await finished(pc,'pdf',1);assert(pdf.origin.conversation_id===data.conversation_id&&pdf.metadata.reexport.model_requests===0);
  await run(pc,"refreshSources();refreshArtifacts()");
  await until(pc,`state.sources.some(s=>s.artifact_id==='${pdf.id}')`);
  pass('Actual PDF export completes, retains the original chat, and becomes a project quick reference');
  await run(pc,`document.querySelector('[data-local-job="${data.saved_job_id}"] [data-local-export]').click();$('documentExportFormat').value='docx';$('documentExportDialog').querySelector('form').requestSubmit()`);
  await finished(pc,'docx',2);
  assert(await run(pc,`api('/api/jobs/${data.saved_job_id}').then(r=>r.status==='failed'&&r.export_formats.length===6)`));
  pass('Failed layout can be rescued as Word; the original failure record is retained');
  await run(pc,"document.documentElement.dataset.theme='night'");
  await run(pc,`document.querySelector('[data-artifact="${data.artifact_id}"] [data-local-export]').click()`);
  await shot(pc,'desktop-local-export-night');await run(pc,"$('documentExportDialog').close()");
  const ca=new X509Certificate(fs.readFileSync(data.certificate));
  phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let accepted=false;try{accepted=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(accepted?0:-3);});
  const pairing=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pairing.pairing_code);await until(phone,"typeof mobile!=='undefined'&&!$('pairScreen').hidden");
  const name='格式另存验收手机 '+Date.now();
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.name===${JSON.stringify(name)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&window.studyforgeDocumentExports&&mobile.artifacts.length>=3");
  await run(phone,"openSheet('artifactsDialog')");
  await run(phone,`document.querySelector('[data-local-export="${data.artifact_id}"]').click()`);
  assert(await run(phone,"$('documentExportDialog').open&&$('documentExportFormat').options.length===6"));
  phone.setSize(320,844);await shot(phone,'phone-local-export-320');
  assert(await run(phone,"$('documentExportDialog').scrollWidth-$('documentExportDialog').clientWidth<=1"));
  pass('Paired HTTPS phone shows the same chooser in a nested sheet and fits 320px width');
  await run(phone,"$('documentExportFormat').value='pptx';$('documentExportDialog').querySelector('form').requestSubmit()");
  const ppt=await finished(phone,'pptx',3);
  const download=await run(phone,`fetch('${ppt.download_url}').then(async r=>({ok:r.ok,type:r.headers.get('content-type'),size:(await r.arrayBuffer()).byteLength}))`);
  assert(download.ok&&download.size>1000);
  pass('Phone starts a real PPTX export through the paired allowlist and downloads its actual bytes');
  await run(phone,"$('artifactsDialog').close();openSheet('tasksDialog')");
  assert(await run(phone,`document.querySelector('[data-local-export="${data.saved_job_id}"]')!=null`));
  await run(phone,`document.querySelector('[data-local-export="${data.saved_job_id}"]').click()`);
  await run(phone,"theme('dark')");await shot(phone,'phone-layout-rescue-dark');
  await run(phone,"$('documentExportDialog').close();$('tasksDialog').close()");
  await pc.reload();await until(pc,"state.ready&&window.studyforgeDocumentExports");await run(pc,"showView('artifacts');refreshArtifacts()");
  await until(pc,"document.querySelectorAll('[data-artifact] [data-local-export]').length===4");
  pass('Restarting the UI restores the new files and their reusable export entry');
  const other=await run(pc,`api('/api/projects/${data.other_project_id}/artifacts')`);assert(other.length===0);
  const forbidden=await run(phone,`fetch('/api/artifacts/${data.artifact_id}/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:'${data.other_project_id}',format:'docx',request_id:crypto.randomUUID().replaceAll('-','')})}).then(r=>r.status)`);assert(forbidden===404);
  const calls=await run(pc,"api('/__library_test__/calls')");assert(calls.calls.length===0);
  pass('Every conversion used zero model calls, and cross-project export was rejected');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,pdf_artifact:pdf.id,model_requests:0},null,2));
  pc.destroy();phone.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,console_errors:errors},null,2));await shot(pc,'failed-desktop');if(phone.webContents.getURL())await shot(phone,'failed-phone');pc.destroy();phone.destroy();app.exit(1);}
});
