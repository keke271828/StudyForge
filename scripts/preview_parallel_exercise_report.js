// Read-only local report preview: desktop and phone size, no remote resources.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const folder=path.resolve(__dirname,'../build/parallel-exercise-review-20261015'),errors=[],network=[];
app.setPath('userData',path.join(folder,'electron-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1500,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 const run=code=>w.webContents.executeJavaScript(code);
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,done)=>{network.push(req.url);done({cancel:true});});
 try{
  await w.loadURL(pathToFileURL(path.join(folder,'双核查并行与候选对照.html')).href);await run('document.fonts.ready');
  assert.deepEqual(await run('[...document.querySelectorAll("table tbody")].map(t=>t.rows.length)'),[3,16]);
  assert.equal(await run('document.querySelectorAll("details").length'),16);
  assert(await run('document.body.textContent.includes("53.72")&&document.body.textContent.includes("27.85")'));
  assert(!await run('/TEST_COUNT|PARALLEL_ROWS|CANDIDATE_ROWS|FINDINGS|PRIVATE_CHECK_/.test(document.body.textContent)'));
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  for(const file of ['最终核验记录.json','不含私有答案的对照数据.json'])assert(fs.existsSync(path.join(folder,file)));
  await run('document.querySelector("details").open=true');
  assert(await run('document.querySelector("details p").getBoundingClientRect().height>0'));
  w.webContents.debugger.attach('1.3');const picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(folder,'实际页面预览.png'),Buffer.from(picture.data,'base64'));
  w.setSize(390,844);await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  assert(!network.length&&!errors.length,JSON.stringify({network,errors}));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,parallel_rows:3,candidate_rows:16,
   desktop_and_phone_no_horizontal_page_overflow:true,details_expand:true,console_errors:errors,network_requests:network,external_model_requests:0},null,2));
  w.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(1);}
});
