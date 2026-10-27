/* Diagnose a public page with the desktop's Chromium networking and trust. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const url=process.env.STUDYFORGE_LIVE_URL||process.argv[2],output=process.env.STUDYFORGE_BROWSER_REPORT_DIR||process.argv[3];
if(!url||!output||!/^https?:$/.test(new URL(url).protocol))throw Error('Provide a public URL and an output directory');
fs.mkdirSync(output,{recursive:true});app.setPath('userData',path.join(output,'profile'));
app.disableHardwareAcceleration();let win;
app.on('window-all-closed',()=>{});
app.whenReady().then(async()=>{
  const result={url,success:false};
  try{
    win=new BrowserWindow({show:false,webPreferences:{offscreen:true,backgroundThrottling:false,contextIsolation:true,sandbox:true}});
    const load=win.loadURL(url).then(()=>true).catch(error=>{result.load_error=error.message;return false;});
    const loaded=await Promise.race([load,new Promise(resolve=>setTimeout(()=>resolve(false),25000))]);
    if(!loaded){result.error=result.load_error||'Browser load timed out';}
    else{
      result.title=await win.webContents.executeJavaScript('document.title');
      result.text_length=await win.webContents.executeJavaScript('document.body?.innerText.length||0');
      result.success=result.text_length>100;
    }
  }catch(error){result.error=error.message;}
  finally{fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));app.exit(0);}
});
