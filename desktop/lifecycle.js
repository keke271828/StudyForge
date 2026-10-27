const {setTimeout: delay} = require('node:timers/promises');

function desktopCaller(event, allowedOrigin, getWindow) {
  const frame=event.senderFrame;
  try {
    if(!frame || frame!==event.sender.mainFrame || event.sender!==getWindow()?.webContents
       || new URL(frame.url).origin!==allowedOrigin) throw new Error();
  } catch (_) { throw new Error('只允许 StudyForge 主窗口管理后台运行'); }
}

function createDesktopLifecycle({app, Tray, Menu, icon, getWindow, showWindow, prepareShutdown,
                                  stopBackend, readStatus, onError=()=>{}}) {
  let tray, menu, quitting=false, finished=false, sessionEnding=false, shutdownPromise, pollTimer,exitAction;
  let pollBusy=false, noticed=false, tasks={active_jobs:0,memory_running:false,paused_generations:0};
  const liveWindow=()=>{const win=getWindow();return win&&!win.isDestroyed()?win:null;};
  const status=()=>({tray_available:Boolean(tray&&!tray.isDestroyed()),quitting,window_visible:Boolean(liveWindow()?.isVisible()),...tasks});
  function updateMenu() {
    if(!tray||tray.isDestroyed())return;
    const hidden=!liveWindow()?.isVisible();
    const description=quitting?'正在保存并退出':tasks.active_jobs?`${tasks.active_jobs} 项任务运行中`
      :tasks.memory_running?'正在整理学习记忆':tasks.paused_generations?`${tasks.paused_generations} 项生成已暂停`:'已准备好，等待使用';
    tray.setToolTip(`StudyForge · ${description}${hidden?' · 窗口已隐藏':''}`);
    menu=Menu.buildFromTemplate([
      {id:'open',label:'打开学习工作台',enabled:!quitting,click:()=>showWindow()},
      {id:'progress',label:'查看生成进度',enabled:!quitting,click:()=>showWindow('artifacts')},
      {type:'separator'},
      {id:'status',label:description,enabled:false},
      {id:'hide',label:'隐藏到托盘',enabled:!quitting,click:hide},
      {type:'separator'},
      {id:'exit',label:quitting?'正在退出…':'退出 StudyForge',enabled:!quitting,click:()=>app.quit()}
    ]);
    tray.setContextMenu(menu);
  }
  function hide() {
    const win=getWindow();
    if(quitting||!tray||tray.isDestroyed()||!win||win.isDestroyed())return false;
    win.webContents.send('studyforge:desktop-hidden');
    win.hide();updateMenu();
    if(!noticed){
      noticed=true;
      if(process.platform==='win32')try{tray.displayBalloon({title:'StudyForge 仍在后台运行',
        content:'窗口已隐藏，生成任务和学习记录整理仍会继续。点击 Windows 右下角的 StudyForge 图标可回来；右键选择“退出 StudyForge”才会停止软件。'});}catch(_){/* OS may suppress balloons. */}
    }
    return true;
  }
  function attachWindow(win) {
    win.on('close',event=>{
      if(quitting)return;
      event.preventDefault();
      if(!hide())app.quit(); // A failed tray must never make the window unreachable.
    });
    win.on('show',updateMenu);win.on('hide',updateMenu);
    win.on('query-session-end',()=>{
      sessionEnding=true;quitting=true;
      Promise.resolve().then(prepareShutdown).catch(onError);
    });
  }
  async function poll() {
    if(pollBusy||quitting)return;
    pollBusy=true;
    try { tasks=await readStatus();updateMenu(); }
    catch(_){if(tray&&!tray.isDestroyed())tray.setToolTip('StudyForge · 本机服务暂不可用，请打开工作台查看');}
    finally{pollBusy=false;}
  }
  function dispose(){clearInterval(pollTimer);if(tray&&!tray.isDestroyed())tray.destroy();}
  app.on('before-quit',event=>{
    if(finished||sessionEnding){Promise.resolve().then(stopBackend).catch(onError);dispose();return;}
    event.preventDefault();
    if(shutdownPromise)return;
    quitting=true;clearInterval(pollTimer);updateMenu();
    liveWindow()?.webContents.send('studyforge:desktop-quitting');
    shutdownPromise=(async()=>{
      let receipt,prepared=false;
      try {receipt=await Promise.race([Promise.resolve().then(prepareShutdown),delay(5500,undefined,{ref:false})]);prepared=receipt!==undefined;}
      catch(error){onError(error);exitAction?.onFailure(error);}
      finally{
        try{await stopBackend();}catch(error){onError(error);prepared=false;exitAction?.onFailure(error);}
        if(exitAction){
          if(prepared)try{await exitAction.afterStop(receipt);}catch(error){onError(error);}
          else exitAction.onFailure(new Error('退出前状态保存或备份未完成，已取消安装；重新打开后可重试'));
        }
        dispose();finished=true;app.quit();
      }
    })();
  });
  app.on('window-all-closed',()=>{if(!tray||tray.isDestroyed())app.quit();});
  app.on('will-quit',dispose);
  function start(){
    try{
      tray=new Tray(icon);tray.on('click',()=>{if(!quitting)showWindow();});
      tray.on('double-click',()=>{if(!quitting)showWindow();});
      tray.on('balloon-click',()=>{if(!quitting)showWindow();});updateMenu();
    }catch(error){onError(error);tray=null;}
    pollTimer=setInterval(poll,5000);pollTimer.unref();
  }
  return {start,attachWindow,hide,status,poll,dispose,quit:()=>app.quit(),
          quitAfterSave:action=>{if(quitting)throw new Error('应用正在退出');exitAction=action;app.quit();},
          // Main-process handles for native desktop acceptance checks.
          get tray(){return tray;},get menu(){return menu;},get shutdownPromise(){return shutdownPromise;}};
}

function registerDesktopHandlers(ipcMain,allowedOrigin,getWindow,lifecycle){
  for(const [channel,callback] of [
    ['studyforge:desktop-status',()=>lifecycle.status()],
    ['studyforge:hide-to-tray',()=>{if(!lifecycle.hide())throw new Error('托盘暂不可用，请保持窗口打开');return true;}],
    ['studyforge:quit',()=>{setImmediate(()=>lifecycle.quit());return true;}]
  ])ipcMain.handle(channel,event=>{desktopCaller(event,allowedOrigin,getWindow);return callback();});
}

module.exports={createDesktopLifecycle,registerDesktopHandlers,desktopCaller};
