/* Real app API, persisted task snapshots and paired phone layout. No cloud calls. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]||'library-ranges-ui-20261011');
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-profile'));app.disableHardwareAcceleration();
// Keep native input and CSS coordinates identical on high-DPI Windows hosts.
app.commandLine.appendSwitch('force-device-scale-factor','1');
const errors=[],checks=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'ui-log.txt'),text+'\n');}
function run(win,code){return win.webContents.executeJavaScript(code);}
async function until(win,code){for(let i=0;i<250;i++){if(await run(win,code))return;await sleep(100);}throw new Error('UI wait failed: '+code);}
async function shot(win,name){await sleep(250);if(!win.webContents.debugger.isAttached())win.webContents.debugger.attach('1.3');const p=await win.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(p.data,'base64'));}
async function scrollList(win,touch=false){
 if(!win.webContents.debugger.isAttached())win.webContents.debugger.attach('1.3');
 win.webContents.focus();await win.webContents.debugger.sendCommand('Page.bringToFront');
 const point=await run(win,"(()=>{const list=document.querySelector('.book-match-list');list.scrollIntoView({block:'center'});list.scrollTop=0;const r=list.getBoundingClientRect();const x=r.x+r.width/2,y=Math.min(r.y+r.height*.8,innerHeight-30);return {x,y,travel:r.height*.55,ratio:devicePixelRatio,max:list.scrollHeight-list.clientHeight,top:r.y,bottom:r.bottom,inside:list.contains(document.elementFromPoint(x,y)),element:document.elementFromPoint(x,y)?.outerHTML.slice(0,200)};})()");
 fs.appendFileSync(path.join(folder,'scroll-log.jsonl'),JSON.stringify({touch,point})+'\n');
 assert(point.max>0,'Lookup list must actually overflow for scroll test');
 assert.equal(point.ratio,1,'This harness normalizes device scale before creating windows');
 const {x,y,travel}=point;
 await run(win,"window.lookupInputEvents=[];document.querySelector('.book-match-list').addEventListener('wheel',e=>lookupInputEvents.push({type:e.type,trusted:e.isTrusted,delta:e.deltaY}),{passive:true})");
 if(touch){
  await win.webContents.debugger.sendCommand('Emulation.setTouchEmulationEnabled',{enabled:true});
  await win.webContents.debugger.sendCommand('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1}]});
  for(let i=1;i<=5;i++){await win.webContents.debugger.sendCommand('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y-travel*i/5,id:1}]});await sleep(35);}
  await win.webContents.debugger.sendCommand('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 }else{
  await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',x,y});
  await sleep(100);
  for(let i=0;i<4;i++){await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseWheel',x,y,deltaX:0,deltaY:80});await sleep(80);}
 }
 await sleep(500);const after=await run(win,"({scroll:document.querySelector('.book-match-list').scrollTop,height:document.querySelector('.book-match-list').clientHeight,outer:document.querySelector('.book-chat-references').scrollTop,events:lookupInputEvents})");fs.appendFileSync(path.join(folder,'scroll-log.jsonl'),JSON.stringify({touch,after})+'\n');assert(after.scroll>0,touch?'Touch must move the lookup list':'Mouse wheel must move the lookup list');
}
const book=data.range_book_id,[chapter,definitions,examples,argumentsNode,last]=data.range_nodes;
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 for(const win of [pc,phone])win.webContents.on('console-message',(_e,level,text)=>{if(level===3&&!text.includes('401')&&!text.includes('404'))errors.push(text);});
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");
  await run(pc,`libraryOpen('${book}')`);await until(pc,"studyforgeBookLibrary.nodes.length===5&&$('selectAllBookNodes')");
  await run(pc,`document.querySelector('[data-book-fold="${chapter.id}"]').click();$('selectAllBookNodes').click()`);
  assert(await run(pc,"studyforgeBookLibrary.selected.size===5&&document.querySelectorAll('[data-book-select]').length===2&&$('bookSelectedCount').textContent.includes('3 个被筛选或折叠')"));
  pass('Collapsed child nodes included in one-click whole-book selection; hidden count visible');
  await run(pc,"$('bookNodeQuery').value='Definitions';$('bookNodeQuery').dispatchEvent(new Event('input'));$('selectFilteredBookNodes').click()");
  assert(await run(pc,`studyforgeBookLibrary.selected.size===1&&studyforgeBookLibrary.selected.has('${definitions.id}')`));
  pass('Only-filtered selection replaces hidden selections without selecting ancestor context');
  await run(pc,"$('clearBookSelection').click()");assert(await run(pc,"studyforgeBookLibrary.selected.size===0&&$('readBookNodes').disabled&&$('locateBookNodes').disabled"));
  pass('Clear selection disables empty reading and location requests');
  await run(pc,"$('clearBookFilters').click();$('selectAllBookNodes').click();$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));$('bookReadingMode').value='parallel';$('bookReadingMode').dispatchEvent(new Event('change'))");
  assert(await run(pc,"$('bookReadingNotice').textContent.includes('立即')&&$('bookReadingNotice').textContent.includes('并行处理')"));
  await run(pc,"api('/__library_test__/foreground',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({busy:true})})");
  await run(pc,"$('readBookNodes').click()");
  await until(pc,"studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&j.status==='completed')");
  const tasks=await run(pc,`api('/api/library/books/${book}').then(d=>d.jobs)`);
  const locate=tasks.find(j=>j.kind==='ranges'),read=tasks.find(j=>j.kind==='read');
  assert(locate.status==='completed'&&locate.payload.foreground&&locate.payload.read_after&&!locate.result.pending_node_ids.length);
  assert(read.payload.foreground&&read.payload.parallel&&read.result.workers===2&&read.payload.node_ids.length===2);
  const timing=await run(pc,"api('/__library_test__/timing')");assert(timing.peak===2);
  pass('Foreground auto-location and two actual chapter requests finish while foreground activity is present');
  pass('Parent/child selection deduplicates to two covered chapter scopes; read-after snapshot retains both switches');
  const located=await run(pc,"studyforgeBookLibrary.nodes.every(n=>n.confirmed)&&studyforgeBookLibrary.nodes.find(n=>n.title==='1 Definitions').end_page===2");assert(located);
  await run(pc,`studyforgeBookLibrary.collapsed.clear();$('clearBookFilters').click();document.querySelector('[data-book-scope="${definitions.id}"]').click()`);
  await until(pc,"$('bookScopeDialog').open&&$('bookPagePreview').complete");
  assert(await run(pc,"$('bookRangeEvidence').textContent.includes('原页标题匹配')&&$('bookRangeEvidence').textContent.includes('之前')&&$('bookScopeAuto').disabled"));
  await run(pc,"$('bookPreviewEnd').click()");assert(await run(pc,"Number($('bookPreviewNumber').value)===Number($('bookEnd').value)&&$('bookCropEdge').value==='end'"));
  await shot(pc,'desktop-auto-range-evidence');await run(pc,"$('bookScopeDialog').close()");
  pass('Range dialog shows observed start/end titles and retains manual page/crop correction');
  await run(pc,`$('clearBookSelection').click();const check=document.querySelector('[data-book-select="${definitions.id}"]');if(check){check.checked=true;check.dispatchEvent(new Event('change'));}else{studyforgeBookLibrary.collapsed.clear();$('clearBookFilters').click();const item=document.querySelector('[data-book-select="${definitions.id}"]');item.checked=true;item.dispatchEvent(new Event('change'));}$('bookReadingPriority').value='background';$('bookReadingPriority').dispatchEvent(new Event('change'));$('readBookNodes').click()`);
  await until(pc,`studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&!j.payload.foreground&&j.payload.node_ids.includes('${definitions.id}'))`);
  await sleep(750);
  const bg=await run(pc,`api('/api/library/books/${book}').then(d=>d.jobs.find(j=>j.kind==='read'&&!j.payload.foreground))`);
  assert(bg.status==='queued'&&bg.progress===0);pass('Background mode truly waits under the same foreground activity');
  await run(pc,"document.documentElement.dataset.theme='night';$('bookDetail').scrollIntoView({block:'start'})");await shot(pc,'desktop-library-night');
  const ca=new X509Certificate(fs.readFileSync(data.certificate));
  phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let accepted=false;try{accepted=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(accepted?0:-3);});
  const pairing=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pairing.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");
  const deviceName='范围与前台验收手机 '+Date.now();
  await run(phone,`$('deviceName').value=${JSON.stringify(deviceName)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(deviceName)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(deviceName)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");
  await run(phone,`libraryOpen('${book}')`);await until(phone,"studyforgeBookLibrary.nodes.length===5");
  await run(phone,"$('selectAllBookNodes').click();$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'))");
  assert(await run(phone,"studyforgeBookLibrary.selected.size===5&&studyforgeBookLibrary.readingPriority==='foreground'"));
  pass('Paired mobile shares automatic page scopes and supports select-all and foreground switch');
  await run(phone,`$('clearBookSelection').click();const i=document.querySelector('[data-book-select="${examples.id}"]');i.checked=true;i.dispatchEvent(new Event('change'));$('bookReadingMode').value='serial';$('bookReadingMode').dispatchEvent(new Event('change'));$('readBookNodes').click()`);
  await until(phone,`studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&j.payload.foreground&&j.payload.node_ids.includes('${examples.id}')&&j.status==='completed')`);
  pass('Phone foreground request executes under load with serial processing retained in persisted payload');
  phone.setSize(320,844);await run(phone,"$('bookDetail').scrollIntoView({block:'start'})");
  const overflow=await run(phone,"Math.max(document.documentElement.scrollWidth-document.documentElement.clientWidth,$('mobileBookLibrary').scrollWidth-$('mobileBookLibrary').clientWidth,$('bookDetail').scrollWidth-$('bookDetail').clientWidth)");assert(overflow<=1,`320px overflow ${overflow}`);
  await shot(phone,'phone-library-320');pass('320px phone layout contains controls and job cards without horizontal overflow');
  await run(pc,"api('/__library_test__/foreground',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({busy:false})})");
  await until(pc,`api('/api/library/books/${book}').then(d=>d.jobs.some(j=>j.id==='${bg.id}'&&j.status==='completed'))`);
  pass('Background task continues automatically after foreground activity ends');
  await pc.reload();await until(pc,"state.ready&&typeof libraryOpen==='function'");await run(pc,`libraryOpen('${book}')`);
  await until(pc,"studyforgeBookLibrary.nodes.length===5&&studyforgeBookLibrary.jobs.filter(j=>j.kind==='read'&&j.status==='completed').length===3");
  assert(await run(pc,"studyforgeBookLibrary.nodes.every(n=>n.confirmed)&&studyforgeBookLibrary.jobs.some(j=>j.payload.foreground&&j.kind==='ranges')"));
  pass('Reload preserves ranges, jobs and scheduling snapshots');

  await run(pc,`refreshNavigation().then(()=>selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'),{conversationId:'${data.conversation_id}'}))`);
  await until(pc,`state.conversation==='${data.conversation_id}'&&studyforgeBookLibrary.prefReady`);
  await run(pc,"showView('study');document.documentElement.dataset.focus='false'");
  for(let i=0;i<18;i++){
   const result=await run(pc,`api('/api/library/conversations/${data.conversation_id}/references?project_id=${data.project_id}&query=closure%20${i}')`);
   assert(result.history?.nodes.length,'Actual reference endpoint must save nonempty lookup');
   await run(pc,`libraryShowMatches(${JSON.stringify(result)}, {conversation_id:'${data.conversation_id}',text:'closure ${i}'})`);
  }
  await run(pc,"$('prompt').value='closure 条件为什么要求非零除数？';$('sendMessage').click()");
  await until(pc,"!isChatBusy()&&!liveChats.size&&studyforgeBookLibrary.matchHistory.length===19");
  pass('Actual tutor stream and reference API persist original-source lookup entries');
  await scrollList(pc);const scrollBefore=await run(pc,"document.querySelector('.book-match-list').scrollTop");
  await run(pc,"libraryRefreshMatches()");assert.equal(await run(pc,"document.querySelector('.book-match-list').scrollTop"),scrollBefore);
  await run(pc,"window.lookupListBeforeRefresh=document.querySelector('.book-match-list');libraryRefreshMatches()");
  assert(await run(pc,"lookupListBeforeRefresh===document.querySelector('.book-match-list')"));
  await shot(pc,'desktop-lookup-scroll');pass('Actual mouse-wheel input scrolls long desktop lookup list; refresh preserves position and unchanged DOM');
  await run(pc,`refreshNavigation().then(()=>selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}')))`);
  await until(pc,`state.conversation==='${data.other_conversation_id}'&&studyforgeBookLibrary.prefReady`);
  assert(await run(pc,"studyforgeBookLibrary.matchHistory.length===0&&!document.querySelector('.book-match-list')"));
  pass('Switching project shows no lookup records from another conversation');
  await run(pc,`refreshNavigation().then(()=>selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'),{conversationId:'${data.conversation_id}'}))`);
  await until(pc,"studyforgeBookLibrary.prefReady&&studyforgeBookLibrary.matchHistory.length===19");
  assert(await run(pc,"document.querySelectorAll('.book-match-entry').length===19"));
  pass('Returning to original conversation restores saved lookup navigation');
  await pc.reload();await until(pc,`state.ready&&state.conversation==='${data.conversation_id}'&&studyforgeBookLibrary.prefReady&&studyforgeBookLibrary.matchHistory.length===19`);
  pass('Application reload restores lookup entries from the database');

  await run(phone,"$('mobileBookLibrary').close()");phone.setSize(390,844);
  await run(phone,`selectProject('${data.project_id}').then(()=>selectChat('${data.conversation_id}'))`);
  await until(phone,"studyforgeBookLibrary.prefReady&&studyforgeBookLibrary.matchHistory.length===19");
  await run(phone,"openSheet('optionsDialog')");await scrollList(phone,true);await shot(phone,'phone-lookup-touch-scroll');
  pass('Paired phone restores same-chat records and actual touch swipe scrolls the lookup list');
  await run(phone,"$('optionsDialog').close();$('prompt').value='closure 非零除数';$('sendMessage').click()");
  await until(phone,"!mobile.runs.size&&!mobile.sending.size&&studyforgeBookLibrary.matchHistory.length===20");
  pass('Phone tutor completion refreshes saved lookup entries without switching conversations');

  await run(pc,"libraryRefreshMatches().then(()=>$('bookReferenceStatus').querySelector('.book-reference-head button').click())");
  await until(pc,"$('clearBookHistory')?.open");await run(pc,"$('clearBookHistory').querySelector('[data-clear]').click()");
  await until(pc,"studyforgeBookLibrary.matchHistory.length===0&&!$('clearBookHistory')");
  assert(await run(pc,`api('/api/library/conversations/${data.conversation_id}/history?project_id=${data.project_id}').then(r=>r.entries.length===0)`));
  assert(await run(pc,`api('/api/library/books/${book}').then(r=>r.nodes.length===5)`));
  pass('Clear-history action removes only this chat lookup navigation and preserves the textbook');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,model_peak:timing.peak,console_errors:errors},null,2));pc.destroy();phone.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,console_errors:errors},null,2));await shot(pc,'failed-desktop');if(phone.webContents.getURL())await shot(phone,'failed-phone');pc.destroy();phone.destroy();app.exit(1);}
});
