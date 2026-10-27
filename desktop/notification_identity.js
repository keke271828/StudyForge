const fs=require('node:fs');
const path=require('node:path');

// The installed app's NSIS shortcut already supplies this identity. Source
// acceptance also needs a Start Menu identity for Windows' native toast API.
function ensureNotificationIdentity({app,shell,root,icon,platform=process.platform,shortcutDirectory,appId,shortcutName='StudyForge 源码验收版.lnk'}){
  if(platform!=='win32')return {appId:null};
  appId=appId||(app.isPackaged?'org.studyforge.desktop':'org.studyforge.desktop.source');
  app.setAppUserModelId(appId);
  if(app.isPackaged)return {appId};
  const folder=shortcutDirectory||path.join(app.getPath('appData'),'Microsoft','Windows','Start Menu','Programs');
  fs.mkdirSync(folder,{recursive:true});
  const shortcut=path.join(folder,shortcutName);
  const details={target:process.execPath,args:'"'+root+'"',cwd:root,icon,iconIndex:0,
    description:'StudyForge 学习工作台（源码验收版）',appUserModelId:appId};
  if(!shell.writeShortcutLink(shortcut,'create',details))throw new Error('无法建立 Windows 通知身份，请从安装版运行');
  return {appId,shortcut};
}
module.exports={ensureNotificationIdentity};
