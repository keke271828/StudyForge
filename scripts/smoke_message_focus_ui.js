/* Actual page and paired mobile passage selection; model transport controlled. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-focus'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<350;n++){if(await run(w,c))return;await sleep(70);}throw Error('UI wait failed: '+c);}
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'ui-log.txt'),text+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,`selectConversation('${data.conversation_id}')`);await until(pc,`state.conversation==='${data.conversation_id}'&&!conversationUI.restoring`);
  await run(pc,`document.querySelector('[data-followup-message="${data.target_message_id}"]').click()`);
  await until(pc,"document.querySelector('#messageFocusDialog textarea').value.length>0");
  assert.equal((await run(pc,"api('/__focus_test__/state')")).calls.length,0);
  await run(pc,"document.querySelector('[data-focus-offset]').value=5800;document.querySelector('[data-focus-jump]').click()");
  await until(pc,`document.querySelector('#messageFocusDialog textarea').value.includes('🔎')`);
  await run(pc,`(()=>{document.querySelector('[data-focus-source]').click();const a=document.querySelector('[data-focus-text]'),start=a.value.indexOf('🔎'),end=a.value.indexOf('特例。',start)+'特例。'.length;a.setSelectionRange(start,end);document.querySelector('[data-focus-select]').click();})()`);
  await until(pc,"!document.querySelector('#messageFocusDialog').open&&!document.querySelector('.message-focus-banner').hidden");
  const ref=await run(pc,`studyforgeMessageFocus.capture('${data.project_id}','${data.conversation_id}')`);
  assert.equal(ref.selection.text,data.target_quote);
  assert.equal((await run(pc,"api('/__focus_test__/state')")).calls.length,0);
  pass('Select late Unicode/CRLF passage from a long saved answer without model call or whole-book parsing');
  await run(pc,`selectConversation('${data.same_project_other_chat}')`);await until(pc,`state.conversation==='${data.same_project_other_chat}'&&!conversationUI.restoring`);
  assert(await run(pc,"document.querySelector('.message-focus-banner').hidden"));
  await run(pc,`selectConversation('${data.conversation_id}')`);await until(pc,`state.conversation==='${data.conversation_id}'&&!conversationUI.restoring`);
  assert(!(await run(pc,"document.querySelector('.message-focus-banner').hidden")));
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring&&!document.querySelector(".message-focus-banner").hidden');
  assert.deepEqual(await run(pc,`studyforgeMessageFocus.capture('${data.project_id}','${data.conversation_id}')`),ref);
  pass('Reference draft stays isolated by chat and survives switching and full reload');
  await run(pc,"$('prompt').value='只解释我选中的这一步为什么成立。';void $('sendMessage').onclick();true");
  await until(pc,"!isChatBusy()&&document.querySelector('.message-focus-history')");
  const first=await run(pc,"api('/__focus_test__/state')");assert.equal(first.calls.length,1);assert.equal(first.references.length,1);
  assert(first.calls[0].messages.at(-1).content.includes(data.target_quote));assert.equal(first.users[0].content,'只解释我选中的这一步为什么成立。');
  assert.equal(first.calls[0].messages.at(-1).content.split(data.target_quote).length-1,1);
  assert(first.calls[0].messages.at(-1).content.includes('【学生选中的旧AI原句开始，不是学生作答】'));
  assert(first.calls[0].messages.at(-1).content.endsWith('【学生自己的本条问题】\n只解释我选中的这一步为什么成立。'));
  assert(!first.calls[0].messages.at(-1).content.includes('【本次教学要求'));
  assert(first.calls[0].messages[0].content.includes('当前学习模式：精学'));
  assert(first.calls[0].messages[0].content.includes('当前讲解风格：'));
  assert(await run(pc,"document.querySelector('.message-focus-banner').hidden"));
  await pc.reload();await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring&&document.querySelector(".message-focus-history")');
  assert.equal((await run(pc,"api('/__focus_test__/state')")).calls.length,1);await shot(pc,'电脑端原句追问');
  pass('Sent reference reaches actual chat loop, keeps student text verbatim, and displays after reload with no repeated request');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='原句追问手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,`selectChat('${data.conversation_id}')`);
  await until(phone,`document.querySelector('[data-followup-message="${data.short_message_id}"]')`);
  await run(phone,`document.querySelector('[data-followup-message="${data.short_message_id}"]').click()`);await until(phone,"document.querySelector('[data-focus-text]').value.includes('偏导')");
  assert(await run(phone,'document.documentElement.scrollWidth<=innerWidth'));await shot(phone,'手机端原句选择');
  await run(phone,"document.querySelector('[data-focus-whole]').click();$('prompt').value='我针对这条回答追问，二者区别在哪里？';send()");
  await until(phone,"!mobile.runs.size&&document.querySelectorAll('.message-focus-history').length===2");
  const second=await run(pc,"api('/__focus_test__/state')");assert.equal(second.calls.length,2);assert.equal(second.references.length,2);
  assert(second.calls[1].messages.at(-1).content.includes('偏导和沿轨迹的时间导数不同'));assert(await run(phone,'document.documentElement.scrollWidth<=innerWidth'));await shot(phone,'手机端原句追问');
  pass('Paired HTTPS mobile opens passage dialog, sends whole short-answer reference, and preserves readable history at 390px');
  assert(second.calls[1].messages.at(-1).content.endsWith('【学生自己的本条问题】\n我针对这条回答追问，二者区别在哪里？'));
  assert(!second.calls[1].messages.at(-1).content.includes('【本次教学要求'));
  assert(second.calls[1].messages[0].content.includes('当前学习模式：精学'));
  pass('Desktop and phone send original questions without redundant teaching tails, retaining full system mode and style');
  assert.deepEqual(second.scores,[]);assert.deepEqual(second.insights,[]);assert.deepEqual(errors,[]);
  pass('Quotation alone creates neither mastery scores nor learner insights; no console errors');
  fs.writeFileSync(path.join(folder,'ui-results.json'),JSON.stringify({passed:true,checks,controlled_model_requests:second.calls.length,external_model_requests:0,console_errors:errors},null,2));
  for(const w of windows)w.destroy();app.exit(0);
 }catch(error){if(!pc.isDestroyed()){await shot(pc,'失败时页面');fs.writeFileSync(path.join(folder,'failed-page.html'),await run(pc,'document.documentElement.outerHTML'));}fs.writeFileSync(path.join(folder,'ui-results.json'),JSON.stringify({passed:false,checks,error:error.stack,console_errors:errors},null,2));for(const w of windows)w.destroy();app.exit(1);}
});
