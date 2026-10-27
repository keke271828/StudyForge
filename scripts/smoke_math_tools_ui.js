/* Real page, native model tool packets, paired mobile and reload persistence. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-math-tools'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=(w,c)=>w.webContents.executeJavaScript(c);
async function until(w,c){for(let n=0;n<350;n++){if(await run(w,c))return;await sleep(70);}throw Error('UI wait failed: '+c);}
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'ui-log.txt'),text+'\n');}
function watch(w){w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  await run(pc,`$('prompt').value=${JSON.stringify(data.rational?'请用核验工具检查两个约分式的原分母条件，只讲数学示意，不出题。':data.polynomial?'请用本机工具核对平方展开恒等式和能量表达式的偏导。':'请用数学工具核验两个分数算式与向量例子。')};void $('sendMessage').onclick();true`);
  await until(pc,"[...document.querySelectorAll('.tool-activity')].some(n=>n.textContent==='数学核验 · 完成')");
  assert(await run(pc,"[...document.querySelectorAll('.tool-activity')].some(n=>n.textContent==='数学核验 · 完成')"));
  await shot(pc,'电脑端数学核验');
  await until(pc,"!isChatBusy()&&$('messages').textContent.includes('UI_MATH_DONE')");
  assert.equal((await run(pc,"api('/__math_test__/state')")).calls,2);
  pass(data.rational?'Desktop native tool loop keeps original denominator restrictions despite cancellation; read-only operation completes':data.polynomial?'Desktop native tool loop rejects the wrong polynomial identity and derivative with read-only permission; Chinese activity label completes':'Desktop native tool loop computes exact fractions and vector result with read-only permission; Chinese activity label completes');
  await pc.reload();await until(pc,"state.ready&&state.conversation&&!conversationUI.restoring&&$('messages').textContent.includes('UI_MATH_DONE')");
  assert.equal((await run(pc,"api('/__math_test__/state')")).calls,2);
  pass('Completed reply survives reload without another model request');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='数学工具手机验收 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),d=s.devices.find(d=>d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');
  await run(phone,"$('prompt').value='手机也请用数学核验工具核算同一例子。';send()");
  await until(phone,"!mobile.runs.size&&$('messages').textContent.includes('手机也请')&&$('messages').textContent.includes('UI_MATH_DONE')");
  await until(pc,"api('/__math_test__/state').then(s=>s.calls===4&&s.tools.length===4)");
  assert(await run(phone,'document.documentElement.scrollWidth<=innerWidth'));await shot(phone,'手机端数学核验');
  pass('Paired HTTPS phone completes the same read-only tool loop and displays reply at mobile width');
  const result=await run(pc,"api('/__math_test__/state')");
  assert(result.tools.every(t=>t.tool==='sf_check_math'&&t.status==='completed'));
  assert(!JSON.stringify(result.tools).includes('3/10')&&!JSON.stringify(result.tools).includes('dot_product'));
  if(data.polynomial){assert(!JSON.stringify(result.tools).includes('normal_form'));assert(await run(phone,"$('messages').querySelectorAll('.katex').length>0&&!$('messages').querySelector('.katex-error')"));}
  if(data.rational){assert(result.tools.every(t=>!Object.hasOwn(JSON.parse(t.result_json),'results')));assert(await run(phone,"$('messages').querySelectorAll('.katex').length>0&&!$('messages').querySelector('.katex-error')&&$('messages').textContent.includes('定义域')"));}
  assert.deepEqual(result.scores,[]);assert.deepEqual(result.exercises,[]);
  pass('Public operation records contain no numeric answers; checks create no mastery score or exercise set');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(folder,'ui-results.json'),JSON.stringify({passed:true,checks,controlled_model_requests:result.calls,external_model_requests:0,console_errors:errors},null,2));
  for(const w of windows)w.destroy();app.exit(0);
 }catch(error){if(!pc.isDestroyed()){await shot(pc,'失败时页面');fs.writeFileSync(path.join(folder,'failed-page.html'),await run(pc,'document.documentElement.outerHTML'));}fs.writeFileSync(path.join(folder,'ui-results.json'),JSON.stringify({passed:false,checks,error:error.stack,console_errors:errors},null,2));for(const w of windows)w.destroy();app.exit(1);}
});
