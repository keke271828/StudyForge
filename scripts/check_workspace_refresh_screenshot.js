/* Visual check after the existing sheet transition settles; reuse our paired fixture. */
const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-refresh'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
 await phone.loadURL(data.mobile_url);
 for(let i=0;i<350;i++){if(await phone.webContents.executeJavaScript("typeof mobile!=='undefined'&&mobile.authenticated&&mobile.artifacts.length===2"))break;await new Promise(resolve=>setTimeout(resolve,100));}
 await phone.webContents.executeJavaScript("$('openArtifacts').click()");await new Promise(resolve=>setTimeout(resolve,500));
 phone.webContents.debugger.attach('1.3');const result=await phone.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});
 fs.writeFileSync(path.join(folder,'phone-artifacts-settled.png'),Buffer.from(result.data,'base64'));phone.destroy();app.exit(0);
}).catch(error=>{fs.writeFileSync(path.join(folder,'screenshot-error.txt'),String(error));app.exit(1);});
