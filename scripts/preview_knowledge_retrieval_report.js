const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/knowledge-retrieval-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const wait=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}}),errors=[],requests=[];
 window.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 window.webContents.session.webRequest.onBeforeRequest((r,cb)=>{if(/^https?:/.test(r.url))requests.push(r.url);cb({cancel:false});});
 const run=c=>window.webContents.executeJavaScript(c);
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const r=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
 try{
  await window.loadFile(path.join(folder,'知识库混合检索与条件保留验收.html'));
  assert.equal(await run('document.querySelectorAll("#example option").length'),3);
  for(let i=0;i<3;i++){
   await run(`document.getElementById('example').value='${i}';document.getElementById('example').dispatchEvent(new Event('change'));`);
   assert(await run(`examples[${i}].rows.every((row,j)=>document.querySelectorAll('.exact-output')[j].textContent===row.text)`));
  }
  await run("document.getElementById('example').value='1';document.getElementById('example').dispatchEvent(new Event('change'))");
  assert(await run("!document.querySelector('.before .exact-output').textContent.includes('EXACT_DOMAIN_CONDITION')&&document.querySelector('.after .exact-output').textContent.includes('EXACT_DOMAIN_CONDITION')&&document.querySelector('.after .exact-output').textContent.includes('DEFINITION_CONTEXT')"));
  for(let i=0;i<100;i++){if(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'))break;await wait(50);}
  assert(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'));
  const links=await run('[...document.querySelectorAll("a[href]")].map(a=>a.href)');let local=0,external=0;
  for(const href of links){const url=new URL(href);if(url.protocol==='file:'){assert(fs.existsSync(fileURLToPath(url)),href);local++;}else{assert.equal(url.protocol,'https:');external++;}}
  for(const width of [1400,390,320]){
   window.setSize(width,1000);await wait(100);await run('scrollTo(0,0)');
   assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('知识库验收页-'+width);
   await run('document.getElementById("caseTitle").scrollIntoView()');await wait(100);await shot('条件保留对照-'+width);
  }
  await run('document.querySelectorAll("details").forEach(el=>el.open=true)');
  assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
  assert(await run("[...document.querySelectorAll('pre')].every(el=>{if(el.scrollHeight>el.clientHeight+1){el.scrollTop=el.scrollHeight;return el.scrollTop>0}return true})"));
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,interactive_cases:3,raw_outputs_preserved:true,local_links:local,external_primary_links:external,images:2,widths:[1400,390,320],horizontal_overflow:false,scrollable_excerpts:true,console_errors:errors,network_requests:requests},null,2));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));window.destroy();app.exit(1);}
});
