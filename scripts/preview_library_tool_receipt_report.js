const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/library-tool-receipt-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}}),errors=[],requests=[];
 window.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
 window.webContents.session.webRequest.onBeforeRequest((request,callback)=>{if(/^https?:/.test(request.url))requests.push(request.url);callback({cancel:false});});
 const run=code=>window.webContents.executeJavaScript(code);
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const result=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));}
 try{
  await window.loadFile(path.join(folder,'导师原页回查与阅读版本验收.html'));
  assert.equal(await run('document.querySelectorAll("#example option").length'),4);
  for(let index=0;index<4;index++){
   await run(`document.getElementById('example').value='${index}';document.getElementById('example').dispatchEvent(new Event('change'));`);
   assert(await run(`document.getElementById('returned').textContent===(examples[${index}].returned_text||'（空字符串：没有返回正文）')&&document.getElementById('receipt').textContent===JSON.stringify(examples[${index}].receipt,null,2)`));
  }
  await run("document.getElementById('example').value='2';document.getElementById('example').dispatchEvent(new Event('change'))");
  assert(await run("document.getElementById('textMetric').textContent.includes('未提供正文')&&!JSON.parse(document.getElementById('receipt').textContent).sources[0].included"));
  await run("document.getElementById('example').value='0';document.getElementById('example').dispatchEvent(new Event('change'))");
  for(let index=0;index<100;index++){if(await run('[...document.images].every(image=>image.complete&&image.naturalWidth>0)'))break;await wait(50);}
  assert(await run('[...document.images].every(image=>image.complete&&image.naturalWidth>0)'));
  const links=await run('[...document.querySelectorAll("a[href]")].map(link=>link.href)');
  for(const href of links){const url=new URL(href);assert.equal(url.protocol,'file:');assert(fs.existsSync(fileURLToPath(url)),href);}
  for(const width of [1400,390,320]){
   window.setSize(width,1000);await wait(150);await run('scrollTo(0,0)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('原页回查验收页-'+width);
   await run('document.getElementById("caseTitle").scrollIntoView()');await wait(100);await shot('实际读取对照-'+width);
  }
  await run('document.querySelectorAll("details").forEach(element=>element.open=true)');
  assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
  assert(await run("[...document.querySelectorAll('pre')].every(element=>{if(element.scrollHeight>element.clientHeight+1){element.scrollTop=element.scrollHeight;return element.scrollTop>0}return true})"));
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,interactive_cases:4,raw_tool_text_preserved:true,raw_receipts_preserved:true,local_links:links.length,images:2,widths:[1400,390,320],horizontal_overflow:false,scrollable_receipts:true,console_errors:errors,network_requests:requests},null,2));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));window.destroy();app.exit(1);}
});
