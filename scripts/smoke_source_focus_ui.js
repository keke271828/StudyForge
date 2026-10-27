const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-source-focus'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let i=0;i<350;i++){if(await run(w,code))return;await sleep(80);}throw Error('UI wait failed: '+code);}
const pass=text=>checks.push(text);
function watch(w){w.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const value=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(value.data,'base64'));}
function received(state,count){assert.equal(state.calls.length,count);assert.equal(state.receipts.length,count);
 const system=state.calls.at(-1).messages[0].content;assert(data.targets.every(target=>system.includes(target)));
 assert(system.includes('相关原文片段，不是全文'));assert(state.receipts.at(-1).included.every(item=>item.source_id===data.source_id));
 assert(state.receipts.at(-1).context_characters<16000);assert.equal(state.mastery,0);assert.equal(state.events,0);
}
app.whenReady().then(async()=>{
 const options={sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true};
 const pc=new BrowserWindow({show:false,width:1440,height:980,webPreferences:options});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  assert(await run(pc,`state.selected.has('${data.source_id}')`));
  assert.equal((await run(pc,"api('/__source_focus_test__/state')")).calls.length,0);pass('Opening a saved long-source chat restores selection without another model reading');
  await run(pc,`$('prompt').value=${JSON.stringify(data.question)};void $('sendMessage').onclick();true`);
  await until(pc,"!isChatBusy()&&$('messages').textContent.includes('非零和可逆的区别')");
  let state=await run(pc,"api('/__source_focus_test__/state')");received(state,1);assert.equal(state.users[0].content,data.question);
  assert(await run(pc,"$('messages').querySelectorAll('.katex').length>=4"));await shot(pc,'desktop-source-focus');
  pass('Actual desktop send supplies tail definitions, examples and conditions, with rendered formulas and one controlled model request');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'),'${data.other_conversation_id}')`);
  await until(pc,`state.conversation==='${data.other_conversation_id}'&&!state.projectLoading`);
  assert(!(await run(pc,"$('messages').textContent.includes('非零和可逆的区别')")));
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'),'${data.conversation_id}')`);
  await until(pc,"!state.projectLoading&&$('messages').textContent.includes('非零和可逆的区别')");
  await pc.reload();await until(pc,"state.ready&&!conversationUI.restoring&&$('messages').textContent.includes('非零和可逆的区别')");
  received(await run(pc,"api('/__source_focus_test__/state')"),1);pass('Switching projects and reloading preserves the owning conversation and does not repeat AI work');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:options});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='长资料定位手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(value=>value.devices.some(device=>device.status==='pending'&&device.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const value=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=value.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');assert(await run(phone,`mobile.selected.has('${data.source_id}')`));
  await run(phone,"$('prompt').value='请只据教材讲清商环中非零陪集[2]为什么不可逆，不出题。';send()");
  await until(phone,"!mobile.runs.size&&$('messages').querySelectorAll('.katex').length>=8");
  state=await run(pc,"api('/__source_focus_test__/state')");received(state,2);
  assert.equal(state.users[1].content,'请只据教材讲清商环中非零陪集[2]为什么不可逆，不出题。');
  pass('A paired HTTPS phone continues the same long-source chat using its saved reading record without needing another pre-read');
  for(const width of [390,320]){phone.setSize(width,844);await sleep(120);
   assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth+1"));await shot(phone,'phone-source-focus-'+width);
  }pass('The actual phone answer renders formulas at 390 and 320 pixels without page overflow');
  await phone.reload();await until(phone,"mobile.authenticated&&$('messages').querySelectorAll('.katex').length>=8");
  received(await run(pc,"api('/__source_focus_test__/state')"),2);pass('Phone reload retains replies and causes no extra model calls or learner-score events');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_model_requests:2,external_model_requests:0,console_errors:errors},null,2));
  fs.writeFileSync(path.join(folder,'input-receipts.json'),JSON.stringify(state.receipts,null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const[i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+i);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
