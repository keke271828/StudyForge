/* Refresh acceptance screenshots from the existing isolated paired session. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-content-check'));app.disableHardwareAcceleration();
const run=(w,c)=>w.webContents.executeJavaScript(c),sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(w,c){for(let n=0;n<350;n++){if(await run(w,c))return;await sleep(65);}throw Error(c);}
async function shot(w,name){w.webContents.debugger.attach('1.3');const picture=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(picture.data,'base64'));}
app.whenReady().then(async()=>{
 const windows=[];
 try{
  const pc=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});windows.push(pc);
  await pc.loadURL(data.desktop_url);await until(pc,'state.ready&&state.conversation&&!conversationUI.restoring');
  const before=(await run(pc,"api('/__library_test__/calls')")).calls.length;
  await run(pc,`openLessonFeedback('${data.pc.questionnaire_id}')`);await sleep(350);await shot(pc,'desktop-content-check');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true}});windows.push(phone);
  await phone.webContents.session.clearStorageData({storages:['serviceworkers','cachestorage']});
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  await phone.loadURL(data.mobile_url);await until(phone,'mobile.authenticated&&mobile.chat');
  await run(phone,`studyforgeMobileLessonFeedback.open('${data.phone.questionnaire_id}')`);
  await until(phone,"$('lessonFeedbackDialog').open&&document.querySelectorAll('dialog[open]').length===1");
  assert(await run(phone,"$('lessonFeedbackDialog').textContent.includes('理解与内容反馈')"));
  await sleep(600);await shot(phone,'phone-mixed-content-check');
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,before);
  fs.writeFileSync(path.join(folder,'preview-report.json'),JSON.stringify({passed:true,updated_neutral_feedback_title:true,new_model_requests:0},null,2));
  windows.forEach(w=>w.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'preview-report.json'),JSON.stringify({passed:false,error:error.stack},null,2));windows.forEach(w=>w.destroy());app.exit(1);}
});
