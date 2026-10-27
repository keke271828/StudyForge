const fs=require('node:fs');
const path=require('node:path');
const {desktopCaller}=require('./lifecycle');
const {readWindowsEntry}=require('./windows_startup');

const AUTO_FLAG='--studyforge-autostart';
const HIDDEN_FLAG='--studyforge-start-hidden';
const isAutostartLaunch=argv=>argv.includes(AUTO_FLAG);
const startHidden=argv=>isAutostartLaunch(argv)&&argv.includes(HIDDEN_FLAG);
const samePath=(a,b)=>path.win32.normalize(a||'').toLowerCase()===path.win32.normalize(b||'').toLowerCase();
const sameArgs=(a,b)=>JSON.stringify(a||[])===JSON.stringify(b||[]);

function launchSettings({packaged,executable,projectRoot,hidden=true}){
  // Electron quotes individual arguments when it writes the Run command.
  // Pre-quoting the project path makes literal quotes reach Electron at login.
  const args=packaged?[]:[path.resolve(projectRoot)];
  args.push(AUTO_FLAG);if(hidden)args.push(HIDDEN_FLAG);
  return {path:executable,args};
}

function createStartupManager({app,storageDirectory,projectRoot,executable=process.execPath,
                               platform=process.platform,name='StudyForge',readEntry=readWindowsEntry,files=fs}){
  const file=path.join(storageDirectory,'desktop','startup.json');
  const available=platform==='win32';
  function preferences(){
    try{
      const value=JSON.parse(files.readFileSync(file,'utf8'));
      return {enabled:value.enabled===true,start_hidden:value.start_hidden!==false,launch:value.launch};
    }catch{return {enabled:false,start_hidden:true};}
  }
  function launch(hidden){return launchSettings({packaged:app.isPackaged,executable,projectRoot,hidden});}
  function registered(value){
    // Electron 44's getter can report no launchItems for a source executable
    // even after its setter wrote a valid Run value. Read the owned native value.
    const row=readEntry(name);
    return row&&row.scope==='user'&&samePath(row.path,value.path)?row:null;
  }
  function persist(value){
    files.mkdirSync(path.dirname(file),{recursive:true});
    const temporary=file+'.tmp';
    try{
      files.writeFileSync(temporary,JSON.stringify(value,null,2));
      try{files.renameSync(temporary,file);}
      catch(error){
        if(error.code!=='EXDEV')throw error;
        // Redirected Windows profile files can land on different backing
        // volumes even in one directory. Keep rollback data for this fallback.
        const previous=files.existsSync(file)?files.readFileSync(file):null;
        try{files.copyFileSync(temporary,file);}
        catch(copyError){
          if(previous!==null)files.writeFileSync(file,previous);
          else if(files.existsSync(file))files.unlinkSync(file);
          throw copyError;
        }
      }
    }
    finally{if(files.existsSync(temporary))files.unlinkSync(temporary);}
  }
  function describe(saved,item){
    const expected=launch(saved.start_hidden);
    if(!available)return {available:false,enabled:false,start_hidden:saved.start_hidden,message:'开机自动启动目前支持 Windows 桌面版。'};
    const matched=Boolean(item&&item.scope==='user'&&samePath(item.path,expected.path)&&sameArgs(item.args,expected.args));
    const enabled=matched&&item.enabled===true;
    const blocked=Boolean(matched&&!item.enabled);
    return {available:true,registered:matched,enabled,blocked_by_windows:blocked,start_hidden:saved.start_hidden,
      source_build:!app.isPackaged,launch_name:name,executable,
      message:blocked?'Windows 已禁用此启动项；可在这里重新开启，或在任务管理器的“启动应用”中启用 StudyForge。':
        enabled?(saved.start_hidden?'已设置。下次登录 Windows 时自动启动，窗口先隐藏到右下角托盘。':'已设置。下次登录 Windows 时自动打开学习工作台。'):
        '开机自动启动未启用。手动打开软件不受影响。'};
  }
  function status(){const saved=preferences();return describe(saved,available?readEntry(name):null);}
  function save(value){
    if(!available)throw new Error('当前环境不支持 Windows 开机自动启动');
    if(typeof value?.enabled!=='boolean'||typeof value?.start_hidden!=='boolean')throw new Error('启动设置必须包含两个明确的开关');
    const previous=preferences(),oldLaunch=previous.launch||launch(previous.start_hidden),oldItem=readEntry(name);
    const target=launch(value.start_hidden);
    const saved={enabled:value.enabled,start_hidden:value.start_hidden,launch:target};let item;
    try{
      app.setLoginItemSettings({...target,name,openAtLogin:value.enabled,enabled:value.enabled});
      item=readEntry(name);
      if(value.enabled&&!(item&&item.scope==='user'&&samePath(item.path,target.path)&&item.enabled&&sameArgs(item.args,target.args)))throw new Error('Windows 未确认自启动已启用，请检查启动应用权限');
      if(!value.enabled&&item)throw new Error('Windows 启动项未移除，请重试');
      persist(saved);
    }
    catch(error){
      // Restore the exact previous command after setter, verification or disk
      // failures, including a source-to-installed migration that failed.
      try{app.setLoginItemSettings({...oldLaunch,...(oldItem?{path:oldItem.path,args:oldItem.args}:{}),name,openAtLogin:Boolean(oldItem),enabled:oldItem?.enabled===true});}
      catch(restoreError){throw new Error('启动设置未完成，恢复原启动项也失败：'+error.message+'；'+restoreError.message);}
      throw new Error('启动设置未保存，已恢复原启动项：'+error.message);
    }
    // The verified entry is still current; avoid launching another Windows
    // query after every save, which stalls the desktop's main process.
    return describe(saved,item);
  }
  function reconcile(){
    if(!available)return status();
    const saved=preferences(),old=saved.launch;
    if(saved.enabled&&old&&(!samePath(old.path,executable)||!sameArgs(old.args,launch(saved.start_hidden).args))){
      const entry=registered(old);
      // Moving from the source launcher to an installed build replaces one
      // owned entry. A user disabling it in Windows is never undone here.
      if(entry?.enabled&&sameArgs(entry.args,old.args))return save({enabled:true,start_hidden:saved.start_hidden});
    }
    return status();
  }
  return {status,save,reconcile};
}

function registerStartupHandlers(ipcMain,origin,getWindow,manager){
  ipcMain.handle('studyforge:startup-status',event=>{desktopCaller(event,origin,getWindow);return manager.status();});
  ipcMain.handle('studyforge:startup-save',(event,value)=>{desktopCaller(event,origin,getWindow);return manager.save(value);});
}

module.exports={AUTO_FLAG,HIDDEN_FLAG,isAutostartLaunch,startHidden,launchSettings,createStartupManager,registerStartupHandlers};
