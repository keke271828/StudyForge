const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/teaching-witness-acceptance-20261022');
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 const window=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
 const errors=[],network=[];let links=0;
 window.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message)});
 window.webContents.session.webRequest.onBeforeRequest((request,callback)=>{if(/^https?:/.test(request.url))network.push(request.url);callback({cancel:false})});
 const run=code=>window.webContents.executeJavaScript(code);
 async function shot(name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const result=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'))}
 try{
  await window.loadFile(path.join(folder,'教学例子前提与代数核对验收.html'));
  assert.equal(await run('data.pairs.length'),3);assert.equal(await run('data.audits.length'),8);assert.equal(await run('data.native.length'),4);
  for(let index=0;index<3;index++){
   await run("document.getElementById('pair').value='"+index+"';document.getElementById('pair').dispatchEvent(new Event('change'))");
   assert(await run("data.pairs["+index+"].rows.every((row,j)=>document.querySelectorAll('#pairRows [data-raw]')[j].dataset.raw===row.answer)"));
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
   for(const href of await run('[...document.querySelectorAll("a[href]")].map(element=>element.href)')){const url=new URL(href);assert.equal(url.protocol,'file:');assert(fs.existsSync(fileURLToPath(url)),href);links++}
  }
  assert(await run('data.audits.every((row,j)=>document.querySelectorAll("#audits pre")[j].textContent===row.raw)'));
  assert(await run('data.native.every((row,j)=>document.querySelectorAll("#native [data-raw]")[j].dataset.raw===row.content)'));
  assert.equal(await run('data.audits.filter(row=>!row.strict_json).length'),2);
  await run('document.getElementById("initial").click()');assert.equal(await run('document.getElementById("left").textContent'), '7');assert.equal(await run('document.getElementById("right").textContent'),'7');
  await run('document.getElementById("witness").click()');assert.equal(await run('document.getElementById("left").textContent'),'8');assert.equal(await run('document.getElementById("right").textContent'),'9');
  await run('document.getElementById("a").value=4;document.getElementById("a").dispatchEvent(new Event("input"))');assert.equal(await run('document.getElementById("left").textContent'),'9');assert.equal(await run('document.getElementById("right").textContent'),'11');
  await run('document.querySelectorAll("details").forEach(element=>element.open=true)');
  await run('document.getElementById("pair").value=0;document.getElementById("pair").dispatchEvent(new Event("change"));document.getElementById("witness").click()');
  assert.equal(await run('getComputedStyle(document.querySelector("section")).borderRadius'),'24px');
  for(const width of [1400,390,320]){
   window.setSize(width,1000);await sleep(100);await run('scrollTo(0,0)');assert(await run('document.documentElement.scrollWidth<=innerWidth+1'));
   await shot('教学核验页-'+width);await run('document.getElementById("pairRows").scrollIntoView()');await sleep(70);await shot('实际讲解对照-'+width);
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
  }
  assert(await run('[...document.querySelectorAll(".raw,.answer,.native")].every(element=>{if(element.scrollHeight>element.clientHeight+1){element.scrollTop=element.scrollHeight;return element.scrollTop>0}return true})'));
  assert(!errors.length,JSON.stringify(errors));assert(!network.length,JSON.stringify(network));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,teaching_pairs:3,raw_answers_preserved:6,raw_audits_preserved:8,native_documents_preserved:4,
   invalid_original_json_visible:2,local_links_verified:links,widths:[1400,390,320],horizontal_overflow:false,scrollable_outputs:true,
   exact_example_buttons_and_slider:true,katex_errors:0,console_errors:errors,network_requests:network,business_ui_test:false,physical_android_test:false},null,2));
  window.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:network},null,2));window.destroy();app.exit(1)}
});
