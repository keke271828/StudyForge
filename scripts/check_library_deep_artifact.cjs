/* Render the real, unedited model comparison with local math assets. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.resolve(__dirname,'../build/library-deep-real-20261011-1');
app.setPath('userData',path.join(folder,'artifact-browser'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1500,height:980,webPreferences:{sandbox:true,contextIsolation:true}});
 const errors=[];win.webContents.on('console-message',event=>{if(['error','warning'].includes(event.level)&&!event.message.includes('Electron Security Warning'))errors.push(event.message);});
 try{
  await win.loadFile(path.join(folder,'结构索引与重点精读对照.html'));
  const result=await win.webContents.executeJavaScript(`(()=>({index:document.getElementById('index').textContent.length,deep:document.getElementById('deep').textContent.length,formulas:document.querySelectorAll('.katex').length,errors:[...document.querySelectorAll('.katex-error')].map(x=>x.textContent),images:[...document.querySelectorAll('.originals img')].map(x=>({complete:x.complete,width:x.naturalWidth}))}))()`);
  assert(result.index>800&&result.deep>2500);assert(result.formulas>25);assert.equal(result.errors.length,0);assert(result.images.length===2&&result.images.every(x=>x.complete&&x.width>500));assert.equal(errors.length,0);
  fs.writeFileSync(path.join(folder,'artifact-desktop.png'),(await win.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(folder,'artifact-ui-report.json'),JSON.stringify({passed:true,...result,console_errors:errors},null,2));
  win.destroy();app.quit();
 }catch(e){fs.writeFileSync(path.join(folder,'artifact-ui-report.json'),JSON.stringify({passed:false,error:String(e.stack||e),console_errors:errors},null,2));win.destroy();app.exit(1);}
});
