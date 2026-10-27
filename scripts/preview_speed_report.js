// Read-only local report verification; no model requests or remote resources.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const folder=path.resolve(__dirname,'../build/deepseek-speed-review-20261015'),errors=[],network=[];
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1540,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 const run=code=>w.webContents.executeJavaScript(code);
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,done)=>{network.push(req.url);done({cancel:true});});
 try{
  await w.loadURL(pathToFileURL(path.join(folder,'DeepSeek实际速度诊断.html')).href);await run('document.fonts.ready');
  assert.deepEqual(await run('[...document.querySelectorAll("table tbody")].map(t=>t.rows.length)'),[6,4]);
  assert(await run('document.body.textContent.includes("7406")&&document.body.textContent.includes("28935")'));
  assert(!await run('/TOTAL_TOKENS|CONNECTION_ROWS/.test(document.body.textContent)'));
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  for(const file of ['逐请求指标.csv','最终核验记录.json'])assert(fs.existsSync(path.join(folder,file)));
  w.webContents.debugger.attach('1.3');const picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(folder,'实际页面预览.png'),Buffer.from(picture.data,'base64'));
  w.setSize(390,844);await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  assert(!network.length&& !errors.length,JSON.stringify({network,errors}));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,request_rows:6,connection_rows:4,
   desktop_and_phone_no_horizontal_page_overflow:true,console_errors:errors,network_requests:network,external_model_requests:0},null,2));
  w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(1);}
});
