/* Real DOM/API verification of grouped review and partial reading. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]||'library-range-review-ui-20261011-1');
const data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-profile-review'));app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
function pass(text){checks.push(text);fs.appendFileSync(path.join(folder,'review-log.txt'),text+'\n');}
async function until(w,c){for(let i=0;i<300;i++){if(await run(w,c))return;await sleep(100);}throw new Error('UI wait failed: '+c);}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
const book=data.review_book_id,[chapter,definitions,examples,argumentsNode,last,absent]=data.review_nodes;
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
 const ca=new X509Certificate(fs.readFileSync(data.certificate));
 phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let accepted=false;try{accepted=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(accepted?0:-3);});
 for(const win of [pc,phone])win.webContents.on('console-message',(_e,level,text)=>{if(level===3&&!text.includes('401')&&!text.includes('404'))errors.push(text);});
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");
  await run(pc,`libraryOpen('${book}')`);await until(pc,"studyforgeBookLibrary.nodes.length===6&&$('reviewBookRanges')");
  assert(await run(pc,"$('reviewBookRanges').disabled&&!$('completeBookRanges').disabled"));
  assert(await run(pc,"$('bookRangeAI').checked===false"));
  pass('Unlocated nodes are separated from actual failed boundary proposals');
  await run(pc,`for(const id of ${JSON.stringify([definitions.id,examples.id,argumentsNode.id,absent.id])}){const i=document.querySelector('[data-book-select="'+id+'"]');i.checked=true;i.dispatchEvent(new Event('change'));}$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));$('readBookNodes').click();`);
  await until(pc,"studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&j.status==='completed')");
  const jobs=await run(pc,`api('/api/library/books/${book}').then(r=>r.jobs)`),locate=jobs.find(j=>j.kind==='ranges'),read=jobs.find(j=>j.kind==='read');
  assert.deepEqual(read.payload.node_ids,[argumentsNode.id]);assert.equal(locate.result.pending_node_ids.length,3);
  pass('One reliable selected section reads while three separate doubts remain; no unrelated chapters are read');
  await run(pc,`document.querySelector('[data-book-pending="${locate.id}"]').click()`);await until(pc,"$('bookRangeReviewDialog').open&&document.querySelectorAll('[data-review-node]').length===3");
  assert(await run(pc,`document.querySelector('[data-review-check="${absent.id}"]').disabled&&document.querySelector('[data-review-check="${definitions.id}"]').checked===false`));
  await until(pc,"Array.from($('bookRangeReviewEvidence').querySelectorAll('img')).every(i=>i.complete&&i.naturalWidth>0)");
  assert.equal(await run(pc,"$('bookRangeReviewEvidence').querySelectorAll('img').length"),2);
  assert(await run(pc,"$('bookReviewConfirm').disabled&&$('bookReviewRead').disabled"));
  await shot(pc,'desktop-review');
  pass('Only current boundary pair loads; missing boundaries cannot be batch approved and nothing is prechecked');
  await run(pc,`{const i=document.querySelector('[data-review-check="${definitions.id}"]');i.checked=true;i.dispatchEvent(new Event('change'));$('bookRangeReviewEvidence').querySelector('figcaption button').click();}`);
  await until(pc,"$('bookScopeDialog').open&&$('bookPagePreview').dataset.ready==='true'");
  assert(await run(pc,"$('bookNodeTitle').disabled&&$('bookScopeConfirmed').disabled&&$('bookScopeForm').querySelector('button[type=submit]').hidden"));
  await run(pc,"$('bookPagePreview').click();$('bookScopeDialog').close()");
  await until(pc,`$('bookRangeReviewDialog').open&&document.querySelector('[data-review-check="${definitions.id}"]').checked`);
  pass('Large original-page preview is read-only; returning preserves already reviewed unchanged scopes');
  for(const id of [definitions.id,examples.id])await run(pc,`{const i=document.querySelector('[data-review-check="${id}"]');i.checked=true;i.dispatchEvent(new Event('change'));}`);
  await run(pc,"$('bookReviewConfirm').click()");await until(pc,"!$('bookRangeReviewDialog').open");
  assert(await run(pc,`api('/api/library/books/${book}').then(r=>r.nodes.filter(n=>['${definitions.id}','${examples.id}'].includes(n.id)).every(n=>n.confirmed)&&r.nodes.find(n=>n.id==='${absent.id}').confirmed===0)`));
  pass('Two reviewed proposals confirm in one action; missing scope remains unconfirmed');
  await run(pc,`document.querySelector('[data-book-scope="${definitions.id}"]').click()`);await until(pc,"$('bookScopeDialog').open&&$('bookPagePreview').dataset.ready==='true'");
  assert(await run(pc,"$('bookScopeConfirmed').checked"));
  const before=await run(pc,`api('/api/library/books/${book}').then(r=>r.nodes.find(n=>n.id==='${definitions.id}'))`);
  await run(pc,"$('bookScopeForm').requestSubmit()");await until(pc,"!$('bookScopeDialog').open");
  const after=await run(pc,`api('/api/library/books/${book}').then(r=>r.nodes.find(n=>n.id==='${definitions.id}'))`);
  assert.equal(after.start_y,before.start_y);assert.equal(after.end_y,before.end_y);assert.equal(after.confirmed,1);
  pass('Opening and saving a confirmed scope preserves confirmation and precise crop coordinates');
  await run(pc,`document.querySelector('[data-book-scope="${definitions.id}"]').click()`);await until(pc,"$('bookPagePreview').dataset.ready==='true'");
  await run(pc,"$('bookPreviewNumber').value=3;$('bookPreviewPage').click();$('bookPagePreview').click()");
  assert.equal(await run(pc,"Number($('bookStart').value)"),after.start_page);
  await until(pc,"$('bookPagePreview').dataset.ready==='true'&&$('bookPagePreview').dataset.page==='3'");
  await run(pc,"$('bookScopeDialog').close()");
  pass('Clicking the old image while another page loads cannot change a crop');
  await run(pc,`api('/api/library/books/${book}').then(r=>{if(r.nodes.find(n=>n.id==='${definitions.id}').start_page!==${after.start_page})throw new Error('Preview altered the stored scope');})`);
  const name='范围核对验收手机 '+Date.now();
  const pairing=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pairing.pairing_code);
  await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");
  await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");await run(phone,`libraryOpen('${book}')`);await until(phone,"studyforgeBookLibrary.nodes.length===6");
  assert(await run(phone,`studyforgeBookLibrary.nodes.find(n=>n.id==='${definitions.id}').confirmed===1`));
  await run(phone,"$('reviewBookRanges').click()");await until(phone,"$('bookRangeReviewDialog').open");
  phone.setSize(320,844);await sleep(150);
  const overflow=await run(phone,"Math.max(document.documentElement.scrollWidth-document.documentElement.clientWidth,$('bookRangeReviewDialog').scrollWidth-$('bookRangeReviewDialog').clientWidth,$('bookRangeReviewEvidence').scrollWidth-$('bookRangeReviewEvidence').clientWidth)");assert(overflow<=1,`320px overflow ${overflow}`);
  await shot(phone,'phone-review-320');pass('Paired phone shows shared confirmation state and usable 320px review dialog');
  await run(phone,"$('bookRangeReviewDialog').close();$('mobileBookLibrary').close()");
  // Explicitly unconfirm one proposal; the phone must use its real permitted
  // batch endpoint before starting the new scoped reader.
  await run(pc,`api('/api/library/nodes/${examples.id}',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:false})})`);
  await run(phone,`libraryOpen('${book}')`);await until(phone,"studyforgeBookLibrary.nodes.length===6");await run(phone,"$('reviewBookRanges').click()");
  await until(phone,`$('bookRangeReviewDialog').open&&!document.querySelector('[data-review-check="${examples.id}"]').disabled`);
  await run(phone,`{document.querySelector('[data-review-node="${examples.id}"]').click();const i=document.querySelector('[data-review-check="${examples.id}"]');i.checked=true;i.dispatchEvent(new Event('change'));$('bookReviewRead').click();}`);
  await until(phone,`studyforgeBookLibrary.jobs.some(j=>j.kind==='read'&&j.payload.node_ids.includes('${examples.id}')&&j.status==='completed')`);
  pass('Phone batch confirmation endpoint and confirm-then-read execute successfully');
  assert(!errors.length,JSON.stringify(errors));
  fs.writeFileSync(path.join(folder,'review-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors},null,2));
  pc.destroy();phone.destroy();app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'review-ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,console_errors:errors},null,2));await shot(pc,'review-failed-desktop');if(phone.webContents.getURL())await shot(phone,'review-failed-phone');pc.destroy();phone.destroy();app.exit(1);}
});
