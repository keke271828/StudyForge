/* Real desktop and paired HTTPS mobile provenance, mocked model only. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-evidence'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
const selector=`[data-artifact="${data.artifact_id}"] .source-evidence`;
const legacy=`[data-artifact="${data.legacy_artifact_id}"] .source-evidence`;
const query=selector=>`document.querySelector(${JSON.stringify(selector)})`;
const pass=message=>{checks.push(message);fs.appendFileSync(path.join(folder,'evidence-ui-log.txt'),message+'\n');};
async function until(w,code){for(let i=0;i<350;i++){if(await run(w,code))return;await sleep(100);}throw Error('UI wait failed: '+code);}
function watch(w){w.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const result=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));}
async function open(w,select=selector){await run(w,`${query(select)}?.querySelector('summary').click()`);await until(w,`${query(select)}?.open&&${query(select)}.querySelector('.source-evidence-body')`);}
async function verify(w){
 const body=await run(w,`${query(selector)}.textContent`);
 assert(body.includes('saved-reading-model')&&!body.includes('later-reading-model'));assert(body.includes('PDF 第 1–2 页')&&body.includes('50%'));
 assert(body.includes(data.old_reading_id.slice(0,8))&&body.includes('saved-scan-reader')&&body.includes('已标疑')&&body.includes('校订'));
 assert.equal(await run(w,`${query(selector)}.querySelectorAll('img').length`),0);assert(!(await run(w,'window.evidenceInjected')));
 assert.equal(await run(w,`${query(selector)}.querySelectorAll('li').length`),1);
}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation");await run(pc,"showView('artifacts')");await until(pc,`${query(selector)}`);
  assert.equal(await run(pc,"document.querySelectorAll('.source-evidence-body').length"),0);
  assert(await run(pc,`${query('[data-artifact="'+data.artifact_id+'"]')}.textContent.includes('选定范围')&&!${query('[data-artifact="'+data.artifact_id+'"]')}.textContent.includes('完整读取')`));
  pass('Real DOCX pipeline appears with an accurate selected-scope caption; evidence bodies are not created until expanded');
  await open(pc);await verify(pc);pass('Desktop shows the launch reading/model, original scope, suspect note and correction even after a newer reading completes; user text cannot inject HTML');
  await run(pc,"state.artifactSignature=null;refreshArtifacts()");await until(pc,`${query(selector)}?.open&&${query(selector)}.querySelector('.source-evidence-body')`);await verify(pc);
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'))`);
  await until(pc,`state.project?.id==='${data.other_project_id}'&&!state.projectLoading`);assert.equal(await run(pc,"document.querySelectorAll('.source-evidence').length"),0);
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'))`);await until(pc,`${query(selector)}?.open`);await verify(pc);
  pass('Refresh and project return preserve the expanded evidence; a different project does not show these documents');
  await open(pc,legacy);assert(await run(pc,`${query(legacy)}.textContent.includes('未保存阅读模型与版本')&&!${query(legacy)}.textContent.includes('later-reading-model')`));
  pass('Legacy documents explicitly show missing provenance and never borrow the current book model');
  await run(pc,`${query(legacy)}.open=false;${query(selector)}.scrollIntoView({block:'center'})`);await sleep(150);
  const bodyBox=await run(pc,`(()=>{const body=${query(selector)}.querySelector('.source-evidence-body'),r=body.getBoundingClientRect();return {x:r.left+30,y:r.top+40,overflow:body.scrollHeight>body.clientHeight};})()`);assert(bodyBox.overflow);
  if(!pc.webContents.debugger.isAttached())pc.webContents.debugger.attach('1.3');await pc.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseWheel',x:bodyBox.x,y:bodyBox.y,deltaX:0,deltaY:250});
  await until(pc,`${query(selector)}.querySelector('.source-evidence-body').scrollTop>0`);await run(pc,`${query(selector)}.querySelector('.source-evidence-body').scrollTop=0`);await shot(pc,'desktop-source-evidence');pass('Expanded source details scroll with a real browser wheel event, keeping the card controls usable');
  assert(await run(pc,`[...${query('[data-artifact="'+data.artifact_id+'"]')}.querySelectorAll('.card-actions>button,.card-actions>a')].every(button=>getComputedStyle(button).whiteSpace==='nowrap'&&button.scrollWidth<=button.clientWidth+1)`));
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='来源依据验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()),device=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat");await run(phone,"$('openArtifacts').click()");await until(phone,`${query(selector)}`);
  assert.equal(await run(phone,"document.querySelectorAll('.source-evidence-body').length"),0);await open(phone);await verify(phone);
  await run(phone,"refreshProject()");await until(phone,`${query(selector)}?.open`);await verify(phone);pass('A genuinely paired HTTPS phone renders the same saved scope/version and keeps expansion across its refreshes');
  for(const width of [390,320]){phone.setSize(width,844);await sleep(150);await run(phone,`${query(selector)}.scrollIntoView({block:'center'})`);
   assert(await run(phone,`${query(selector)}.scrollWidth<=${query(selector)}.clientWidth+1&&${query(selector)}.querySelector('.source-evidence-body').scrollHeight>${query(selector)}.querySelector('.source-evidence-body').clientHeight`));
   await shot(phone,'phone-source-evidence-'+width);
  }pass('The phone source panel wraps and scrolls at both 390 and 320 pixels');
  const download=await run(phone,`fetch('/api/artifacts/${data.artifact_id}/download').then(async r=>({status:r.status,signature:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.signature,[80,75]);
  pass('The phone still downloads the actual generated Word document; provenance needs no extra model request');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'evidence-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:data.model_requests,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'evidence-ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,console_errors:errors},null,2));for(const [i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'evidence-failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
