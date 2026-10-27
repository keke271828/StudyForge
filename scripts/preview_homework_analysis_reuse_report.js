const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/homework-analysis-reuse-acceptance-20261022');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
 const errors=[],network=[];let links=0;
 window.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message)});
 window.webContents.session.webRequest.onBeforeRequest((request,callback)=>{if(/^https?:/.test(request.url))network.push(request.url);callback({cancel:false})});
 const run=code=>window.webContents.executeJavaScript(code);
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const value=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(value.data,'base64'))}
 try{
  await window.loadFile(path.join(folder,'错因澄清后按题续做与完整补讲验收.html'));
  assert.equal(await run('data.questions.length'),3);assert.equal(await run('data.raw.length'),3);assert.equal(await run('data.native.length'),2);
  assert(await run('JSON.stringify(data.raw.map(row=>JSON.parse(row.content).items.length))==="[3,3,1]"'));
  for(let index=0;index<3;index++){
   await run("document.getElementById('question').value='"+index+"';document.getElementById('question').dispatchEvent(new Event('change'))");
   assert(await run("['baseline','fixed'].every((arm,j)=>document.querySelectorAll('#comparison [data-raw]')[j].dataset.raw===lesson(data.questions["+index+"][arm]))"));
   if(index>0)assert(await run("JSON.stringify(data.questions["+index+"].initial)===JSON.stringify(data.questions["+index+"].fixed)"));
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
  }
  assert(await run('data.raw.every((item,j)=>document.querySelectorAll("#raw pre")[j].textContent===item.content)'));
  assert(await run('data.native.every((item,j)=>document.querySelectorAll("#native [data-raw]")[j].dataset.raw===item.content)'));
  for(const href of await run('[...document.querySelectorAll("a[href]")].map(element=>element.href)')){
   const url=new URL(href);assert.equal(url.protocol,'file:');const file=fileURLToPath(url);assert(fs.existsSync(file),href);
   if(url.hash&&file.endsWith('.html'))assert(fs.readFileSync(file,'utf8').includes('id="'+url.hash.slice(1)+'"'),href);
   links++;
  }
  await run('document.querySelectorAll("details").forEach(element=>element.open=true);document.getElementById("question").value=0;document.getElementById("question").dispatchEvent(new Event("change"))');
  assert.equal(await run('getComputedStyle(document.querySelector("section")).borderRadius'),'24px');
  for(const width of [1400,390,320]){
   window.setSize(width,1000);await sleep(120);await run('scrollTo(0,0)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));await shot('分题补讲验收页-'+width);
   await run('document.getElementById("comparison").scrollIntoView()');await sleep(80);await shot('数学补讲对照-'+width);
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
  }
  assert(await run('[...document.querySelectorAll(".lesson,.native,.raw")].every(element=>{if(element.scrollHeight>element.clientHeight+1){element.scrollTop=element.scrollHeight;return element.scrollTop>0}return true})'));
  assert(!errors.length,JSON.stringify(errors));assert(!network.length,JSON.stringify(network));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,question_pairs:3,original_teaching_items_preserved:6,raw_responses_preserved:3,
   model_written_items:[3,3,1],native_documents_preserved:2,unchanged_teaching_verified:[2,3],local_links:links,
   widths:[1400,390,320],horizontal_overflow:false,scrollable_outputs:true,katex_errors:0,console_errors:errors,network_requests:network,
   business_ui_test:false,physical_android_test:false},null,2));window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:network},null,2));window.destroy();app.exit(1)}
});
