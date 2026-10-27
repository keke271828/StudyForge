/* Actual application DOM and paired TLS mobile; all contents work stays local. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-toc'));app.disableHardwareAcceleration();app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
const pass=t=>{checks.push(t);fs.appendFileSync(path.join(folder,'toc-ui-log.txt'),t+'\n');};
async function until(w,c){for(let i=0;i<400;i++){if(await run(w,c))return;await sleep(100);}throw new Error('UI wait failed: '+c);}
async function choose(w,id){await run(w,`libraryOpen('${id}')`);await until(w,`studyforgeBookLibrary.loadedBook==='${id}'&&Boolean($('bookNodeQuery'))`);}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
function watch(w){w.webContents.on('console-message',e=>{if(e.level==='error'&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:850,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc,data.auto_toc_book_id);
  assert(await run(pc,"studyforgeBookLibrary.nodes.length===0&&studyforgeBookLibrary.jobs.length===0&&$('bookAutoToc')&&!$('bookTocManual').open&&$('bookTocScanLimit').value==='32'"));
  await shot(pc,'desktop-toc-before');pass('Import without bookmarks stays unparsed and shows the automatic contents entry by default');
  await run(pc,"$('bookTocScanLimit').value='0';$('bookAutoToc').click()");await sleep(300);assert.equal(await run(pc,"studyforgeBookLibrary.jobs.length"),0);
  await run(pc,"$('bookTocScanLimit').value='32';$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));$('bookAutoToc').click()");
  await until(pc,"studyforgeBookLibrary.jobs.some(j=>j.status==='running')");assert(await run(pc,"$('bookAutoToc').disabled&&studyforgeBookLibrary.jobs[0].payload.auto_discover&&studyforgeBookLibrary.jobs[0].payload.foreground"));
  pass('Invalid bounds submit no task; explicit discovery uses the selected foreground priority and prevents duplicates');
  await run(pc,"document.querySelector('[data-book-job][data-action=pause]').click()");await until(pc,"studyforgeBookLibrary.jobs[0].status==='paused'");
  const paused=await run(pc,"api('/__library_test__/toc-stats').then(s=>s.probed.length)");await sleep(1000);assert.equal(await run(pc,"api('/__library_test__/toc-stats').then(s=>s.probed.length)"),paused);
  pass('Pausing discovery suspends new OCR steps while retaining completed progress');
  await run(pc,"document.querySelector('[data-book-job][data-action=resume]').click()");await until(pc,"studyforgeBookLibrary.nodes.length===6&&studyforgeBookLibrary.jobs[0].status==='completed'");
  assert(await run(pc,"studyforgeBookLibrary.jobs[0].result.toc_discovery.candidate_pages.join(',')==='3,4'&&studyforgeBookLibrary.nodes.every(n=>!n.confirmed&&!n.reading)"));
  assert(await run(pc,`document.querySelector('[data-book-open="${data.auto_toc_book_id}"] small').textContent.includes('6 个目录节点')`));
  const stats=await run(pc,"api('/__library_test__/toc-stats')");const firstProbes=stats.probed.filter(p=>p[0]===data.auto_toc_book_id).map(p=>p[1]);assert.equal(new Set(firstProbes).size,firstProbes.length);
  pass('Resuming creates one complete two-page directory, preserves unconfirmed scopes and reuses completed probes');
  await run(pc,"document.querySelector('.book-toc-evidence').open=true");await sleep(2300);assert(await run(pc,"document.querySelector('.book-toc-evidence').open"));
  await shot(pc,'desktop-toc-complete');await run(pc,"document.querySelector('[data-book-toc-page=\"3\"]').click()");await until(pc,"$('bookScopeDialog').open&&$('bookPagePreview').dataset.ready==='true'");assert(await run(pc,"$('bookScopeConfirmed').disabled"));await run(pc,"$('bookScopeDialog').close()");
  pass('Contents evidence remains expanded through polling and opens the actual source page without changing scope');
  await choose(pc,data.review_toc_book_id);await run(pc,"$('bookTocScanLimit').value='3';$('bookAutoToc').click()");await until(pc,"studyforgeBookLibrary.jobs[0]?.status==='completed'");
  assert(await run(pc,"studyforgeBookLibrary.nodes.length===0&&studyforgeBookLibrary.jobs[0].result.toc_discovery.status==='review'&&document.querySelector('.book-toc-evidence').open"));
  await run(pc,"document.querySelector('[data-book-toc-use]').click()");assert(await run(pc,"$('bookTocManual').open&&$('bookTocPages').value==='3'"));
  await run(pc,"$('bookTocPages').value='3-4';$('bookTocForm').requestSubmit()");await until(pc,"studyforgeBookLibrary.nodes.length===6");
  pass('A cut-off search waits for review; candidate pages prefill the manual correction and exact-page recognition still works');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='目录验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");await choose(phone,data.phone_toc_book_id);
  for(const width of [390,320]){phone.setSize(width,844);await run(phone,"$('bookAutoToc').scrollIntoView({block:'center'})");assert(await run(phone,"$('bookAutoToc')&&!$('bookTocManual').open&&$('bookDetail').scrollWidth-$('bookDetail').clientWidth<=1&&$('bookAutoToc').getBoundingClientRect().top>0&&$('bookAutoToc').getBoundingClientRect().bottom<innerHeight"));await shot(phone,'phone-toc-before-'+width);pass(`Paired phone ${width}px has a visible automatic/manual contents form without horizontal overflow`);}
  await run(phone,"$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));$('bookAutoToc').click()");await until(phone,"studyforgeBookLibrary.nodes.length===6&&studyforgeBookLibrary.jobs[0].status==='completed'");
  assert(await run(phone,"studyforgeBookLibrary.jobs[0].result.toc_discovery.candidate_pages.join(',')==='3,4'"));
  pass('The paired HTTPS phone runs the same real task and sees the completed directory');
  await run(phone,"document.querySelector('[data-book-toc-page=\"4\"]').click()");await until(phone,"$('bookScopeDialog').open&&$('bookPagePreview').dataset.ready==='true'");assert(await run(phone,"$('bookScopeConfirmed').disabled"));await shot(phone,'phone-toc-original');await run(phone,"$('bookScopeDialog').close()");
  const final=await run(pc,"api('/__library_test__/toc-stats')");assert.equal(final.model_calls,0);assert.equal(final.readings,0);pass('Source-page preview also works on phone; all three flows use zero model requests and create zero book readings');
  assert.equal(errors.length,0);fs.writeFileSync(path.join(folder,'toc-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,model_requests:final.model_calls},null,2));console.log('PASS '+checks.length+' checks');
 }catch(e){fs.writeFileSync(path.join(folder,'toc-ui-report.json'),JSON.stringify({passed:false,checks,console_errors:errors,error:e.stack},null,2));console.error(e.stack);await shot(pc,'failed-toc').catch(()=>{});process.exitCode=1;}
 finally{for(const w of windows)w.destroy();app.quit();}
});
