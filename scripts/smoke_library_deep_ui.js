/* Genuine UI/API jobs; fixed model responses keep this acceptance repeatable. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-deep'));app.disableHardwareAcceleration();app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
const pass=text=>{checks.push(text);fs.appendFileSync(path.join(folder,'deep-ui-log.txt'),text+'\n');};
async function until(w,c){for(let i=0;i<400;i++){if(await run(w,c))return;await sleep(100);}throw new Error('UI wait failed: '+c);}
function watch(w){w.webContents.on('console-message',e=>{if(e.level==='error'&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const image=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(image.data,'base64'));}
async function choose(w,id){await run(w,`libraryOpen('${id}')`);await until(w,`studyforgeBookLibrary.loadedBook==='${id}'&&Boolean($('bookReadingDepth'))`);}
function draft(focus){return `{studyforgeBookLibrary.selected=new Set(['${data.field_node_id}']);$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));$('bookReadingDepth').value='deep';$('bookReadingDepth').dispatchEvent(new Event('change'));$('bookReadingFocus').value=${JSON.stringify(focus)};$('bookReadingFocus').dispatchEvent(new Event('input'));const node=document.querySelector('[data-book-select="${data.field_node_id}"]');node.checked=true;node.dispatchEvent(new Event('change'));}`;}
async function notes(w){await run(w,`document.querySelector('[data-book-notes="${data.field_node_id}"]').click()`);await until(w,"$('bookNotesVersion')&&!$('bookNotesDeepen').disabled");}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc,data.book_id);
  assert(await run(pc,"$('bookReadingDepth').value==='index'&&$('bookReadingFocusLabel').hidden"));pass('Default reading remains a compact index; focus input is hidden');
  await run(pc,draft('ORIGINAL_FOCUS：为什么定义需要非零除数？'));
  await choose(pc,data.second_book_id);assert(await run(pc,"$('bookReadingDepth').value==='index'&&$('bookReadingFocus').value===''"));await choose(pc,data.book_id);
  assert(await run(pc,"$('bookReadingDepth').value==='deep'&&$('bookReadingFocus').value.includes('ORIGINAL_FOCUS')"));pass('Question drafts and depth follow their book; another book starts with an empty draft');
  await run(pc,"$('readBookNodes').click();$('bookReadingFocus').value='LATER_DRAFT_ONLY';$('bookReadingFocus').dispatchEvent(new Event('input'))");
  await until(pc,"studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&j.status==='running')");
  const job=await run(pc,"studyforgeBookLibrary.jobs.find(j=>j.kind==='read').id");
  await run(pc,`document.querySelector('[data-book-job="${job}"][data-action="pause"]').click()`);
  await until(pc,`studyforgeBookLibrary.jobs.some(j=>j.id==='${job}'&&j.status==='paused')`);
  await notes(pc);assert(await run(pc,"$('bookNotesBody').textContent.includes('OLD_INDEX_AVAILABLE')&&$('bookNotesVersion').options.length===1"));await run(pc,"$('bookNotesDialog').close()");
  pass('A paused deep reading preserves the existing index and does not publish partial notes');
  await run(pc,`document.querySelector('[data-book-job="${job}"][data-action="resume"]').click()`);await until(pc,`studyforgeBookLibrary.jobs.some(j=>j.id==='${job}'&&j.status==='completed')`);
  const first=await run(pc,"api('/__library_test__/calls')");assert.equal(first.calls.length,1);assert(first.calls[0].messages.at(-1).content.includes('ORIGINAL_FOCUS'));assert(!first.calls[0].messages.at(-1).content.includes('LATER_DRAFT_ONLY'));assert(!first.calls[0].messages.at(-1).content.includes('OLD_INDEX_AVAILABLE'));assert(!first.calls[0].messages.at(-1).content.includes('UNRELATED_BOTTOM'));
  pass('The actual request contains selected original text and frozen focus; resume makes no duplicate request');
  await notes(pc);assert(await run(pc,"$('bookNotesVersion').options.length===2&&$('bookNotesBody').querySelectorAll('.katex').length>0&&!$('bookNotesBody').querySelector('.katex-error')"));
  await shot(pc,'desktop-deep-notes');
  await run(pc,`$('bookNotesVersion').value='${data.index_reading_id}';$('bookNotesVersion').dispatchEvent(new Event('change'))`);await until(pc,"$('bookNotesBody').textContent.includes('OLD_INDEX_AVAILABLE')");
  await run(pc,"$('bookNotesDeepen').click()");assert(await run(pc,"!$('bookNotesDialog').open&&$('bookReadingDepth').value==='deep'&&studyforgeBookLibrary.selected.size===1"));pass('Old and deep versions switch without model calls; the deepen shortcut selects only its node');
  await run(pc,draft('SECOND_FOCUS：封闭性到底排除了什么？')+"$('readBookNodes').click()");await until(pc,"studyforgeBookLibrary.jobs.filter(j=>j.kind==='read'&&j.status==='completed').length===2");
  await notes(pc);assert(await run(pc,"$('bookNotesVersion').options.length===3&&$('bookNotesBody').textContent.includes('SECOND_FOCUS')"));await run(pc,"$('bookNotesDialog').close()");pass('A second focus produces an independent saved version');
  await run(pc,"$('bookReadingDepth').value='index';$('bookReadingDepth').dispatchEvent(new Event('change'));$('readBookNodes').click()");await until(pc,"studyforgeBookLibrary.jobs.filter(j=>j.kind==='read'&&j.status==='completed').length===3");assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,2);await notes(pc);assert(await run(pc,"$('bookNotesBody').textContent.includes('OLD_INDEX_AVAILABLE')&&!$('bookNotesBody').textContent.includes('DEEP_ORIGINAL_AVAILABLE')"));await run(pc,"$('bookNotesDialog').close()");pass('Choosing index again reuses and visibly opens the index instead of showing deep notes');
  await pc.reload();await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc,data.book_id);await notes(pc);assert(await run(pc,"$('bookNotesVersion').options.length===3"));await run(pc,"$('bookNotesDialog').close()");pass('All completed reading versions survive a page reload');
  await run(pc,`document.querySelector('[data-book-notes="${data.field_node_id}"]').click();$('bookNotesDialog').close();document.querySelector('[data-book-notes="${data.field_node_id}"]').click()`);await until(pc,"$('bookNotesVersion')&&!$('bookNotesDeepen').disabled");assert(await run(pc,"$('bookNotesBody').textContent.includes('OLD_INDEX_AVAILABLE')"));await run(pc,"$('bookNotesDialog').close()");pass('Immediate close/reopen does not let a delayed close event clear or abort the new note');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='精读验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");await choose(phone,data.book_id);
  await run(phone,"$('bookReadingDepth').value='deep';$('bookReadingDepth').dispatchEvent(new Event('change'))");
  const before=await run(phone,"$('messages').children.length");
  for(const width of [390,320]){
   phone.setSize(width,844);await notes(phone);await until(phone,"$('bookNotesBody').querySelector('.katex')");
   assert(await run(phone,"$('bookNotesDialog').scrollWidth-$('bookNotesDialog').clientWidth<=1&&$('bookNotesVersion').options.length===3&&!$('bookNotesBody').querySelector('.katex-error')"));
   await run(phone,"$('bookNotesDialog').querySelector('.book-dialog-body').scrollTop=500");assert(await run(phone,"$('bookNotesDialog').querySelector('.book-dialog-body').scrollTop>0"));await shot(phone,'phone-deep-'+width);await run(phone,"$('bookNotesDialog').close()");
   assert.equal(await run(phone,"$('messages').children.length"),before);pass(`Paired phone ${width}px shows, switches and scrolls saved formula notes without inserting chat messages`);
  }
  await run(phone,draft('PHONE_FOCUS：怎样从定义检查一个数集？')+"$('readBookNodes').click()");await until(phone,"studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&j.payload.focus?.startsWith('PHONE_FOCUS')&&j.status==='completed')");
  await notes(phone);assert(await run(phone,"$('bookNotesVersion').options.length===4&&$('bookNotesBody').textContent.includes('PHONE_FOCUS')"));await shot(phone,'phone-deep-new-focus');pass('Paired phone submits a real independent deep-reading job and receives its saved version');
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,3);assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'deep-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:3},null,2));windows.forEach(w=>w.destroy());app.exit(0);
 }catch(e){fs.writeFileSync(path.join(folder,'deep-ui-report.json'),JSON.stringify({passed:false,error:e.stack||String(e),checks,console_errors:errors},null,2));for(const [i,w] of windows.entries())if(w.webContents.getURL())await shot(w,'deep-failed-'+i);windows.forEach(w=>w.destroy());app.exit(1);}
});
