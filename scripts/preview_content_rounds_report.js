const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/content-rounds-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const wait=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}}),errors=[],requests=[];
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest((r,cb)=>{if(/^https?:/.test(r.url))requests.push(r.url);cb({cancel:false});});
 const run=c=>w.webContents.executeJavaScript(c);
 async function shot(name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
 try{
  await w.loadFile(path.join(folder,'讲解新疑问与连续核对验收.html'));
  assert.equal(await run('document.querySelectorAll("article.panel").length'),2);
  await run('document.querySelectorAll("summary").forEach(s=>s.click());document.querySelectorAll("img").forEach(i=>i.loading="eager")');
  for(let i=0;i<100;i++){if(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'))break;await wait(50);}
  assert(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'));
  const links=await run('[...document.querySelectorAll("a[href]")].map(a=>a.href)');
  for(const href of links){const url=new URL(href);assert.equal(url.protocol,'file:');assert(fs.existsSync(fileURLToPath(url)),href);}
  for(const width of [1400,390,320]){w.setSize(width,1000);await wait(80);assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('连续核对验收页-'+width);}
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,controlled_followups:2,local_links:links.length,images:2,widths:[1400,390,320],horizontal_overflow:false,console_errors:errors,network_requests:requests},null,2));w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));w.destroy();app.exit(1);}
});
