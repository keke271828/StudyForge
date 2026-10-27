/* Real desktop and paired mobile navigation/notes checks; no paid model calls. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]);
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-continuity'));app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),windows=[];
const run=(w,c)=>w.webContents.executeJavaScript(c);
const pass=text=>{checks.push(text);fs.appendFileSync(path.join(folder,'continuity-log.txt'),text+'\n');};
async function until(w,c){for(let i=0;i<300;i++){if(await run(w,c))return;await sleep(100);}throw new Error('UI wait failed: '+c);}
function debug(w){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');}
async function shot(w,name){debug(w);const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
async function wheel(w,selector,deltaY){debug(w);const p=await run(w,`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round((Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2)};})()`);await w.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseMoved',...p});await w.webContents.debugger.sendCommand('Input.dispatchMouseEvent',{type:'mouseWheel',...p,deltaX:0,deltaY});await sleep(180);}
async function lag(pc,path,seconds=1.2,remaining=1){await run(pc,`api('/__library_test__/lag',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:${JSON.stringify(path)},seconds:${seconds},remaining:${remaining}})})`);}
async function choose(w,book){await run(w,`libraryOpen('${book}')`);await until(w,`studyforgeBookLibrary.loadedBook==='${book}'&&Boolean($('bookNodeQuery'))`);}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:850,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);
 const note=data.field_node_id,other=data.polynomial_node_id,b=data.book_id,q=data.second_book_id;
 function watch(w){w.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
 watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc,b);
  await run(pc,`{const e=document.querySelector('[data-book-select="${note}"]');e.checked=true;e.dispatchEvent(new Event('change'));$('bookNodeQuery').value='fields';$('bookNodeQuery').dispatchEvent(new Event('input'));}`);
  await choose(pc,b);assert(await run(pc,`studyforgeBookLibrary.selected.has('${note}')&&$('bookNodeQuery').value==='fields'`));
  await run(pc,"showView('study')");await choose(pc,b);assert(await run(pc,`studyforgeBookLibrary.selected.has('${note}')&&$('bookNodeQuery').value==='fields'`));
  pass('Reopening the same book and leaving/returning retain selected chapters and filter');
  await run(pc,"$('clearBookFilters').click();$('bookDetail').scrollTop=420");const scroll=await run(pc,"$('bookDetail').scrollTop");assert(scroll>0);
  await choose(pc,q);assert.equal(await run(pc,"studyforgeBookLibrary.selected.size"),0);
  const qid=data.second_nodes[3].id;
  await run(pc,`{const e=document.querySelector('[data-book-select="${qid}"]');e.checked=true;e.dispatchEvent(new Event('change'));$('bookNodeQuery').value='04';$('bookNodeQuery').dispatchEvent(new Event('input'));}`);
  await choose(pc,b);assert(await run(pc,`studyforgeBookLibrary.selected.has('${note}')&&!studyforgeBookLibrary.selected.has('${qid}')&&$('bookNodeQuery').value===''`));assert(Math.abs(await run(pc,"$('bookDetail').scrollTop")-scroll)<=1);
  await choose(pc,q);assert(await run(pc,`studyforgeBookLibrary.selected.has('${qid}')&&!studyforgeBookLibrary.selected.has('${note}')&&$('bookNodeQuery').value==='04'`));
  pass('Different books keep independent checkbox/filter/scroll drafts without crossing selections');
  await choose(pc,b);await run(pc,`{const e=document.querySelector('[data-book-select="${data.extra_node_ids[0]}"]');e.checked=true;e.dispatchEvent(new Event('change'));}api('/__library_test__/remove-extra',{method:'POST'})`);await choose(pc,b);
  assert(!(await run(pc,`studyforgeBookLibrary.selected.has('${data.extra_node_ids[0]}')`)));pass('A removed node is pruned from the retained selection');
  await lag(pc,'/api/library/books/'+q,1.4);
  await run(pc,`window.slowBookOpen=libraryOpen('${q}');void 0`);await sleep(180);await choose(pc,b);await sleep(1600);
  assert.equal(await run(pc,"studyforgeBookLibrary.book.id"),b);assert.equal(await run(pc,"studyforgeBookLibrary.loadedBook"),b);
  pass('A delayed old book response cannot take over the newer selection');
  await run(pc,`document.querySelector('[data-book-notes="${note}"]').click()`);await until(pc,"$('bookNotesDialog').open&&$('bookNotesBody').querySelector('.katex')");
  assert(await run(pc,"$('bookNotesBody').querySelectorAll('.katex-error').length===0&&!window.unsafeNoteExecuted"));
  assert(await run(pc,"$('bookNotesBody').querySelector('.book-notes-source').textContent.includes('Number fields')"));
  const messages=await run(pc,"$('messages').children.length");
  await wheel(pc,'#bookNotesDialog>.book-dialog-body',1100);assert(await run(pc,"$('bookNotesDialog').querySelector('.book-dialog-body').scrollTop>0"));
  assert(await run(pc,"(()=>{const d=$('bookNotesDialog').getBoundingClientRect(),f=$('bookNotesReference').getBoundingClientRect(),h=$('bookNotesDialog').querySelector('.book-dialog-head').getBoundingClientRect();return f.bottom<=d.bottom&&h.top>=d.top;})()"));
  await shot(pc,'desktop-notes');pass('Desktop notes render formulas safely and scroll while header/actions remain visible');
  await run(pc,"$('bookNotesReference').click()");await until(pc,`studyforgeBookLibrary.pref.references.some(r=>r.node_id==='${note}')&&!$('bookNotesReference').disabled`);
  assert.equal(await run(pc,"$('messages').children.length"),messages);pass('A note can become a conversation reference without inserting notes into chat');
  await run(pc,"$('bookNotesOriginal').click()");await until(pc,"$('bookScopeDialog').open&&$('bookPagePreview').dataset.ready==='true'");
  assert(await run(pc,"$('bookScopeForm').querySelector('button[type=submit]').hidden&&$('bookScopeConfirmed').disabled"));
  await run(pc,"$('bookScopeDialog').close()");pass('The note original-page shortcut opens a read-only preview');
  await lag(pc,'/api/library/nodes/'+note+'/notes',1.2);
  await run(pc,`document.querySelector('[data-book-notes="${note}"]').click()`);await until(pc,"$('bookNotesDialog').open");await run(pc,"$('bookNotesDialog').close()");await sleep(1500);
  assert(await run(pc,"!$('bookNotesDialog').open&&$('bookNotesBody').children.length===0"));pass('Closing during note loading aborts the request and never reopens the old window');
  await lag(pc,'/api/library/nodes/'+note+'/notes',1.2);
  await run(pc,`document.querySelector('[data-book-notes="${note}"]').click();document.querySelector('[data-book-notes="${other}"]').click()`);await until(pc,"$('bookNotesBody').textContent.includes('SECOND_NOTE_ONLY')");await sleep(1400);
  assert(await run(pc,"$('bookNotesBody').textContent.includes('SECOND_NOTE_ONLY')&&!$('bookNotesBody').textContent.includes('整理片段 60')"));await run(pc,"$('bookNotesDialog').close()");pass('A slower previous note cannot overwrite the most recently opened node');
  const calls=await run(pc,"api('/__library_test__/calls').then(r=>r.calls.length)");assert.equal(calls,0);
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='阅读笔记验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");await choose(phone,b);
  await run(phone,`{const e=document.querySelector('[data-book-select="${note}"]');e.checked=true;e.dispatchEvent(new Event('change'));}$('mobileBookLibrary').close()`);await choose(phone,b);
  assert(await run(phone,`studyforgeBookLibrary.selected.has('${note}')`));pass('The paired phone retains chapter selection after closing/reopening its library');
  const phoneMessages=await run(phone,"$('messages').children.length");
  for(const width of [390,320]){
    phone.setSize(width,844);await run(phone,`document.querySelector('[data-book-notes="${note}"]').click()`);await until(phone,"$('bookNotesDialog').open&&$('bookNotesBody').querySelector('.katex')");
    assert(await run(phone,"$('bookNotesBody').querySelectorAll('.katex-error').length===0&&$('bookNotesDialog').scrollWidth-$('bookNotesDialog').clientWidth<=1"));
    await wheel(phone,'#bookNotesDialog>.book-dialog-body',900);assert(await run(phone,"$('bookNotesDialog').querySelector('.book-dialog-body').scrollTop>0"));
    assert.equal(await run(phone,"$('messages').children.length"),phoneMessages);await shot(phone,'phone-notes-'+width);await run(phone,"$('bookNotesDialog').close()");pass(`Paired phone ${width}px renders and scrolls long formula notes without polluting chat`);
  }
  await run(phone,`document.querySelector('[data-book-notes="${note}"]').click()`);await until(phone,"$('bookNotesDialog').open&&$('bookNotesBody').querySelector('.katex')");await run(phone,"$('bookNotesOriginal').click()");await until(phone,"$('bookScopeDialog').open&&$('bookPagePreview').dataset.ready==='true'");assert(await run(phone,"$('bookScopeConfirmed').disabled"));await run(phone,"$('bookScopeDialog').close()");pass('Phone notes also open the actual original page with editing disabled');
  assert.equal(await run(pc,"api('/__library_test__/calls').then(r=>r.calls.length)"),0);assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'continuity-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:0},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(e){fs.writeFileSync(path.join(folder,'continuity-ui-report.json'),JSON.stringify({passed:false,error:e.stack||String(e),checks,console_errors:errors},null,2));await shot(pc,'continuity-failed-desktop');for(const w of windows.slice(1))if(w.webContents.getURL())await shot(w,'continuity-failed-phone');windows.forEach(w=>w.destroy());app.exit(1);}
});
