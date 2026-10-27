/* Actual app UI, four backend batches, pause/resume, and paired HTTPS phone. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-batches'));app.disableHardwareAcceleration();app.commandLine.appendSwitch('force-device-scale-factor','1');
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const run=(w,c)=>w.webContents.executeJavaScript(c);
const pass=t=>{checks.push(t);fs.appendFileSync(path.join(folder,'batches-ui-log.txt'),t+'\n');console.log(t);};
async function until(w,c,timeout=240000){const end=Date.now()+timeout;while(Date.now()<end){if(await run(w,c))return;await sleep(200);}throw new Error('UI wait failed: '+c);}
async function choose(w,id){await run(w,`libraryOpen('${id}')`);await until(w,`studyforgeBookLibrary.loadedBook==='${id}'&&Boolean($('bookNodeQuery'))`);}
async function shot(w,name){if(!w.webContents.debugger.isAttached())w.webContents.debugger.attach('1.3');const r=await w.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
function watch(w){w.webContents.on('console-message',e=>{if(e.level==='error'&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});}
async function selectAll(w){await run(w,"$('selectAllBookNodes').click();$('bookReadingPriority').value='foreground';$('bookReadingPriority').dispatchEvent(new Event('change'));");assert(await run(w,"studyforgeBookLibrary.selected.size===316&&!$('readBookNodes').disabled&&$('bookSelectedCount').textContent.includes('自动分批')"));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1500,height:900,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});windows.push(pc);watch(pc);
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc,data.bulk_read_book_id);
  await selectAll(pc);assert(await run(pc,"$('locateBookNodes').disabled"));await shot(pc,'desktop-bulk-selected');
  pass('Desktop all 316 nodes can start reading; existing confirmed scopes do not offer re-location');
  await run(pc,"$('bookReadingMode').value='parallel';$('bookReadingMode').dispatchEvent(new Event('change'));$('readBookNodes').click()");
  await until(pc,"studyforgeBookLibrary.jobs[0]?.status==='running'&&studyforgeBookLibrary.jobs[0].result.batches_completed>=1&&studyforgeBookLibrary.jobs[0].result.batch_index===2");
  assert(await run(pc,"studyforgeBookLibrary.jobs.length===1&&studyforgeBookLibrary.jobs[0].payload.batches_total===4&&studyforgeBookLibrary.jobs[0].payload.batch_size===100&&document.querySelector('.book-batch-progress').textContent.includes('/4 批')"));
  pass('One foreground task actually advances to batch 2 of 4 and displays saved-batch progress');
  await run(pc,"document.querySelector('[data-book-job][data-action=pause]').click()");await until(pc,"studyforgeBookLibrary.jobs[0].status==='paused'");
  const paused=await run(pc,"api('/__library_test__/batch-stats')");await sleep(1000);assert.equal((await run(pc,"api('/__library_test__/batch-stats')")).calls,paused.calls);
  await run(pc,"document.querySelector('.book-batch-progress').scrollIntoView({block:'center'})");await shot(pc,'desktop-bulk-paused');
  pass('Pause stops new model requests in the second batch and retains the completed first batch');
  await pc.reload();await until(pc,"state.ready&&state.conversation&&typeof libraryOpen==='function'");await choose(pc,data.bulk_read_book_id);
  assert(await run(pc,"studyforgeBookLibrary.jobs[0].status==='paused'&&studyforgeBookLibrary.jobs[0].result.batches_completed===1"));
  await run(pc,"document.querySelector('[data-book-job][data-action=resume]').click()");await until(pc,"studyforgeBookLibrary.jobs[0].status==='completed'");
  const done=await run(pc,"studyforgeBookLibrary.jobs[0]");assert.equal(done.result.nodes_completed_count,316);assert.equal(done.result.batches_completed,4);assert.equal(done.result.nodes_completed.length,16);
  const stat=await run(pc,"api('/__library_test__/batch-stats')");assert.equal(stat.calls,316);assert.equal(stat.readings,316);assert.equal(stat.peak,2);
  pass('Reload and resume produce 316 readings with 316 mock requests, no duplicates, and at most 2 simultaneous requests');
  await run(pc,"document.querySelector('.book-batch-progress').scrollIntoView({block:'center'})");await shot(pc,'desktop-bulk-complete');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((req,cb)=>{let ok=false;try{ok=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}cb(ok?0:-3);});
  const name='分批验收手机 '+Date.now(),pair=await run(pc,`fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");await choose(phone,data.bulk_range_book_id);await selectAll(phone);
  assert(await run(phone,"!$('locateBookNodes').disabled&&!$('completeBookRanges').disabled"));
  pass('Paired HTTPS phone enables all-selected reading, selected range location and whole-book pending-range completion for 316 nodes');
  await run(phone,"$('completeBookRanges').click()");await until(phone,"studyforgeBookLibrary.jobs[0]?.status==='completed'");
  assert(await run(phone,"studyforgeBookLibrary.jobs.length===1&&studyforgeBookLibrary.jobs[0].result.batches_completed===4&&studyforgeBookLibrary.jobs[0].result.nodes_completed_count===316&&studyforgeBookLibrary.nodes.every(n=>n.confirmed)"));
  assert.equal((await run(pc,"api('/__library_test__/batch-stats')")).calls,316);
  pass('Whole-book location uses four actual batches, confirms 316 native headings, and makes no extra model requests or readings');
  for(const width of [390,320]){phone.setSize(width,844);await run(phone,"document.querySelector('.book-batch-progress').scrollIntoView({block:'center'})");await sleep(150);assert(await run(phone,"$('bookDetail').scrollWidth-$('bookDetail').clientWidth<=1&&document.querySelector('.book-batch-progress').getBoundingClientRect().bottom<innerHeight"));await shot(phone,'phone-bulk-complete-'+width);pass(`Phone ${width}px displays saved-batch progress and controls without horizontal overflow`);}
  assert.equal(errors.length,0);fs.writeFileSync(path.join(folder,'batches-ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,mock_model_requests:stat.calls,peak_model_requests:stat.peak},null,2));console.log('PASS '+checks.length+' checks');
 }catch(e){fs.writeFileSync(path.join(folder,'batches-ui-report.json'),JSON.stringify({passed:false,checks,console_errors:errors,error:e.stack},null,2));console.error(e.stack);await shot(pc,'failed-batches').catch(()=>{});process.exitCode=1;}
 finally{for(const w of windows)w.destroy();app.quit();}
});
