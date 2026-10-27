const {desktopCaller}=require('./lifecycle');

function windowState(win) {
  if(!win||win.isDestroyed())throw new Error('学习窗口已经关闭');
  return {fullscreen:win.isFullScreen()};
}

function setWindowFullscreen(win,value,timeoutMs=3000) {
  if(typeof value!=='boolean')throw new Error('全屏状态必须为布尔值');
  if(windowState(win).fullscreen===value)return Promise.resolve(windowState(win));
  return new Promise((resolve,reject)=>{
    const event=value?'enter-full-screen':'leave-full-screen';
    let timeout;
    const cleanup=()=>{clearTimeout(timeout);win.removeListener(event,changed);win.removeListener('closed',closed);};
    const changed=()=>{cleanup();try{resolve(windowState(win));}catch(error){reject(error);}};
    const closed=()=>{cleanup();reject(new Error('学习窗口已经关闭'));};
    win.once(event,changed);win.once('closed',closed);
    timeout=setTimeout(()=>{cleanup();
      try{if(windowState(win).fullscreen===value)resolve(windowState(win));else reject(new Error('窗口未完成全屏切换，请重试'));}
      catch(error){reject(error);}
    },timeoutMs);
    try{win.setFullScreen(value);if(windowState(win).fullscreen===value)changed();}
    catch(error){cleanup();reject(error);}
  });
}

function attachWindowControls(win) {
  const changed=()=>{if(!win.isDestroyed()&&!win.webContents.isDestroyed())win.webContents.send('studyforge:window-changed',windowState(win));};
  win.on('enter-full-screen',changed);win.on('leave-full-screen',changed);
  win.on('resize',changed);win.on('show',changed);
}

function registerWindowHandlers(ipcMain,origin,getWindow) {
  ipcMain.handle('studyforge:window-state',event=>{
    desktopCaller(event,origin,getWindow);return windowState(getWindow());
  });
  ipcMain.handle('studyforge:window-fullscreen',(event,value)=>{
    desktopCaller(event,origin,getWindow);return setWindowFullscreen(getWindow(),value);
  });
}

module.exports={windowState,setWindowFullscreen,attachWindowControls,registerWindowHandlers};
