const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-quotes'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,fn,...args)=>w.webContents.executeJavaScript('('+fn.toString()+')(...'+JSON.stringify(args)+')');
async function until(w,fn,...args){for(let n=0;n<350;n++){if(await run(w,fn,...args))return;await sleep(70);}throw new Error('UI wait timed out: '+fn.toString());}
function watch(w){windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});watch(pc);
 try{
  await pc.loadURL(data.desktop_url);
  await until(pc,()=>state.ready&&state.conversation&&!conversationUI.restoring);
  await run(pc,()=>showView('artifacts'));
  await until(pc,()=>document.querySelectorAll('#artifacts .lesson-quality').length===3);
  const cards=await run(pc,()=>{
   const panels=[...document.querySelectorAll('#artifacts .lesson-quality')];
   const pick=label=>panels.find(p=>p.parentElement.textContent.includes('引文状态：'+label));
   for(const panel of panels)panel.open=true;
   return {old:pick('旧版').textContent,exact:pick('逐字').textContent,white:pick('空白').textContent,
           overflow:panels.some(p=>p.scrollWidth>p.clientWidth+2)};
  });
  assert(cards.old.includes('未区分空白差异，不能据此确认逐字一致'));
  assert(cards.exact.includes('引句片段逐字匹配 1/1'));
  assert(cards.white.includes('引句片段逐字匹配 0/1')&&cards.white.includes('仅忽略空白匹配 1 处')&&cards.white.includes('不能视为逐字确认'));
  assert(!cards.overflow);
  assert.equal((await run(pc,()=>api('/__quote_test__/state'))).requests,0);
  await shot(pc,'成果卡片引文状态');checks.push('Actual artifact cards distinguish exact fragments, whitespace-only matches and legacy unknown records without model calls');
  await run(pc,async data=>{showView('study');await selectConversation(data.conversation_id);await setSourceSelected(data.source_id,true);},data);
  await until(pc,()=>!conversationUI.restoring&&state.selected.size===1);
  await run(pc,()=>{$('prompt').value='请解释原文这句话。';void $('sendMessage').onclick();});
  await until(pc,()=>!isChatBusy()&&$('messages').textContent.includes('软件引文核对'));
  const first=await run(pc,()=>api('/__quote_test__/state'));assert.equal(first.requests,1);
  assert(await run(pc,()=>$('messages').textContent.includes('令')&&!document.querySelector('.katex-error')));
  await pc.reload();await until(pc,()=>state.ready&&!conversationUI.restoring&&$('messages').textContent.includes('软件引文核对'));
  assert.equal((await run(pc,()=>api('/__quote_test__/state'))).requests,1);
  await shot(pc,'电脑端引文核对');checks.push('Desktop tutor renders formula with local quote notice, saves and reloads it with one controlled model response');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='引文核对手机 '+Date.now();
  const pair=await run(pc,token=>api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':token}}),data.token);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);
  await until(phone,()=>$('pairScreen')&&!$('pairScreen').hidden);
  await run(phone,name=>{$('deviceName').value=name;$('pairForm').requestSubmit();},name);
  await until(pc,async(token,name)=>(await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':token}})).devices.some(d=>d.name===name&&d.status==='pending'),data.token,name);
  await run(pc,async(token,name)=>{const status=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':token}}),d=status.devices.find(d=>d.name===name);await api('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':token,'Content-Type':'application/json'},body:JSON.stringify({approved:true})});},data.token,name);
  await until(phone,()=>mobile.authenticated&&mobile.chat);
  await run(phone,id=>selectChat(id),data.conversation_id);
  await until(phone,()=>$('messages').textContent.includes('软件引文核对'));
  await run(phone,()=>{$('prompt').value='请继续核对原文引句。';send();});
  await until(phone,()=>!mobile.runs.size&&($('messages').textContent.match(/软件引文核对/g)||[]).length===2);
  assert(await run(phone,()=>document.documentElement.scrollWidth<=innerWidth&&!document.querySelector('.katex-error')));
  await shot(phone,'手机端引文核对');checks.push('Paired HTTPS mobile restores the desktop notice, sends a new request and displays the second notice at 390px');
  assert.equal((await run(pc,()=>api('/__quote_test__/state'))).requests,2);
  assert.deepEqual(errors,[]);checks.push('Two controlled responses total, no extra audit inference and no console or math rendering errors');
  fs.writeFileSync(path.join(folder,'ui-results.json'),JSON.stringify({passed:true,checks,controlled_model_requests:2,external_model_requests:0,console_errors:errors},null,2));
  for(const w of windows)w.destroy();app.exit(0);
 }catch(error){try{await shot(pc,'失败页面');}catch{}fs.writeFileSync(path.join(folder,'ui-results.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));for(const w of windows)w.destroy();app.exit(1);}
});
