/* Actual app panels, paired phone, paging, safe text and refresh recovery. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.resolve(__dirname,'../build',process.argv[2]);
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-teaching-review'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[];
const run=(w,c)=>w.webContents.executeJavaScript(c),wait=ms=>new Promise(r=>setTimeout(r,ms));
const q=s=>`document.querySelector(${JSON.stringify(s)})`;
const sel=row=>`[data-artifact="${row.artifact_id}"] .teaching-review`;
async function until(w,c){for(let i=0;i<250;i++){if(await run(w,c))return;await wait(100);}throw Error('UI wait: '+c);}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
function windowOf(width,height){const w=new BrowserWindow({show:false,width,height,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(w);w.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});return w;}
async function verify(w,label){
 for(const row of data.teaching_review_cases){
  const s=sel(row);await until(w,q(s));
  assert.equal(await run(w,`${q(s)}.querySelector('.teaching-review-body')`),null);
  await run(w,`${q(s)}.querySelector('summary').click()`);await until(w,`${q(s)}.querySelector('.teaching-review-body')`);
  const text=await run(w,`${q(s)}.textContent`);
  assert(text.includes('不是正确性认证')&&text.includes('不会请求模型、出题或写入学习画像'));
  if(row.mode==='fast'){
   assert(text.includes('局部修订 · 未再次独立复核')&&text.includes('需对照实际页码核对来源'));
   assert.equal(await run(w,`${q(s)}.querySelectorAll('.teaching-review-issue').length`),2);
   assert.equal(await run(w,`${q(s)}.querySelector('.teaching-review-edit')`),null);
   await run(w,`${q(s)}.querySelector('.teaching-review-edits>summary').click()`);await until(w,`${q(s)}.querySelector('.teaching-review-edit')`);
   assert(await run(w,`${q(s)}.textContent.includes('也可以取更大的N')`));
   assert(await run(w,`${q(s)}.textContent.includes('本机保存了 1 处应用定位记录')`));
  }else assert(text.includes('未执行独立模型审查'));
  assert(await run(w,'document.documentElement.scrollWidth<=innerWidth+1'));
 }
 checks.push(label+': native fast / express records, applied and unresolved issues, lazy replacements, no page overflow');
}
app.whenReady().then(async()=>{
 const pc=windowOf(1440,1000),fast=data.teaching_review_cases.find(r=>r.mode==='fast');
 try{
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation');await run(pc,"showView('artifacts')");await verify(pc,'Desktop');
  await run(pc,`${q(sel(fast))}.scrollIntoView({block:'center'})`);await shot(pc,'电脑教学核查记录');
  await run(pc,`${q(sel(fast))}.querySelector('.teaching-review-body').scrollTop=90`);await wait(100);
  await run(pc,'state.artifactSignature=null;refreshArtifacts()');await until(pc,`${q(sel(fast))}?.open&&${q(sel(fast))}.querySelector('.teaching-review-body')`);
  assert(await run(pc,`${q(sel(fast))}.querySelector('.teaching-review-body').scrollTop>0`));checks.push('Desktop refresh retains open panel and internal reading position');
  // Stress the real shared component separately; fixture data is not an AI quality result.
  const isolated=windowOf(390,844);await isolated.loadURL('about:blank');
  await run(isolated,`document.head.append(Object.assign(document.createElement('style'),{textContent:${JSON.stringify(fs.readFileSync(path.join(__dirname,'../web/teaching_review.css'),'utf8'))}}));document.body.style.margin='10px'`);
  await run(isolated,fs.readFileSync(path.join(__dirname,'../web/teaching_review.js'),'utf8'));
  await run(isolated,`window.fixtureReports=[{stage:'历史核查',attempt:1,section:2,passed:false,issues:Array.from({length:53},(_,i)=>({location:'位置'+i,problem:'疑点'+i,evidence:i===0?'<img src=x onerror="window.unsafe=true">'+ '依据'.repeat(1800):'请回查'}))},{stage:'修订后复核',attempt:2,passed:true,issues:[]}];document.body.append(studyforgeTeachingReview.create({reviews:fixtureReports},'stress','explanation'))`);
  assert.equal(await run(isolated,"document.querySelectorAll('.teaching-review-issue').length"),0);
  await run(isolated,"document.querySelector('summary').click()");await until(isolated,"document.querySelector('.teaching-review-issue')");
  assert.equal(await run(isolated,"document.querySelectorAll('.teaching-review-issue').length"),5);
  assert.equal(await run(isolated,"document.querySelector('img,script,a')"),null);
  assert(!await run(isolated,'Boolean(window.unsafe)'));
  const pages='input[aria-label="跳转到第几页疑点"]';
  await run(isolated,`${q(pages)}.value='11';${q(pages)}.dispatchEvent(new Event('change'))`);
  assert(await run(isolated,"document.querySelector('.teaching-review-issues').textContent.includes('疑点52')"));
  assert.equal(await run(isolated,"document.querySelectorAll('.teaching-review-issue').length"),3);
  const reports='input[aria-label="跳转到第几项记录"]';
  await run(isolated,`${q(reports)}.value='2';${q(reports)}.dispatchEvent(new Event('change'))`);
  assert(await run(isolated,"document.querySelector('.teaching-review-body').textContent.includes('本轮未列出疑点，仍可能漏检')"));
  await run(isolated,`${q(reports)}.value='0';${q(reports)}.dispatchEvent(new Event('change'))`);
  assert.equal(await run(isolated,`${q(reports)}.value`),'2');
  await run(isolated,`${q(reports)}.value='1';${q(reports)}.dispatchEvent(new Event('change'))`);
  assert(await run(isolated,"document.querySelector('.teaching-review-body').textContent.includes('疑点0')"));
  assert.equal(await run(isolated,"studyforgeTeachingReview.create({reviews:[{result:{solution:'PRIVATE_SOLUTION'}}]},'private','exercises')"),null);
  assert(!await run(isolated,"document.body.textContent.includes('PRIVATE_SOLUTION')"));
  checks.push('53 synthetic issues page to the last item; report switching never marks old issues resolved; invalid jumps, XSS and private-exercise exclusion checked');
  await run(isolated,"document.querySelector('.teaching-review-text details>summary').click()");await until(isolated,"document.querySelector('.teaching-review-text pre')");
  assert(await run(isolated,"document.querySelector('.teaching-review-text pre').textContent.length>3500"));
  assert(await run(isolated,'document.documentElement.scrollWidth<=innerWidth+1'));checks.push('Long evidence is expandable as literal text and remains within phone width');
  const phone=windowOf(390,844),ca=new X509Certificate(fs.readFileSync(data.certificate));
  phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='核查验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()),d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,"$('openArtifacts').click()");await verify(phone,'Paired HTTPS phone');
  for(const width of [390,320]){phone.setSize(width,844);await wait(150);await run(phone,`${q(sel(fast))}.scrollIntoView({block:'center'})`);assert(await run(phone,'document.documentElement.scrollWidth<=innerWidth+1'));await shot(phone,'手机教学核查记录-'+width);}
  await run(phone,"document.documentElement.dataset.theme='dark'");
  const colors=await run(phone,`({background:getComputedStyle(${q(sel(fast))}).backgroundColor,foreground:getComputedStyle(${q(sel(fast))}).color,panel:getComputedStyle(document.documentElement).getPropertyValue('--panel')})`);
  assert.equal(colors.background,'rgb(32, 46, 42)');assert.equal(colors.foreground,'rgb(228, 237, 231)');await shot(phone,'手机深色教学核查记录');
  await run(phone,'refreshProject()');await until(phone,`${q(sel(fast))}?.open`);checks.push('Paired phone retains expanded panels after refresh; 390/320 px and actual dark-theme foreground/background checked');
  const download=await run(phone,`fetch('/api/artifacts/${fast.artifact_id}/download').then(async r=>({status:r.status,signature:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);
  assert.equal(download.status,200);assert.deepEqual(download.signature,[80,75]);
  const calls=await run(pc,"fetch('/__library_test__/calls').then(r=>r.json()).then(v=>v.calls.length)");assert.equal(calls,3);
  checks.push('Actual DOCX downloadable; browsing all records adds zero model requests');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'teaching-review-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,controlled_requests:calls,external_model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){for(const [i,w]of windows.entries())if(w.webContents.getURL())await shot(w,'界面检查失败-'+i);fs.writeFileSync(path.join(folder,'teaching-review-ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
