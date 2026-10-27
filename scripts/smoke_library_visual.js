// Recheck the existing isolated UI fixture after a CSS change; no AI calls.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]||'library-ui-20261010-5');
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-profile'));
app.disableHardwareAcceleration();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=(win,code)=>win.webContents.executeJavaScript(code);
async function until(win,code){for(let i=0;i<240;i++){if(await run(win,code))return;await sleep(100);}throw Error('Visual wait failed: '+code);}
async function shot(win,name){
 await sleep(350);
 // CDP requests a newly composited frame; capturePage can return an older
 // hidden-window frame immediately after navigation or a dialog transition.
 if(!win.webContents.debugger.isAttached())win.webContents.debugger.attach('1.3');
 const shot=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(shot.data,'base64'));
}
const contrastCode=`(()=>{
 const el=document.querySelector('.book-upload'),s=getComputedStyle(el);
 const channels=c=>c.match(/[\\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
 const lum=c=>{const a=channels(c);return .2126*a[0]+.7152*a[1]+.0722*a[2];};
 const a=lum(s.color),b=lum(s.backgroundColor);
 return {text:el.textContent.trim(),color:s.color,background:s.backgroundColor,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
})()`;
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:1050,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 const phone=new BrowserWindow({show:false,width:320,height:740,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
 const errors=[];
 for(const win of [pc,phone])win.webContents.on('console-message',(_e,level,text)=>{if(level===3&&!text.includes('401')&&!text.includes('404'))errors.push(text);});
 try{
  await pc.webContents.session.clearCache();
  await pc.loadURL(data.desktop_url);
  await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");
  await sleep(1000);
  await run(pc,`libraryOpen('${data.book_id}')`);
  await until(pc,"state.view==='library'&&$('view-library').classList.contains('active')&&studyforgeBookLibrary.nodes.length===4");
  await run(pc,"applyStudioPreferences({...studioPreferences,ui_theme:'night'},true)");
  const desktop=await run(pc,contrastCode);
  assert(desktop.contrast>=4.5,JSON.stringify(desktop));
  const night=await run(pc,"({background:getComputedStyle(document.querySelector('.book-detail')).backgroundColor,color:getComputedStyle(document.querySelector('.book-node-select small')).color})");
  assert.equal(night.background,'rgb(36, 57, 47)');
  assert.equal(night.color,'rgb(190, 210, 194)');
  await shot(pc,'desktop-book-library-night');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));
  phone.webContents.session.setCertificateVerifyProc((request,callback)=>{
   let accepted=false;try{const leaf=new X509Certificate(request.certificate.data);accepted=request.hostname==='127.0.0.1'&&leaf.verify(ca.publicKey);}catch{}
   callback(accepted?0:-3);
  });
  const pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);
  await until(phone,"typeof mobile!=='undefined'&&typeof libraryOpen==='function'");
  await sleep(400);
  if(!await run(phone,'mobile.authenticated')){
   const name='书库外观验收 '+Date.now();
   await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
   await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
   await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});return fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})}).then(r=>r.json());})()`);
  }
  await until(phone,"mobile.authenticated&&mobile.chat&&studyforgeBookLibrary.chat===mobile.chat.id");
  await sleep(800);
  await run(phone,`libraryOpen('${data.book_id}')`);
  await until(phone,"$('pairScreen').hidden&&$('mobileBookLibrary').open&&studyforgeBookLibrary.nodes.length===4");
  const mobile=await run(phone,contrastCode);
  assert(mobile.contrast>=4.5,JSON.stringify(mobile));
  await shot(phone,'phone-book-library-320');
  await run(phone,"document.querySelector('#mobileBookLibrary .book-reading-toolbar').scrollIntoView({block:'start'})");
  await shot(phone,'phone-book-library-nodes-320');
  assert.equal(errors.length,0,errors.join('\n'));
  const report={passed:true,checks:['mobile upload text contrast','desktop night surface colors','mobile node controls'],desktop,mobile,night,console_errors:errors};
  fs.writeFileSync(path.join(folder,'visual-report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));pc.destroy();phone.destroy();app.quit();
 }catch(e){console.error(e);await shot(pc,'failed-visual-desktop');if(phone.webContents.getURL())await shot(phone,'failed-visual-phone');pc.destroy();phone.destroy();app.exit(1);}
});
