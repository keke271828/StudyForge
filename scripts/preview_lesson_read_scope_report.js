const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/lesson-read-scope-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const wait=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}}),errors=[],requests=[];
 window.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 window.webContents.session.webRequest.onBeforeRequest((r,cb)=>{if(/^https?:/.test(r.url))requests.push(r.url);cb({cancel:false});});
 const run=c=>window.webContents.executeJavaScript(c);
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const r=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
 try{
  await window.loadFile(path.join(folder,'原文读取范围与讲解核对验收.html'));
  assert.equal(await run('document.querySelectorAll("article.answer").length'),4);
  assert.equal(await run('document.querySelectorAll(".badge.bad").length'),1);
  assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
  const formulas=await run('document.querySelectorAll(".katex").length');assert(formulas>0);
  assert(await run(`data.samples.every(row=>[...document.querySelectorAll('.raw-answer pre:first-of-type')].some(el=>el.textContent===row.text))`));
  assert(await run('document.querySelector(".bad").closest("article").querySelector(".model-answer").textContent.includes("<｜｜DSML｜｜ calls>")'));
  for(let i=0;i<100;i++){if(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'))break;await wait(50);}
  assert(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'));
  const links=await run('[...document.querySelectorAll("a[href]")].map(a=>a.href)');
  for(const href of links){const url=new URL(href);assert.equal(url.protocol,'file:');assert(fs.existsSync(fileURLToPath(url)),href);}
  for(const width of [1400,390,320]){
   window.setSize(width,1000);await wait(100);await run('scrollTo(0,0)');
   assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('原文核对验收页-'+width);
   await run('document.querySelector(".case-group").scrollIntoView()');await wait(100);await shot('真实数学回答-'+width);
  }
  await run('document.querySelectorAll("details").forEach(el=>el.open=true)');
  assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,raw_replies:4,failed_printed_tool_replies:1,math_formulas:formulas,local_links:links.length,images:2,widths:[1400,390,320],horizontal_overflow:false,console_errors:errors,network_requests:requests},null,2));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));window.destroy();app.exit(1);}
});
