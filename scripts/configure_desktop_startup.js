/* Headless configuration for the source desktop. Does not start/stop its backend. */
const {app}=require('electron');
const path=require('node:path');
const {createStartupManager}=require('../desktop/startup');
const {readWindowsEntry}=require('../desktop/windows_startup');
app.setName('StudyForge');
app.whenReady().then(()=>{
  try{
    if(process.env.STUDYFORGE_SMOKE_REPORT)throw new Error('Do not configure the real startup entry from an acceptance environment');
    const enable=process.argv.includes('--enable'),disable=process.argv.includes('--disable');
    if(enable===disable)throw new Error('Specify exactly one of --enable / --disable');
    const storageDirectory=path.resolve(process.env.STUDYFORGE_DATA_DIR||path.join(process.env.LOCALAPPDATA||app.getPath('userData'),'StudyForge'));
    const manager=createStartupManager({app,storageDirectory,projectRoot:path.resolve(__dirname,'..')});
    const result=manager.save({enabled:enable,start_hidden:!process.argv.includes('--foreground')});
    console.log(JSON.stringify({ok:true,...result,native_entry:readWindowsEntry('StudyForge')},null,2));
  }catch(error){console.error(error.message);app.exit(1);return;}
  app.quit();
});
