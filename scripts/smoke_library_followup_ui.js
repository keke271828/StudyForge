const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-followup'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),run=(w,code)=>w.webContents.executeJavaScript(code);
async function until(w,code){for(let index=0;index<350;index++){if(await run(w,code))return;await sleep(80);}throw Error('UI wait failed: '+code);}
const pass=text=>checks.push(text);
function watch(w){w.webContents.on('console-message',event=>{if((event.level==='error'||event.level===3)&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const value=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(value.data,'base64'));}
async function select(w){await until(w,`document.querySelector('[data-followup-message="${data.target_message_id}"]')`);await run(w,`document.querySelector('[data-followup-message="${data.target_message_id}"]').click()`);
 await until(w,"document.querySelector('[data-focus-text]').value.length>0");
 await run(w,`(()=>{const area=document.querySelector('[data-focus-text]'),start=area.value.indexOf(${JSON.stringify(data.target_quote)});area.setSelectionRange(start,start+${data.target_quote.length});document.querySelector('[data-focus-select]').click();})()`);
 await until(w,"!document.querySelector('#messageFocusDialog').open&&!document.querySelector('.message-focus-banner').hidden");
}
function received(state,count){assert.equal(state.calls.length,count);const call=state.calls.at(-1);
 assert(call.messages[0].content.includes(data.original_text));assert(call.messages.at(-1).content.includes(data.target_quote));
 assert(state.history[0].receipt.sources.some(source=>source.node_id===data.node_id&&source.library_reading.id===data.reading_id));
 assert.equal(state.events,0);assert.equal(state.mastery,0);
}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:980,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');await select(pc);
  assert.equal((await run(pc,"api('/__followup_test__/state')")).calls.length,0);pass('Selecting a saved AI sentence performs no model request');
  await run(pc,"$('prompt').value='这里为什么不成立？不出题。';void $('sendMessage').onclick();true");await until(pc,"!isChatBusy()&&document.querySelector('.message-focus-history')");
  let state=await run(pc,"api('/__followup_test__/state')");received(state,1);assert.equal(state.users[0].content,'这里为什么不成立？不出题。');
  pass('Desktop sends the original question and selected AI sentence while supplying the actual PDF source through automatic library retrieval');
  await until(pc,"document.querySelector('#bookReferenceStatus .source-evidence')");await run(pc,"document.querySelector('#bookReferenceStatus .source-evidence>summary').click()");
  await until(pc,"document.querySelector('#bookReferenceStatus .source-evidence-body')");await shot(pc,'desktop-followup-reference');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'),'${data.other_conversation_id}')`);
  await until(pc,`state.conversation==='${data.other_conversation_id}'&&!state.projectLoading`);await until(pc,"!document.querySelector('#bookReferenceStatus [data-lookup-id]')");
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'))`);await until(pc,"document.querySelector('#bookReferenceStatus [data-lookup-id]')");
  await pc.reload();await until(pc,"state.ready&&state.conversation&&!conversationUI.restoring&&document.querySelector('#bookReferenceStatus [data-lookup-id]')");
  received(await run(pc,"api('/__followup_test__/state')"),1);pass('Source receipts stay in the owning conversation and restore after switching projects and reloading without another model call');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='检索追问手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(value=>value.devices.some(device=>device.status==='pending'&&device.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const value=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=value.devices.find(item=>item.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await select(phone);await run(phone,"$('prompt').value='这句为什么不对？只讲这一点，不出题。';send()");
  await until(phone,"!mobile.runs.size&&document.querySelectorAll('.message-focus-history').length===2");state=await run(pc,"api('/__followup_test__/state')");received(state,2);
  assert.equal(state.users[1].content,'这句为什么不对？只讲这一点，不出题。');pass('The paired HTTPS phone supplies the same PDF source for a short quoted follow-up, keeping the student wording unchanged');
  await run(phone,"$('openOptions').click()");await until(phone,"$('optionsDialog').open&&document.querySelector('#bookReferenceStatus .source-evidence')");
  await run(phone,"const item=document.querySelector('#bookReferenceStatus .source-evidence');if(!item.open)item.querySelector('summary').click()");
  await until(phone,"document.querySelector('#bookReferenceStatus .source-evidence-body')");
  for(const width of [390,320]){phone.setSize(width,844);await sleep(150);await run(phone,"document.querySelector('#bookReferenceStatus .source-evidence').scrollIntoView({block:'center'})");
   assert(await run(phone,"document.querySelector('#bookReferenceStatus .source-evidence').checkVisibility()&&document.documentElement.scrollWidth<=innerWidth+1"));await shot(phone,'phone-followup-reference-'+width);
  }pass('The actual phone reference panel remains visible and wraps at 390 and 320 pixels');
  await phone.reload();await until(phone,"mobile.authenticated&&mobile.chat&&document.querySelectorAll('.message-focus-history').length===2");received(await run(pc,"api('/__followup_test__/state')"),2);
  pass('Full phone reload keeps both sent passage references without repeated retrieval/model requests');
  const count=data.auto_context_check?await require('./smoke_library_auto_context_ui')({pc,phone,run,until,shot,data,assert,pass}):2;
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_model_requests:count,external_model_requests:0,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const[index,w]of windows.entries())if(w.webContents.getURL())await shot(w,'failed-'+index);fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
