/* Inspect the local report, all delivered files, and desktop/phone layout. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL,fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/review-data-acceptance-20261015'),errors=[],network=[];
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1450,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 const run=c=>w.webContents.executeJavaScript(c);
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,done)=>{network.push(req.url);done({cancel:true});});
 try{
  await w.loadURL(pathToFileURL(path.join(folder,'审核输入与核查记录保留实际对照.html')).href);await run('document.fonts.ready');
  assert.deepEqual(await run('[...document.querySelectorAll("table tbody")].map(t=>t.rows.length)'),[4,2]);
  assert.equal(await run('document.querySelectorAll("details").length'),12);
  for(const url of await run('[...document.querySelectorAll("a")].map(a=>a.href)'))assert(fs.existsSync(fileURLToPath(url)),url);
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  w.webContents.debugger.attach('1.3');let picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(folder,'实际页面预览.png'),Buffer.from(picture.data,'base64'));
  w.setSize(390,844);await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  await run('document.querySelector("details").open=true');assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,'手机宽度预览.png'),Buffer.from(picture.data,'base64'));
  assert(!network.length&&!errors.length,JSON.stringify({network,errors}));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,table_rows:[4,2],details:12,links_exist:true,
    desktop_and_phone_no_horizontal_page_overflow:true,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(1);}
});
