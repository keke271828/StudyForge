/* Verify the local acceptance report on desktop and phone widths. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL,fileURLToPath}=require('node:url');
const folder=path.resolve(__dirname,'../build/content-check-review-20261015'),errors=[],network=[];
app.setPath('userData',path.join(folder,'electron-report-preview'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1450,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});
 const run=code=>w.webContents.executeJavaScript(code);
 w.webContents.on('console-message',e=>{if(e.level==='error'||e.level===3)errors.push(e.message);});
 w.webContents.session.webRequest.onBeforeRequest({urls:['https://*/*','http://*/*']},(req,done)=>{network.push(req.url);done({cancel:true});});
 try{
  await w.loadURL(pathToFileURL(path.join(folder,'内容核对与审核候选实际对照.html')).href);await run('document.fonts.ready');
  assert.deepEqual(await run('[...document.querySelectorAll("table tbody")].map(t=>t.rows.length)'),[5,5]);
  assert(await run('document.querySelectorAll("details").length===54'));
  assert(!await run('/TEST_COUNT/.test(document.body.textContent)'));
  for(const url of await run('[...document.querySelectorAll("a")].map(a=>a.href)'))assert(fs.existsSync(fileURLToPath(url)),url);
  assert(await run('[...document.images].every(i=>i.complete&&i.naturalWidth>0)'));
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  w.webContents.debugger.attach('1.3');const picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(folder,'实际页面预览.png'),Buffer.from(picture.data,'base64'));
  w.setSize(390,844);await run('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  await run('document.querySelector("details").open=true');
  assert(await run('document.documentElement.scrollWidth<=innerWidth'));
  assert(!network.length&&!errors.length,JSON.stringify({network,errors}));
  fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:true,table_rows:[5,5],details:54,links_and_images_exist:true,
   desktop_and_phone_no_horizontal_page_overflow:true,console_errors:errors,network_requests:network,external_model_requests:0},null,2));
  w.destroy();app.exit(0);
 }catch(error){const layout=await run(`({width:innerWidth,scroll:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('body *')].map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width,text:e.textContent.slice(0,90)})).filter(e=>e.right>innerWidth+1).slice(0,16)})`);fs.writeFileSync(path.join(folder,'页面运行核验.json'),JSON.stringify({passed:false,error:error.stack,layout,console_errors:errors,network_requests:network},null,2));w.destroy();app.exit(1);}
});
