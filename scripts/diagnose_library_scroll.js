const {app,BrowserWindow}=require('electron');const fs=require('node:fs'),path=require('node:path');
const folder=path.join(__dirname,'../build',process.argv[2]);const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'scroll-diagnostic-profile'));app.disableHardwareAcceleration();
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));app.on('window-all-closed',()=>{});
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{backgroundThrottling:false,sandbox:true}});
 const run=code=>win.webContents.executeJavaScript(code);const output=[];
 try{
  await win.loadURL(data.desktop_url);for(let i=0;i<250&&!await run("state.ready&&studyforgeBookLibrary.prefReady");i++)await delay(100);
  await run(`refreshNavigation().then(()=>selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'),{conversationId:'${data.conversation_id}'}))`);
  for(let i=0;i<100&&!await run('studyforgeBookLibrary.matchHistory.length>0');i++)await delay(100);
  await run("showView('study');document.documentElement.dataset.focus='false';window.scrollEvents=[];document.addEventListener('wheel',e=>scrollEvents.push({x:e.clientX,y:e.clientY,delta:e.deltaY,target:e.target.outerHTML.slice(0,250),prevented:e.defaultPrevented}),true)");
  win.webContents.debugger.attach('1.3');win.webContents.focus();await win.webContents.debugger.sendCommand('Page.bringToFront');
  const point=await run("(()=>{const l=document.querySelector('.book-match-list');l.scrollIntoView({block:'center'});l.scrollTop=0;const r=l.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,rect:{x:r.x,y:r.y,w:r.width,h:r.height},ratio:devicePixelRatio,zoom:getComputedStyle(document.body).zoom,visibility:document.visibilityState};})()");output.push({point,viewport:await win.webContents.debugger.sendCommand('Page.getLayoutMetrics')});
  for(const multiplier of [1,1/point.ratio,point.ratio]){
   await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',x:point.x*multiplier,y:point.y*multiplier});
   await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseWheel',x:point.x*multiplier,y:point.y*multiplier,deltaX:0,deltaY:240});await delay(500);
   output.push({multiplier,result:await run("({top:document.querySelector('.book-match-list').scrollTop,outer:document.querySelector('.book-chat-references').scrollTop,events:scrollEvents})")});
  }
  await run("document.querySelector('.book-match-list').focus()");
  await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyDown',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34});
  await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyUp',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34});await delay(200);
  output.push({keyboard:await run("({top:document.querySelector('.book-match-list').scrollTop,active:document.activeElement.className})")});
  fs.writeFileSync(path.join(folder,'library-scroll-diagnostic.json'),JSON.stringify(output,null,2));win.destroy();app.exit(0);
 }catch(error){output.push({error:String(error)});fs.writeFileSync(path.join(folder,'library-scroll-diagnostic.json'),JSON.stringify(output,null,2));win.destroy();app.exit(1);}
});
