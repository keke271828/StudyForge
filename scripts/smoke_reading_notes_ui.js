/* Exercise actual source-evidence panels in desktop and paired HTTPS phone. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.resolve(__dirname,'../build',process.argv[2]);
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-reading-notes'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[];
const run=(w,c)=>w.webContents.executeJavaScript(c),wait=ms=>new Promise(r=>setTimeout(r,ms));
const q=s=>`document.querySelector(${JSON.stringify(s)})`;
const sel=row=>`[data-artifact="${row.artifact_id}"] .source-evidence`;
const texts={matched:'使用输入相同的通读笔记',legacy:'使用旧版整体笔记作导航，未确认对应本分段',unmatched:'没有匹配的通读输入，未猜配笔记'};
async function until(w,c){for(let i=0;i<250;i++){if(await run(w,c))return;await wait(100);}throw Error('UI wait: '+c);}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
function windowOf(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function verify(w,label){
 for(const row of data.reading_note_cases){
  const selector=sel(row);await until(w,q(selector));
  assert.equal(await run(w,`${q(selector)}.querySelector('.source-evidence-body')`),null);
  await run(w,`${q(selector)}.querySelector('summary').click()`);await until(w,`${q(selector)}.querySelector('.reading-note-evidence-list')`);
  const text=await run(w,`${q(selector)}.textContent`);assert(text.includes(texts[row.kind])&&text.includes('不是原文或正确性证明'));
  assert.equal(await run(w,`${q(selector)}.querySelectorAll('.reading-note-evidence-list>li').length`),1);
  assert(await run(w,'document.documentElement.scrollWidth<=innerWidth+1'));
 }
 checks.push(label+': matched / legacy / unmatched records are distinct, lazily built, and wrap without page overflow');
}
app.whenReady().then(async()=>{
 const pc=windowOf(1440,950);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation");await run(pc,"showView('artifacts')");await verify(pc,'Desktop');
  const row=data.reading_note_cases.find(r=>r.kind==='unmatched');
  await run(pc,`${q(sel(row))}.scrollIntoView({block:'center'})`);await shot(pc,'电脑通读笔记依据');
  await run(pc,'state.artifactSignature=null;refreshArtifacts()');await until(pc,`${q(sel(row))}?.open&&${q(sel(row))}.querySelector('.reading-note-evidence-list')`);
  checks.push('Desktop refresh preserves expanded source evidence');
  const phone=windowOf(390,844),ca=new X509Certificate(fs.readFileSync(data.certificate));
  phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='阅读笔记验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()),d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat");await run(phone,"$('openArtifacts').click()");await verify(phone,'Paired HTTPS phone');
  await run(phone,'refreshProject()');await until(phone,`${q(sel(row))}?.open&&${q(sel(row))}.querySelector('.reading-note-evidence-list')`);
  assert(await run(phone,`${q(sel(row))}.textContent.includes(${JSON.stringify(texts.unmatched)})`));
  checks.push('Phone refresh preserves the actual unassigned status');
  for(const width of [390,320]){phone.setSize(width,844);await wait(150);await run(phone,`${q(sel(row))}.scrollIntoView({block:'center'})`);assert(await run(phone,'document.documentElement.scrollWidth<=innerWidth+1'));await shot(phone,'手机通读笔记依据-'+width);}
  checks.push('Source panels remain readable at 390 and 320 px');
  const download=await run(phone,`fetch('/api/artifacts/${row.artifact_id}/download').then(async r=>({status:r.status,signature:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);
  assert.equal(download.status,200);assert.deepEqual(download.signature,[80,75]);checks.push('Paired phone downloads the actual generated DOCX');
  const calls=await run(pc,"fetch('/__library_test__/calls').then(r=>r.json()).then(v=>v.calls.length)");assert.equal(calls,data.model_requests);assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'reading-note-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_requests:calls,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const [i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'界面检查失败-'+i);fs.writeFileSync(path.join(folder,'reading-note-ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
