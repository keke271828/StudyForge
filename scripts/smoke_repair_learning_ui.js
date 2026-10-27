const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-repair'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<300;i++){if(await run(w,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1460,height:1080,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert.equal(await run(pc,'state.conversation'),data.conversation_id);
  await run(pc,'openHomework({history:true})');
  await until(pc,`$('homeworkDialog').querySelector('[data-repair-set="${data.set_id}"]')`);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);await shot(pc,'desktop-repair-entry');
  pass('A completed 95-point paper offers voluntary targeted repair in the desktop workbench; viewing makes no model call');
  await run(pc,`$('homeworkDialog').querySelector('[data-repair-set="${data.set_id}"]').click()`);
  await until(pc,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.some(j=>j.kind==='repair'&&j.status==='completed'))`);
  const rows=await run(pc,`api('/api/projects/${data.project_id}/jobs')`),job=rows.find(j=>j.kind==='repair');
  const done=await run(pc,`api('/api/jobs/${job.id}')`),output=done.result.output,fresh=output.exercise_set;
  assert.equal(fresh.questions.length,1);assert.equal(fresh.difficulty,2);assert.equal(fresh.repair.targets[0].basis,'student_self_report');
  assert(!JSON.stringify(fresh).includes('REPAIR_PRIVATE'));pass('Actual background repair makes one question for the single error, retains reference difficulty and self-report boundary, and hides private answers');
  await run(pc,`$('homeworkDialog').close();showView('exercises');refreshExercises()`);
  await until(pc,`document.querySelector('[data-open-set="${fresh.id}"]')`);await run(pc,`openSet('${fresh.id}')`);
  assert(await run(pc,`$('set-${fresh.id}').querySelector('[data-repair-reference]').textContent.includes('原第1题')`));await shot(pc,'desktop-repair-reference');
  const calls=(await run(pc,"api('/__library_test__/calls')")).calls;assert.equal(calls.length,4);
  const design=calls.find(c=>c.messages[0].content.includes('严谨的习题设计者')).messages.at(-1).content;
  assert(design.includes('我把电通量当成了每个点的电场'));assert(design.includes(data.source_text));assert.equal(design.split('修复目标数据：').length-1,1);
  pass('Desktop question view identifies original target; native request receives full source and actual cause/teaching once, with four existing model steps');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='错因再练验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`studyforgeMobileHomework.open().then(()=>studyforgeMobileHomework.openAttempt('${data.attempt_id}'))`);
  await until(phone,"[...$('homeworkResult').querySelectorAll('button')].some(b=>b.textContent==='按本次错因同难度再练')");await shot(phone,'phone-repair-entry');
  await run(phone,"[...$('homeworkResult').querySelectorAll('button')].find(b=>b.textContent==='按本次错因同难度再练').click()");
  await until(pc,`api('/api/projects/${data.project_id}/jobs').then(rows=>rows.filter(j=>j.kind==='repair'&&j.status==='completed').length===2)`);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,4);pass('Paired phone also offers repair above 80 and reuses the same completed reference without new model calls');
  await run(phone,`studyforgeMobileHomework.openSet('${fresh.id}')`);
  await until(phone,"$('homeworkQuestions').querySelector('[data-repair-reference]')");await shot(phone,'phone-repair-reference');
  const artifact=output.artifact,download=await run(phone,`fetch('/api/artifacts/${artifact.id}/download').then(async r=>({status:r.status,prefix:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);
  assert.equal(download.status,200);assert.deepEqual(download.prefix,[80,75]);pass('Phone shows the same target provenance and downloads actual Word worksheet');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:4,external_model_requests:0},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
