// Inspect the saved student-only report; no model or external site access.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const folder=path.resolve(__dirname,'../build/lesson-check-review-20261015'),errors=[],remote=[];
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1540,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 const run=code=>w.webContents.executeJavaScript(code);
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,done)=>{remote.push(req.url);done({cancel:true});});
 try{
  await w.loadURL(pathToFileURL(path.join(folder,'补讲后单题理解检查实际对照.html')).href);await run('document.fonts.ready');
  const samples=await run('[...document.querySelectorAll(".sample")].map(a=>({case:a.dataset.case,version:a.dataset.version,text:a.querySelector(".verbatim").textContent,link:a.querySelector("a").getAttribute("href")}))');
  assert.equal(samples.length,4);
  for(const item of samples){
   const source=path.join(folder,'../'+(item.version==='第一版'?'lesson-check-real-20261015-2':'lesson-check-real-20261015-3'));
   assert.equal(item.text,fs.readFileSync(path.join(source,item.case+'-student.md'),'utf8'));
   const target=path.resolve(folder,decodeURIComponent(item.link));assert(fs.existsSync(target));assert.equal(path.extname(target),'.docx');
  }
  assert.equal(await run('document.querySelectorAll(".group").length'),2);
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  w.webContents.debugger.attach('1.3');
  const picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(folder,'实际页面预览.png'),Buffer.from(picture.data,'base64'));
  w.setSize(390,844);await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  assert(!errors.length,JSON.stringify(errors));assert(!remote.length,JSON.stringify(remote));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,displayed_samples:samples.length,groups:2,
   verbatim_student_outputs:true,word_links_exist:true,desktop_and_phone_no_horizontal_overflow:true,
   console_errors:errors,network_requests:remote,external_model_requests:0},null,2));w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:remote},null,2));w.destroy();app.exit(1);}
});
