const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-error-help'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,code)=>w.webContents.executeJavaScript(code);
function create(width,height,partition){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false,partition}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|403|404|429|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function until(w,code){for(let i=0;i<500;i++){if(await run(w,code))return;await sleep(70);}throw Error('Wait failed: '+code);}
async function shot(w,name){await sleep(120);w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});w.webContents.debugger.detach();fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
const pass=value=>{checks.push(value);fs.writeFileSync(path.join(folder,'ui-progress.json'),JSON.stringify(checks,null,2));};
const close="$('operationErrorDialog').querySelector('header button').click()";
const panel="$('operationErrorDialog')?.open";
app.whenReady().then(async()=>{
 try{
  const pc=create(1440,1000,'error-pc');await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const original=await run(pc,"api('/__error_ui__/state')");
  await run(pc,"showView('artifacts')");await until(pc,`$('jobs').querySelector('[data-local-job="${data.error_jobs.json}"] .operation-error-action')`);
  assert(await run(pc,`(()=>{const card=$('jobs').querySelector('[data-local-job="${data.error_jobs.json}"]');return card.querySelector('.job-meta span').textContent==='未完成'&&card.textContent.includes('返回内容的格式')&&!card.textContent.includes('sk-fixture')})()`));
  await shot(pc,'desktop-failed-tasks');
  await run(pc,`$('jobs').querySelector('[data-local-job="${data.error_jobs.json}"] .operation-error-action').click()`);await until(pc,panel);
  assert(await run(pc,"$('operationErrorDialog').textContent.includes('避免重复发起')&&!$('operationErrorDialog').textContent.includes('sk-fixture')&&!window.errorInjected&&$('operationErrorDialog').querySelector('pre').querySelectorAll('img').length===0"));
  await run(pc,"$('operationErrorDialog').querySelector('details').open=true");await shot(pc,'desktop-json-help');
  await run(pc,"window.errorCopyOriginal=window.copyText;window.copyText=async()=>{throw new DOMException('denied','NotAllowedError')};$('operationErrorDialog').querySelector('details button').click()");
  await until(pc,"$('operationErrorDialog').querySelector('[role=status]').textContent.includes('已选中')");
  assert(await run(pc,"getSelection().toString().includes('JSONDecodeError')&&!getSelection().toString().includes('sk-fixture')"));await run(pc,"window.copyText=window.errorCopyOriginal;void 0");await run(pc,close);
  pass('A failed 100% job says unfinished; details retain the error, mask a sample key, render injected HTML as text, and denied clipboard access falls back to selected text');
  await run(pc,`api('/api/providers/${data.error_provider}/models').catch(error)`);
  await until(pc,"$('toast').querySelector('.operation-error-action')&&$('toast').textContent.includes('AI 服务暂时限制')");
  await run(pc,"$('toast').querySelector('.operation-error-action').click()");await until(pc,panel);
  assert(await run(pc,"$('operationErrorDialog').textContent.includes('减少同一服务')"));await shot(pc,'desktop-rate-limit');await run(pc,close);
  await run(pc,"toast('设置已保存')");assert(await run(pc,"!$('toast').querySelector('.operation-error-action')&&$('toast').textContent.includes('设置已保存')"));
  pass('An actual HTTP 429 has plain next steps and a detail action; replacing it with a success notice removes the obsolete error action');
  await run(pc,"showView('exercises')");await until(pc,`document.querySelector('[data-inline-task="${data.error_jobs.exercise}"] .operation-error-action')`);
  await run(pc,`document.querySelector('[data-inline-task="${data.error_jobs.exercise}"] .operation-error-action').click()`);await until(pc,panel);
  assert(await run(pc,"$('operationErrorDialog').textContent.includes('还没有通过检查')&&$('operationErrorDialog').textContent.includes('题目暂未发布')"));await shot(pc,'desktop-exercise-help');await run(pc,close);
  await run(pc,"libraryOpen()");await until(pc,"document.querySelector('[data-book-open]')");await run(pc,`document.querySelector('[data-book-open="${data.book_id}"]').click()`);
  await until(pc,"$('bookJobs').querySelector('.operation-error-action')");await run(pc,"$('bookJobs').querySelector('.operation-error-action').click()");await until(pc,panel);
  assert(await run(pc,"$('operationErrorDialog').textContent.includes('连接模型或资料网站时失败')&&$('operationErrorDialog').textContent.includes('还不能确定')"));await shot(pc,'desktop-library-help');await run(pc,close);
  pass('Programming-exercise and library failures have their own explanations; unchecked exercises remain unpublished and connection errors do not invent a diagnosis');
  const beforeStream=await run(pc,"api('/__error_ui__/state')");assert.deepEqual(beforeStream.jobs,original.jobs);assert.deepEqual(beforeStream.grades,original.grades);assert.equal(beforeStream.model_requests,0);
  await run(pc,"showView('study');window.errorOriginalFetch=window.fetch;window.fetch=(...args)=>String(args[0])==='/api/chat/stream'?window.errorOriginalFetch('/__error_ui__/stream',args[1]):window.errorOriginalFetch(...args);$('prompt').value='请保留这条失败后的问题草稿';$('sendMessage').click()");
  await until(pc,"!isChatBusy()&&$('prompt').value.includes('失败后的问题草稿')&&$('toast').querySelector('.operation-error-action')");
  assert(await run(pc,"![...document.querySelectorAll('.reply-status')].some(el=>!el.hidden&&el.textContent.includes('等待导师'))"));await run(pc,"window.fetch=window.errorOriginalFetch;void 0");
  await run(pc,"$('toast').querySelector('.operation-error-action').click()");await until(pc,panel);await shot(pc,'desktop-reply-failed');await run(pc,close);
  pass('A controlled streamed chat failure ends the waiting state, restores the question draft and offers help without resending the conversation');
  const phone=create(390,844,'error-phone'),ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((r,callback)=>{let ok=false;try{ok=r.hostname==='127.0.0.1'&&new X509Certificate(r.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='错误说明手机验收 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat");await run(phone,"openSheet('tasksDialog')");
  await until(phone,`$('taskList').querySelector('[data-task-id="${data.error_jobs.json}"] .operation-error-action')`);
  assert(await run(phone,`!$('taskList').querySelector('[data-task-id="${data.error_jobs.json}"]').textContent.includes('100%')`));
  await run(phone,`$('taskList').querySelector('[data-task-id="${data.error_jobs.json}"] .operation-error-action').click()`);await until(phone,panel);
  for(const width of [390,320]){phone.setSize(width,844);await sleep(100);assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth+1&&$('operationErrorDialog').scrollWidth<=$('operationErrorDialog').clientWidth+1"));await shot(phone,'phone-error-'+width);}
  await run(phone,close);await run(phone,"$('tasksDialog').close()");
  pass('The paired HTTPS phone has the same failed-task help, nested above the task sheet, readable at 390 and 320 pixels');
  await run(phone,`openSheet('optionsDialog');api('/api/providers/${data.error_provider}/models').catch(err=>toast(err.message))`);await until(phone,"$('toast').querySelector('.operation-error-action')");assert(await run(phone,"$('toast').parentElement===$('optionsDialog')"));await run(phone,"$('toast').querySelector('.operation-error-action').click()");await until(phone,panel);assert(await run(phone,"$('operationErrorTitle').textContent.includes('AI 服务暂时限制')&&$('toast').hidden"));await run(phone,close);
  await run(phone,`api('/api/providers/${data.error_provider}/models?mode=auth').catch(err=>toast(err.message))`);await until(phone,"$('toast').textContent.includes('登录或访问凭证')");
  assert(await run(phone,"mobile.authenticated&&$('pairScreen').hidden"));await run(phone,"$('toast').querySelector('.operation-error-action').click()");await until(phone,panel);assert(await run(phone,"$('operationErrorTitle').textContent==='登录或访问凭证未通过'"));await shot(phone,'phone-provider-login');await run(phone,close);
  await run(phone,`api('/api/providers/${data.error_provider}/models?mode=locked').catch(err=>toast(err.message))`);await until(phone,"$('toast').textContent.includes('提交作业后')");await run(phone,"$('toast').querySelector('.operation-error-action').click()");await until(phone,panel);assert(await run(phone,"$('operationErrorDialog').textContent.includes('先完成并提交')&&!$('operationErrorDialog').textContent.includes('浏览器读取')"));await run(phone,close);await run(phone,"$('optionsDialog').close()");
  pass('Phone errors remain inside the active options sheet so their action is usable; actual HTTP errors distinguish limits, provider login and locked answers without discarding valid pairing');
  await run(phone,"window.errorOriginalFetch=window.fetch;window.fetch=(...args)=>String(args[0]).includes('offline-fixture')?Promise.reject(new TypeError('Failed to fetch')):window.errorOriginalFetch(...args);api('/api/projects?offline-fixture=1').catch(err=>toast(err.message))");
  await until(phone,"$('toast').textContent.includes('暂时连不上电脑')");await run(phone,"window.fetch=window.errorOriginalFetch;$('toast').querySelector('.operation-error-action').click()");await until(phone,panel);assert(await run(phone,"$('operationErrorDialog').textContent.includes('电脑已开机')&&mobile.authenticated"));await run(phone,close);
  const final=await run(pc,"api('/__error_ui__/state')");assert.deepEqual(final.jobs,original.jobs);assert.deepEqual(final.book_jobs,original.book_jobs);assert.deepEqual(final.grades,original.grades);
  assert.equal(final.learning_events,original.learning_events);assert.equal(final.model_requests,0);assert.equal(final.requests.model_catalog,4);assert.equal(final.requests.stream,1);assert.equal(final.messages,original.messages);
  pass('Local connection failure is distinguished from provider failure; all help leaves original errors, failed statuses, scores and learning memory unchanged, with no model calls or automatic retries');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'flow.json'),JSON.stringify({before:original,after:final},null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_http_failures:4,controlled_stream_failures:1,external_model_requests:0,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const[i,w]of windows.entries())if(!w.isDestroyed())await shot(w,'failed-'+i);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.filter(w=>!w.isDestroyed()).forEach(w=>w.destroy());app.exit(1);}
});
