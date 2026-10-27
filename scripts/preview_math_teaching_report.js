/* Exercise all report groups, real math rendering, links and mobile layout. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL,fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build',process.argv[2]||'math-teaching-acceptance-20261016'),errors=[],network=[];
const reportName=process.argv[3]||'首次讲解与数学核验实际对照.html';
const manifest=JSON.parse(fs.readFileSync(path.join(folder,'manifest.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1450,height:1050,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
 const run=c=>w.webContents.executeJavaScript(c);
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,done)=>{network.push(req.url);done({cancel:true});});
 async function shot(name){await run('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))');await run('document.fonts.ready');if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const p=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
 try{
  await w.loadURL(pathToFileURL(path.join(folder,reportName)).href);await run('document.fonts.ready');
  assert.equal(await run('comparison.count'),manifest.answers);assert.equal(await run('groupSelect.options.length'),manifest.groups);
  if(manifest.actual_remediation){
   assert(await run('document.querySelectorAll("#actualRemediation .katex").length>5'));
   assert.equal(await run('document.querySelectorAll("#actualRemediation .katex-error").length'),0);
   await run('document.getElementById("actualRemediation").closest("details").open=true;document.getElementById("actualRemediation").scrollIntoView()');await shot('实际错因补讲预览');
  }
  assert.deepEqual(await run('[...document.querySelectorAll(".report-table table tbody")].map(t=>t.rows.length)'),manifest.report_table_rows||[4,4]);
  for(const href of await run('[...document.querySelectorAll("a")].map(a=>a.href)'))assert(fs.existsSync(fileURLToPath(href)),href);
  if(manifest.source_identity_preview){
   assert.equal(await run('document.querySelector("#sourceIdentityPreview .source-evidence-body")'),null);
   await run('document.querySelector("#sourceIdentityPreview .source-evidence > summary").click();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
   const t=await run('document.querySelector("#sourceIdentityPreview .source-evidence-body").textContent');
   assert(t.includes('本软件 AI 成果')&&t.includes('导入资料')&&t.includes('未认证作者或内容正确性')&&!t.includes('条原文记录'));
  }
  await run('revealButton.click()');
  for(let i=0;i<manifest.groups;i++){
   await run(`groupSelect.value=${i};groupSelect.onchange();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
   assert.equal(await run('document.querySelectorAll("#answers .answer").length'),2);
   assert(await run('[...document.querySelectorAll("#answers .answer-body")].every(n=>n.textContent.length>60)'));
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
   assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  }
  await run('groupSelect.value=1;groupSelect.onchange();document.querySelector(".controls").scrollIntoView()');await shot('讲解对照页面预览');
  w.setSize(390,844);await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  if(manifest.actual_remediation){await run('document.getElementById("actualRemediation").scrollIntoView()');await shot('手机错因补讲预览');}
  for(let i=0;i<manifest.groups;i++){
   await run(`groupSelect.value=${i};groupSelect.onchange();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
   assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  }
  await run('document.querySelector(".controls").scrollIntoView()');await shot('手机宽度页面预览');
  assert(!network.length&&!errors.length,JSON.stringify({network,errors}));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,groups:manifest.groups,answers:manifest.answers,rendered_each_group:true,
    local_links_exist:true,math_errors:0,desktop_and_phone_no_horizontal_page_overflow:true,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(0);
 }catch(error){let layout;try{layout=await run('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll("body *")].filter(n=>n.getBoundingClientRect().right>innerWidth).slice(0,15).map(n=>({tag:n.tagName,id:n.id,classes:n.className?.baseVal||n.className,right:n.getBoundingClientRect().right}))})');await shot('检查失败页面');}catch{}
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,layout,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(1);}
});
