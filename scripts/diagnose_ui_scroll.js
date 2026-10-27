const {app,BrowserWindow}=require('electron');const fs=require('node:fs'),path=require('node:path');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.disableHardwareAcceleration();
app.on('window-all-closed',()=>{});
const html=path.join(__dirname,'../build/scroll-input-diagnostic.html');
fs.writeFileSync(html,'<div id="list" style="height:150px;width:350px;overflow:auto;touch-action:pan-y">'+Array.from({length:40},(_,i)=>'<button style="display:block;height:40px">row '+i+'</button>').join('')+'</div><script>window.events=[];document.addEventListener("wheel",e=>events.push({type:e.type,delta:e.deltaY,target:e.target.textContent}));</script>');
app.whenReady().then(async()=>{
 const results=[];
 for(const offscreen of [false,true]){
  const win=new BrowserWindow({show:false,width:700,height:500,webPreferences:{offscreen,backgroundThrottling:false}});
  await win.loadFile(html);
  win.webContents.debugger.attach('1.3');
  win.webContents.focus();await win.webContents.debugger.sendCommand('Page.bringToFront');
  await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',x:100,y:100});
  await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseWheel',x:100,y:100,deltaX:0,deltaY:160});
  await delay(300);
  results.push({offscreen,method:'cdp',result:await win.webContents.executeJavaScript('({scroll:list.scrollTop,events})')});
  win.webContents.sendInputEvent({type:'mouseMove',x:100,y:100});
  win.webContents.sendInputEvent({type:'mouseWheel',x:100,y:100,deltaY:160});await delay(300);
  results.push({offscreen,method:'electron',result:await win.webContents.executeJavaScript('({scroll:list.scrollTop,events})')});
  win.destroy();
 }
 fs.writeFileSync(path.join(__dirname,'../build/scroll-input-diagnostic.json'),JSON.stringify(results,null,2));app.exit(0);
}).catch(error=>{process.stderr.write(String(error));app.exit(1);});
