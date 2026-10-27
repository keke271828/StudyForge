/* Native tool receipts in the desktop and a genuinely paired HTTPS phone. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-tool-receipt'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=(w,code)=>w.webContents.executeJavaScript(code);
const select=label=>`#bookReferenceStatus [data-lookup-id="${data.tool_cases.find(c=>c.label===label).lookup_id}"]`;
const legacy=`#bookReferenceStatus [data-lookup-id="${data.legacy_lookup_id}"]`;
const query=selector=>`document.querySelector(${JSON.stringify(selector)})`;
const pass=message=>{checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');};
async function until(w,code){for(let i=0;i<350;i++){if(await run(w,code))return;await sleep(100);}throw Error('UI wait failed: '+code);}
function watch(w){w.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const result=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));}
async function open(w,label){const selector=select(label);await until(w,query(selector));
 await run(w,`if(!${query(selector)}.open)${query(selector)}.querySelector('summary').click()`);
 await until(w,query(selector+' .source-evidence'));
 await run(w,`if(!${query(selector+' .source-evidence')}.open)${query(selector+' .source-evidence')}.querySelector('summary').click()`);
 await until(w,query(selector+' .source-evidence-body'));return run(w,`${query(selector)}.textContent`);
}
async function verify(w){
 const body=await open(w,'partial'),item=data.tool_cases.find(c=>c.label==='partial');
 assert(body.includes('saved-tool-reader')&&!body.includes('later-tool-reader'));
 assert(body.includes(data.old_reading_id.slice(0,8))&&!body.includes(data.new_reading_id.slice(0,8)));
 assert(body.includes('PDF 第 1–2 页')&&body.includes('50%')&&!body.includes('60%'));
 assert(body.includes('第 6–105 字符')&&body.includes('拼接文字偏移 65')&&body.includes('继续位置：165'));
 assert(body.includes('结构索引')&&body.includes('原页回查记录')&&body.includes('历史范围已变化'));
 assert(body.includes(item.receipt.context_sha256.slice(0,12))&&body.includes('实际提供：PDF 第 2 页'));
 assert(!body.includes('实际提供：PDF 第 1 页')&&!body.includes('后来改名'));
 assert.equal(await run(w,`${query(select('partial'))}.querySelectorAll('img').length`),0);
 assert(!(await run(w,'window.toolInjected')));
 const visual=await open(w,'visual');assert(visual.includes('原页提取／OCR：本次未提供文字')&&visual.includes('AI 图像核对记录（不是原文引语）：第 1–66 字符'));
 const empty=await open(w,'empty');assert(empty.includes('本次未提供：')&&!empty.includes('已回查：')&&empty.includes('不能算作读过正文'));
 const all=await open(w,'all');assert(all.includes('实际提供：PDF 第 1 页')&&all.includes('实际提供：PDF 第 2 页')&&!all.includes('继续位置：'));
 await run(w,`if(!${query(legacy)}.open)${query(legacy)}.querySelector('summary').click()`);
 await until(w,`${query(legacy)}.textContent.includes('旧回查记录未保存实际阅读版本及字符范围')`);
 assert.equal(await run(w,query(legacy+' .source-evidence')),null);
}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation");await until(pc,query(select('partial')));
  assert.equal(await run(pc,"document.querySelectorAll('.source-evidence-body').length"),0);
  pass('Saved native-tool history restores at launch; source detail bodies are created only when expanded');
  await verify(pc);pass('Desktop distinguishes exact original and AI-only spans, no-body reads and legacy records, keeping the frozen version despite a later reading and directory edit');
  await run(pc,`${query(select('partial'))}.scrollIntoView({block:'center'})`);await sleep(200);await shot(pc,'desktop-tool-source');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'),'${data.other_conversation_id}')`);
  await until(pc,`state.conversation==='${data.other_conversation_id}'&&!state.projectLoading`);await until(pc,`!${query(select('partial'))}`);
  pass('Another project and conversation cannot see these page-read records');
  await run(pc,`selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'))`);await until(pc,query(select('partial')));await verify(pc);
  pass('Returning to the owning conversation restores all saved receipt versions and spans');
  await pc.reload();await until(pc,"state.ready&&state.conversation");await verify(pc);pass('A full desktop reload preserves the saved records without re-reading any source');
  await open(pc,'all');const source=select('all')+' .source-evidence';
  await run(pc,`${query(source)}.scrollIntoView({block:'center'})`);await sleep(150);
  const box=await run(pc,`(()=>{const el=${query(source+' .source-evidence-body')},r=el.getBoundingClientRect();return{x:r.left+20,y:Math.max(10,r.top)+30,overflow:el.scrollHeight>el.clientHeight};})()`);
  assert(box.overflow);if(!pc.webContents.debugger.isAttached())pc.webContents.debugger.attach('1.3');
  await pc.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseWheel',x:box.x,y:box.y,deltaX:0,deltaY:220});
  await until(pc,`${query(source+' .source-evidence-body')}.scrollTop>0`);pass('A real wheel event scrolls the long source-detail panel');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='原页回查验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()),device=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat");await run(phone,"$('openOptions').click()");await until(phone,"$('optionsDialog').open");await verify(phone);pass('A genuinely paired HTTPS phone shows the identical frozen version, page spans, omitted bodies and legacy limits');
  for(const width of [390,320]){phone.setSize(width,844);await sleep(150);await open(phone,'partial');await run(phone,`${query(select('partial'))}.scrollIntoView({block:'center'})`);
   assert(await run(phone,`${query(select('partial'))}.checkVisibility()&&${query(select('partial'))}.scrollWidth<=${query(select('partial'))}.clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1&&${query(select('partial')+' .source-evidence-body')}.clientWidth>=160`));
   await shot(phone,'phone-tool-source-'+width);
  }pass('Source details wrap without horizontal overflow at 390 and 320 pixels');
  await phone.reload();await until(phone,"mobile.authenticated&&mobile.chat");await run(phone,"$('openOptions').click()");await until(phone,"$('optionsDialog').open");await verify(phone);pass('The paired phone restores the same saved records after a full reload');
  const state=await run(pc,"fetch('/__tool_receipt_test__/state').then(r=>r.json())");
  assert.deepEqual(state,{model_requests:0,events:0,mastery:0,jobs:0,exercise_sets:0});assert(!errors.length,JSON.stringify(errors));
  pass('Opening, restoring and inspecting receipts triggers no model request, learning event, mastery update, document job or exercise');
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,state,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,console_errors:errors},null,2));for(const [i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'tool-failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
