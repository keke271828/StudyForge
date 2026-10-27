// Open and inspect the offline comparison without contacting any model/site.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const target=path.resolve(process.argv[2]),folder=path.dirname(target),errors=[],remote=[];
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1540,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,cb)=>{remote.push(req.url);cb({cancel:true});});
 const run=code=>w.webContents.executeJavaScript(code),sleep=ms=>new Promise(r=>setTimeout(r,ms));
 try{
  await w.loadURL(pathToFileURL(target).href);await run('document.fonts.ready');let count=0;
  const groups=await run('comparison.groups.length');
  for(let i=0;i<groups;i++){
   await run(`groupSelect.value='${i}';showGroup()`);
   assert.equal(await run('document.querySelectorAll(".answer").length'),await run('comparison.groups[Number(groupSelect.value)].rows.length'));
   assert.equal(await run('document.querySelectorAll(".katex-error").length'),0);
   count+=await run('document.querySelectorAll(".answer").length');
  }
  assert.equal(count,await run('comparison.count'));await run("groupSelect.value='0';showLabels=true;showGroup()");await sleep(400);
  w.webContents.debugger.attach('1.3');const shot=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,'实际页面预览.png'),Buffer.from(shot.data,'base64'));
  assert(!errors.length,JSON.stringify(errors));assert(!remote.length,JSON.stringify(remote));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,groups,displayed_samples:count,console_errors:errors,network_requests:remote,external_model_requests:0},null,2));w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:remote},null,2));w.destroy();app.exit(1);}
});
