const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'build/source-focus-acceptance-20261026');
app.setPath('userData',path.join(folder,'report-browser'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1400,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}}),errors=[];
 win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
 const run=code=>win.webContents.executeJavaScript(code);
 try{
  await win.loadFile(path.join(folder,'长资料定位与导师讲解实际对照.html'));
  assert(await run("document.querySelectorAll('[data-case]').length===2&&document.querySelectorAll('#newAnswer .katex').length>10"));
  assert(await run("byId('newAnswer').dataset.rawText===data[0].arms.focused.text&&byId('oldAnswer').dataset.rawText===data[0].arms.legacy.text"));
  await run("byId('caseButtons').querySelectorAll('button')[1].click()");
  assert(await run("byId('metrics').textContent.includes('4898')&&byId('newAnswer').textContent.includes('81.2')&&byId('newAnswer').dataset.rawText===data[1].arms.focused.text"));
  assert(await run("!document.querySelector('.katex-error')&&document.documentElement.scrollWidth<=innerWidth+1"));
  await run("byId('question').scrollIntoView({block:'start'})");
  win.webContents.debugger.attach('1.3');
  const shot=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.join(folder,'实际对照页.png'),Buffer.from(shot.data,'base64'));
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'report-view.json'),JSON.stringify({passed:true,checks:['both actual answers preserved','case switching','formula rendering','metrics','no overflow','no console errors'],console_errors:errors},null,2));
  win.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'report-view.json'),JSON.stringify({passed:false,error:error.stack,console_errors:errors},null,2));win.destroy();app.exit(1);}
});
