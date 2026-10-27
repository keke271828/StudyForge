const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/library-followup-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}}),errors=[],requests=[];
 window.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
 window.webContents.session.webRequest.onBeforeRequest((request,callback)=>{if(/^https?:/.test(request.url))requests.push(request.url);callback({cancel:false});});
 const run=code=>window.webContents.executeJavaScript(code);let links=0;
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const result=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));}
 try{
  await window.loadFile(path.join(folder,'原句追问与知识库教学对照验收.html'));assert.equal(await run('document.querySelectorAll("#case option").length'),3);
  for(let index=0;index<3;index++)for(const view of ['answer','context']){
   await run(`document.getElementById('case').value='${index}';document.getElementById('view').value='${view}';document.getElementById('case').dispatchEvent(new Event('change'));`);
   assert(await run(`examples[${index}].rows.every((row,j)=>document.querySelectorAll('#comparison [data-raw]')[j].dataset.raw===row['${view}'])`));
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
   const hrefs=await run('[...document.querySelectorAll("a[href]")].map(link=>link.href)');for(const href of hrefs){const url=new URL(href);assert.equal(url.protocol,'file:');assert(fs.existsSync(fileURLToPath(url)),href);}links=Math.max(links,hrefs.length);
  }
  await run("document.getElementById('case').value='1';document.getElementById('view').value='answer';document.getElementById('case').dispatchEvent(new Event('change'))");
  assert(await run("document.querySelector('.old .badge').textContent.includes('未提供目标原文')&&document.querySelector('.new .badge').textContent.includes('已提供目标原文')&&document.querySelectorAll('.katex').length>0"));
  for(let index=0;index<100;index++){if(await run('[...document.images].every(image=>image.complete&&image.naturalWidth>0)'))break;await sleep(50);}assert(await run('[...document.images].every(image=>image.complete&&image.naturalWidth>0)'));
  for(const width of [1400,390,320]){window.setSize(width,1000);await sleep(150);await run('scrollTo(0,0)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('原句追问验收页-'+width);await run("document.getElementById('comparison').scrollIntoView()");await sleep(100);await shot('高斯原样对照-'+width);}
  await run('document.querySelectorAll("details").forEach(element=>element.open=true)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
  assert(await run("[...document.querySelectorAll('.lesson,.source')].every(element=>{if(element.scrollHeight>element.clientHeight+1){element.scrollTop=element.scrollHeight;return element.scrollTop>0}return true})"));
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,interactive_cases:3,views_per_case:2,raw_answers_preserved:6,reference_inputs_preserved:6,katex_errors:0,images:2,local_links_per_view:links,widths:[1400,390,320],horizontal_overflow:false,scrollable_answers:true,console_errors:errors,network_requests:requests},null,2));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));window.destroy();app.exit(1);}
});
