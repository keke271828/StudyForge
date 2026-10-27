/* Save one real public answer, no rewrite, on actual desktop/paired phone UI. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.resolve(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-answer-export'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
const q=s=>`document.querySelector(${JSON.stringify(s)})`,button=`[data-save-message="${data.message_id}"]`;
async function until(w,c){for(let i=0;i<300;i++){if(await run(w,`(async()=>Boolean(await (${c})))()`))return;await sleep(80);}throw Error('UI wait: '+c);}
async function shot(w,n){await run(w,'document.fonts.ready');if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const v=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,n+'.png'),Buffer.from(v.data,'base64'));}
function create(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{offscreen:true,sandbox:true,contextIsolation:true,backgroundThrottling:false}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function finished(w,fmt){await until(w,`api('/api/projects/${data.project_id}/artifacts').then(rows=>rows.some(r=>r.format==='${fmt}'&&r.metadata.chat_export))`);const rows=await run(w,`api('/api/projects/${data.project_id}/artifacts')`);return rows.find(r=>r.format===fmt&&r.metadata.chat_export);}
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,`state.ready&&state.conversation==='${data.conversation_id}'&&!conversationUI.restoring&&${q(button)}`);
  assert.equal(await run(pc,'document.querySelectorAll("[data-save-message]").length'),1);
  await run(pc,`${q(button)}.click()`);assert(await run(pc,"$('documentExportDialog').open&&$('documentExportFormat').options.length===6"));
  await shot(pc,'电脑端保存回答');await run(pc,"$('documentExportDialog').close()");
  assert(await run(pc,`api('/api/projects/${data.project_id}/jobs').then(r=>r.length===0)`));
  checks.push('Only completed public assistant answers offer Save; user/stopped answers do not, cancelling the chooser starts no task');
  await run(pc,`${q(button)}.click();$('documentExportDialog').querySelector('input').value='浅复制与共享对象 · 学习笔记';$('documentExportFormat').value='docx';$('documentExportDialog').querySelector('form').requestSubmit()`);
  const word=await finished(pc,'docx');assert.equal(word.metadata.chat_export.content_sha256,data.answer_sha256);assert.equal(word.origin.conversation_id,data.conversation_id);assert(!word.metadata.generation_job_id);
  assert(word.download_filename.includes('浅复制与共享对象')&&word.download_filename.endsWith('.docx'));
  await run(pc,'refreshSources();refreshArtifacts()');await until(pc,`state.sources.some(r=>r.artifact_id==='${word.id}')`);
  await run(pc,"showView('artifacts')");await until(pc,`${q('[data-artifact="'+word.id+'"] .source-evidence')}`);
  await run(pc,`${q('[data-artifact="'+word.id+'"] .source-evidence>summary')}.click()`);
  assert(await run(pc,`${q('[data-artifact="'+word.id+'"] .source-evidence')}.textContent.includes('没有重新生成')||${q('[data-artifact="'+word.id+'"] .source-evidence')}.textContent.includes('未重新生成')`));
  checks.push('Real DOCX uses the exact saved answer hash, friendly name, original chat and project quick references, with no fake generation review');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'))`);await until(pc,`state.project?.id==='${data.other_project_id}'&&!state.projectLoading`);
  assert.equal((await run(pc,`api('/api/projects/${data.other_project_id}/artifacts')`)).length,0);
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'))`);await until(pc,`${q(button)}`);
  await pc.reload();await until(pc,`${q(button)}`);assert.equal(await run(pc,'document.querySelectorAll("[data-save-message]").length'),1);
  checks.push('Switching projects isolates outputs; reload restores a single Save action on the original answer');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`),name='回答保存验收手机 '+Date.now();
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,`mobile.authenticated&&mobile.chat?.id==='${data.conversation_id}'&&${q(button)}`);
  await run(phone,`${q(button)}.click();theme('dark')`);assert(await run(phone,"$('documentExportDialog').open"));
  phone.setSize(320,844);await run(phone,'new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  assert(await run(phone,"$('documentExportDialog').scrollWidth<=$('documentExportDialog').clientWidth+1"));await shot(phone,'手机端保存回答320');
  await run(phone,"$('documentExportDialog').querySelector('input').value='手机保存的浅复制讲解';$('documentExportFormat').value='md';$('documentExportDialog').querySelector('form').requestSubmit()");
  const md=await finished(phone,'md');assert.equal(md.metadata.chat_export.content_sha256,data.answer_sha256);
  const download=await run(phone,`fetch('${md.download_url}').then(async r=>({status:r.status,text:await r.text()}))`);
  assert.equal(download.status,200);const digest=await run(phone,`fetch('${md.download_url}').then(r=>r.arrayBuffer()).then(b=>crypto.subtle.digest('SHA-256',b)).then(b=>[...new Uint8Array(b)].map(n=>n.toString(16).padStart(2,'0')).join(''))`);assert.equal(digest,data.answer_sha256);
  checks.push('Paired HTTPS phone saves and downloads exact Markdown bytes; dark chooser fits 320px and computes the same Unicode hash');
  const bad=await run(phone,`fetch('/api/messages/${data.message_id}/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:'${data.other_project_id}',conversation_id:'${data.conversation_id}',content_sha256:'${data.answer_sha256}',format:'docx',request_id:crypto.randomUUID().replaceAll('-','')})}).then(r=>r.status)`);assert.equal(bad,404);
  const messages=await run(pc,`api('/api/conversations/${data.conversation_id}?project_id=${data.project_id}')`);assert.equal(messages.messages.length,3);
  assert.equal((await run(pc,`api('/api/projects/${data.project_id}/lesson-feedback')`)).length,0);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);assert(!errors.length,JSON.stringify(errors));
  checks.push('Cross-project phone export is rejected, original chat count remains three, and saving causes no model request or new questionnaire');
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,word_artifact:word,markdown_artifact:md,model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(e){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:e.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'失败-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
