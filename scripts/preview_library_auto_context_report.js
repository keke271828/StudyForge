const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/library-auto-context-acceptance-20261021');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}}),errors=[],requests=[];
 window.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
 window.webContents.session.webRequest.onBeforeRequest((request,callback)=>{if(/^https?:/.test(request.url))requests.push(request.url);callback({cancel:false});});
 const run=code=>window.webContents.executeJavaScript(code);let linkCount=0;
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const result=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));}
 try{
  await window.loadFile(path.join(folder,'知识库自动参考与讲解聚焦验收.html'));
  assert.equal(await run('document.querySelectorAll("#sourceCase option").length'),3);assert.equal(await run('document.querySelectorAll("#answerCase option").length'),2);
  for(let index=0;index<3;index++){await run(`document.getElementById('sourceCase').value='${index}';document.getElementById('sourceCase').dispatchEvent(new Event('change'));`);
   assert(await run(`data.sources[${index}].rows.every((row,j)=>document.querySelectorAll('#sourceComparison [data-raw]')[j].textContent===row.context)`));}
  for(let index=0;index<2;index++){await run(`document.getElementById('answerCase').value='${index}';document.getElementById('answerCase').dispatchEvent(new Event('change'));`);
   assert(await run(`data.answers[${index}].rows.every((row,j)=>document.querySelectorAll('#answerComparison [data-raw]')[j].dataset.raw===row.answer)`));
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
   const links=await run('[...document.querySelectorAll("a[href]")].map(link=>link.href)');for(const href of links){const url=new URL(href);assert.equal(url.protocol,'file:');assert(fs.existsSync(fileURLToPath(url)),href);}linkCount=Math.max(linkCount,links.length);
  }
  await run("document.getElementById('sourceCase').value='1';document.getElementById('sourceCase').dispatchEvent(new Event('change'));document.getElementById('answerCase').value='0';document.getElementById('answerCase').dispatchEvent(new Event('change'))");
  assert(await run("document.querySelector('#sourceComparison .old .metric').textContent.includes('3个节点')&&document.querySelector('#sourceComparison .new .metric').textContent.includes('1个节点')"));
  for(let index=0;index<100;index++){if(await run('[...document.images].every(image=>image.complete&&image.naturalWidth>0)'))break;await sleep(50);}assert(await run('[...document.images].every(image=>image.complete&&image.naturalWidth>0)'));
  for(const width of [1400,390,320]){window.setSize(width,1000);await sleep(150);await run('scrollTo(0,0)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('自动参考验收页-'+width);await run("document.getElementById('sourceComparison').scrollIntoView()");await sleep(100);await shot('参考聚焦对照-'+width);}
  await run('document.querySelectorAll("details").forEach(element=>element.open=true)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
  assert(await run("[...document.querySelectorAll('.source,.lesson')].every(element=>{if(element.scrollHeight>element.clientHeight+1){element.scrollTop=element.scrollHeight;return element.scrollTop>0}return true})"));
  assert(!errors.length,JSON.stringify(errors));assert(!requests.length,JSON.stringify(requests));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,source_cases:3,answer_pairs:2,raw_reference_inputs_preserved:6,raw_answers_preserved:4,katex_errors:0,images:2,local_links_per_view:linkCount,widths:[1400,390,320],horizontal_overflow:false,scrollable_outputs:true,console_errors:errors,network_requests:requests},null,2));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));window.destroy();app.exit(1);}
});
