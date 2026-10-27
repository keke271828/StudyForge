const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/teaching-review-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const wait=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
 const errors=[],requests=[];
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest((r,cb)=>{if(/^https?:/.test(r.url))requests.push(r.url);cb({cancel:false});});
 const run=c=>w.webContents.executeJavaScript(c),until=async c=>{for(let i=0;i<100;i++){if(await run(c))return;await wait(50);}throw Error(c);};
 async function shot(name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
 try{
  await w.loadFile(path.join(folder,'教学核查记录与阅读验收.html'));
  await until('window.reportReady&&document.querySelectorAll(".teaching-review-body").length===4');
  assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
  assert.equal(await run('document.querySelectorAll(".teaching-review-issue").length'),3);
  assert(await run('document.body.textContent.includes("本轮未列出疑点，仍可能漏检")'));
  await run('document.querySelectorAll(".teaching-review-edits>summary").forEach(s=>s.click())');
  await until('document.querySelectorAll(".teaching-review-edit").length===4');
  const links=await run('[...document.querySelectorAll("a[href]")].map(a=>a.href)');
  for(const href of links){const u=new URL(href);assert.equal(u.protocol,'file:');assert(fs.existsSync(fileURLToPath(u)),href);}
  await shot('教学核查验收页-电脑');
  for(const width of [390,320]){w.setSize(width,900);await wait(100);assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('教学核查验收页-'+width);}
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,saved_real_reviews:4,visible_issues:3,expanded_replacement_proposals:4,local_links:links.length,widths:[1400,390,320],horizontal_overflow:false,console_errors:errors,network_requests:requests},null,2));
  w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));w.destroy();app.exit(1);}
});
