const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-homework-reader'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
checks.push=function(...values){Array.prototype.push.apply(this,values);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify({checks:[...this],console_errors:errors},null,2));return this.length;};
const run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<400;i++){if(await run(w,code))return;await sleep(100);}throw Error('Wait failed: '+code);}
function create(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function shot(w,name){await sleep(200);w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));w.webContents.debugger.detach();}
const ready="$('homeworkReader')?.open&&!document.querySelector('.homework-reader .primary').disabled&&/已交付|已显示/.test(document.querySelector('.homework-reader-status').textContent)";
const select=n=>`$('homeworkReaderQuestion').value='${n}';$('homeworkReaderQuestion').dispatchEvent(new Event('change'))`;
app.whenReady().then(async()=>{
 const pc=create(1440,1000),phone=create(390,844);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const old=await run(pc,"$('messages').querySelectorAll('.message').length");
  await run(pc,"openHomework({history:true})");
  await until(pc,`$('homeworkHistory').querySelector('[data-homework-read="${data.homework_attempt_id}"]')`);
  await run(pc,`$('homeworkHistory').querySelector('[data-homework-read="${data.homework_attempt_id}"]').click()`);
  await until(pc,ready);
  assert(await run(pc,"$('homeworkReaderContent').textContent.includes('FEEDBACK_GAUSS')&&!$('homeworkReaderContent').textContent.includes('FEEDBACK_ADD')"));
  assert(await run(pc,"!document.querySelector('.homework-reader footer button').hidden"));
  const initialLength=await run(pc,"$('homeworkReaderContent').textContent.length");
  await run(pc,"document.querySelector('.homework-reader footer button').click()");
  await until(pc,`$('homeworkReaderContent').textContent.length>${initialLength}&&!document.querySelector('.homework-reader .primary').disabled`);
  assert(await run(pc,"document.querySelector('.homework-reader-body').scrollHeight>document.querySelector('.homework-reader-body').clientHeight"));
  checks.push('Desktop opens published per-question feedback in a separate scrollable reader and lazily continues a long record');
  await run(pc,select(2));await until(pc,ready+"&&$('homeworkReaderContent').textContent.includes('5−3=2')");
  assert(await run(pc,"!$('homeworkReaderContent').textContent.includes('FEEDBACK_GAUSS')&&$('homeworkReaderContent').querySelectorAll('.katex').length>0"));
  assert.equal(await run(pc,"$('messages').querySelectorAll('.message').length"),old);
  checks.push('Switching question replaces the record, renders math, and inserts no chat messages');await shot(pc,'desktop-question-reader');
  await run(pc,"document.querySelector('.homework-reader-body').scrollTop=document.querySelector('.homework-reader-body').scrollHeight");await shot(pc,'desktop-question-teaching');
  await run(pc,"$('prompt').value='保留这段原草稿';document.querySelector('.homework-reader .primary').click()");
  await until(pc,"!$('homeworkReader').open&&$('prompt').value.includes('第 2 题')");
  assert(await run(pc,"$('prompt').value.includes('保留这段原草稿')"));
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  checks.push('Return-to-original-chat prefills a question label, preserves the draft, and sends no AI request');
  const other=await run(pc,`api('/api/projects/${data.project_id}/conversations',jsonOptions('POST',{provider:'deepseek'}))`);
  await run(pc,`selectConversation('${other.id}')`);await until(pc,`state.conversation==='${other.id}'&&!conversationUI.restoring`);
  await run(pc,`$('prompt').value='另一个对话的草稿不能丢';studyforgeHomeworkReader.open('${data.homework_attempt_id}')`);await until(pc,ready);
  await run(pc,select(2));await until(pc,ready+"&&$('homeworkReaderContent').textContent.includes('5−3=2')");
  await run(pc,"document.querySelector('.homework-reader .primary').click()");
  await until(pc,`state.conversation==='${data.conversation_id}'&&!conversationUI.restoring&&!$('homeworkReader').open`);
  assert(await run(pc,"$('prompt').value.includes('保留这段原草稿')&&!$('prompt').value.includes('另一个对话的草稿')"));
  const saved=await run(pc,`api('/api/conversations/${other.id}?project_id=${data.project_id}')`);
  assert(saved.draft.includes('另一个对话的草稿不能丢'));
  checks.push('Opening a project record from a different chat returns to its original chat and preserves both independent drafts');
  // Private preliminary analysis must not become public in the reader.
  await run(pc,`studyforgeHomeworkReader.open('${data.reader_pending_attempt}')`);await until(pc,ready);
  assert(await run(pc,"$('homeworkReaderContent').textContent.includes('REFERENCE_GAUSS')&&!$('homeworkReaderContent').textContent.includes('FEEDBACK_GAUSS')"));
  checks.push('Awaiting-cause attempt shows the already released reference but no unpublished diagnosis');
  await run(pc,"studyforgeHomeworkReader.close()");
  // Hold a real fetch until the modal has been closed, then release it.
  await run(pc,`window.readerOriginalFetch=window.fetch;window.readerRelease=null;window.fetch=async(...args)=>{if(String(args[0]).includes('/reading?')&&String(args[0]).includes('question_number=1'))await new Promise(resolve=>window.readerRelease=resolve);return window.readerOriginalFetch(...args)};void studyforgeHomeworkReader.open('${data.homework_attempt_id}')`);
  await until(pc,'Boolean(window.readerRelease)');await run(pc,'studyforgeHomeworkReader.close();window.readerRelease();window.fetch=window.readerOriginalFetch;void 0');await sleep(300);
  assert(await run(pc,"!$('homeworkReader').open"));checks.push('A delayed, aborted question request cannot reopen or populate a closed reader');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='逐题阅读验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  await run(phone,`studyforgeMobileHomework.openAttempt('${data.homework_attempt_id}')`);
  await until(phone,`$('homeworkResult').querySelector('[data-homework-read="${data.homework_attempt_id}"]')`);
  await run(phone,`$('homeworkResult').querySelector('[data-homework-read="${data.homework_attempt_id}"]').click()`);await until(phone,ready);
  await run(phone,select(2));await until(phone,ready+"&&$('homeworkReaderContent').textContent.includes('5−3=2')");
  assert(await run(phone,"$('homeworkReaderContent').querySelectorAll('.katex').length>0&&!$('homeworkReaderContent').textContent.includes('FEEDBACK_GAUSS')"));
  assert(await run(phone,"$('homeworkReader').scrollWidth<=$('homeworkReader').clientWidth+1"));await shot(phone,'phone-question-reader-390');
  await run(phone,"document.querySelector('.homework-reader-body').scrollTop=document.querySelector('.homework-reader-body').scrollHeight");await shot(phone,'phone-question-teaching-390');
  checks.push('Authenticated HTTPS phone opens the same real endpoint through the visible homework button, with correct per-question math');
  await run(phone,"theme('dark')");phone.setSize(320,844);await sleep(250);
  assert(await run(phone,"$('homeworkReader').scrollWidth<=$('homeworkReader').clientWidth+1"));await shot(phone,'phone-question-reader-320-dark');
  checks.push('Reader remains within a 320px dark-mode viewport and scrolls its content independently');
  await run(phone,"$('prompt').value='保留手机草稿';document.querySelector('.homework-reader .primary').click()");
  await until(phone,"!$('homeworkReader').open&&$('prompt').value.includes('第 2 题')");
  assert(await run(phone,"$('prompt').value.includes('保留手机草稿')"));
  checks.push('Phone return-to-chat preserves its existing draft and does not automatically submit');
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');
  assert(await run(phone,"$('prompt').value.includes('保留手机草稿')&&$('prompt').value.includes('第 2 题')"));
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,0);
  checks.push('Phone reload restores the draft; the full reader acceptance uses zero model calls');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_model_requests:0,external_model_requests:0,synthetic_content:true,physical_android:false},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
