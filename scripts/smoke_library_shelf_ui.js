/* Native wheel/keyboard and real DOM/API checks for the bounded book shelf. */
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {X509Certificate} = require('node:crypto');
const folder = path.join(__dirname, '../build', process.argv[2]);
const data = JSON.parse(fs.readFileSync(path.join(folder, 'case.json'), 'utf8'));
const baseline = process.argv.includes('--baseline');
app.setPath('userData', path.join(folder, baseline ? 'electron-baseline' : 'electron-shelf'));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('force-device-scale-factor', '1');
const checks = [], errors = [], measurements = [], sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const run = (win, code) => win.webContents.executeJavaScript(code);
const pass = text => {checks.push(text); fs.appendFileSync(path.join(folder, 'shelf-log.txt'), text + '\n');};
async function until(win, code) {
  for (let i = 0; i < 300; i++) {if (await run(win, code)) return; await sleep(100);}
  throw new Error('UI wait failed: ' + code);
}
function debug(win) {if (!win.webContents.debugger.isAttached()) win.webContents.debugger.attach('1.3');}
async function shot(win, name) {
  debug(win);
  const result = await win.webContents.debugger.sendCommand('Page.captureScreenshot', {format:'png'});
  fs.writeFileSync(path.join(folder, name + '.png'), Buffer.from(result.data, 'base64'));
}
async function measure(win) {
  return run(win, `(()=>{const e=$('bookShelf'),r=e.getBoundingClientRect(),v=$('view-library')?.getBoundingClientRect();
    const c=document.querySelector('.book-shelf').getBoundingClientRect();return {height:innerHeight,width:innerWidth,
    top:r.top,bottom:r.bottom,client:e.clientHeight,total:e.scrollHeight,scroll:e.scrollTop,shelfBottom:c.bottom,
    viewBottom:v?.bottom,overflow:Math.max(0,document.documentElement.scrollWidth-innerWidth),
    count:e.querySelectorAll('[data-book-open]').length};})()`);
}
async function wheel(win, id, deltaY) {
  debug(win);
  // Use the midpoint of the visible rectangle; all input is trusted Chromium input.
  const point = await run(win, `(()=>{const r=$('${id}').getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round((Math.max(r.top,0)+Math.min(r.bottom,innerHeight))/2)};})()`);
  await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', {type:'mouseMoved',...point});
  await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', {type:'mouseWheel',...point,deltaX:0,deltaY});
  await sleep(180);
}
const windows = [];
app.whenReady().then(async () => {
  const pc = new BrowserWindow({show:false,width:1500,height:650,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
  windows.push(pc);
  pc.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|404/.test(event.message))errors.push(event.message);});
  try {
    await pc.loadURL(data.desktop_url);
    await until(pc, "state.ready&&state.conversation&&typeof libraryOpen==='function'");
    await run(pc, `libraryOpen('${data.book_id}')`);
    await until(pc, `$('bookShelf').querySelectorAll('[data-book-open]').length===${data.shelf_books.length}`);
    if (baseline) {
      measurements.push(await measure(pc));
      await wheel(pc, 'bookShelf', 100000);
      measurements.push(await measure(pc));
      await shot(pc, 'shelf-before');
      fs.writeFileSync(path.join(folder,'shelf-baseline.json'),JSON.stringify({measurements,console_errors:errors},null,2));
      pc.destroy(); app.exit(0); return;
    }
    await run(pc, "$('bookShelf').addEventListener('wheel',e=>window.shelfTrustedWheel=e.isTrusted)");
    for (const [width,height] of [[1500,650],[1500,1000],[1024,560]]) {
      pc.setSize(width,height); await sleep(200);
      const before = await measure(pc); measurements.push(before);
      assert(before.bottom<=before.viewBottom+1 && before.shelfBottom<=before.viewBottom+1,JSON.stringify(before));
      assert(before.client>=64 && before.total>before.client && before.overflow<=1,JSON.stringify(before));
      await wheel(pc, 'bookShelf', 100000);
      const after = await measure(pc);
      assert(after.scroll>0 && after.scroll>=after.total-after.client-2,JSON.stringify(after));
      assert(await run(pc, "window.shelfTrustedWheel===true"));
      assert(await run(pc, "(()=>{const e=$('bookShelf'),r=e.getBoundingClientRect(),b=e.lastElementChild.getBoundingClientRect();return b.bottom<=r.bottom+1&&b.bottom>r.top;})()"));
      pass(`All ${before.count} books reach the last entry with native wheel at ${width}x${height}; no clipped shelf`);
      await shot(pc, `shelf-${width}x${height}`);
    }
    const beforeSelect = await measure(pc);
    const last = await run(pc, "$('bookShelf').lastElementChild.previousElementSibling.dataset.bookOpen");
    await run(pc, "$('bookShelf').lastElementChild.previousElementSibling.click()");
    await until(pc, `studyforgeBookLibrary.book?.id==='${last}'&&$('bookDetail').querySelector('h2')`);
    assert(Math.abs((await measure(pc)).scroll-beforeSelect.scroll)<=1);
    pass('Selecting a book preserves the shelf scroll position');
    await run(pc, "showView('study')"); await run(pc, `libraryOpen('${last}')`);
    assert(Math.abs((await measure(pc)).scroll-beforeSelect.scroll)<=1);
    pass('Returning to the book library and refreshing the catalogue preserves its position');
    const count = data.shelf_books.length;
    await run(pc, "$('bookSearch').value='教材 05';$('bookSearch').dispatchEvent(new Event('input',{bubbles:true}))");
    await until(pc, "$('bookShelf').querySelectorAll('[data-book-open]').length===1");
    assert.equal((await measure(pc)).scroll,0);
    assert(await run(pc, "$('bookShelf').textContent.includes('教材 05')"));
    pass('A changed search starts at the top and keeps the matching book reachable');
    await run(pc, "$('bookSearch').value='';$('bookSearch').dispatchEvent(new Event('input',{bubbles:true}))");
    await until(pc, `$('bookShelf').querySelectorAll('[data-book-open]').length===${count}`);
    await run(pc, "$('bookShelf').focus()"); debug(pc);
    await pc.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyDown',key:'End',code:'End',windowsVirtualKeyCode:35});
    await pc.webContents.debugger.sendCommand('Input.dispatchKeyEvent',{type:'keyUp',key:'End',code:'End',windowsVirtualKeyCode:35});
    await sleep(220);
    assert((await measure(pc)).scroll>0);
    pass('The focused shelf also scrolls by keyboard');
    await run(pc, "document.querySelectorAll('.book-shelf-controls>details').forEach(e=>e.open=true)");
    await sleep(180);
    const opened = await measure(pc), tools = await run(pc, "(()=>{const e=$('bookShelfControls'),r=e.getBoundingClientRect();return {total:e.scrollHeight,client:e.clientHeight,bottom:r.bottom};})()");
    assert(opened.bottom<=opened.viewBottom+1 && opened.client>=64);
    assert(tools.total>tools.client);
    await wheel(pc, 'bookShelfControls',100000);
    assert(await run(pc, "$('bookShelfControls').scrollTop>0"));
    await wheel(pc, 'bookShelf',-100000);
    assert.equal((await measure(pc)).scroll,0);
    pass('Expanded reading/search settings scroll separately without hiding the book list');
    await shot(pc,'shelf-expanded-settings');
    await run(pc, "document.querySelectorAll('.book-shelf-controls>details').forEach(e=>e.open=false)");
    await run(pc, `libraryOpen('${data.book_id}')`);
    const shelfBeforeDetail = (await measure(pc)).scroll;
    await wheel(pc,'bookDetail',900);
    assert(await run(pc, "$('bookDetail').scrollTop>0"));
    assert.equal((await measure(pc)).scroll,shelfBeforeDetail);
    pass('The chapter panel scrolls independently and leaves book selection in place');
    await run(pc, `libraryOpen('${last}')`);
    assert.equal(await run(pc,"$('bookDetail').scrollTop"),0);
    pass('Changing the book shows the new chapter panel from its heading');
    await run(pc,"document.documentElement.dataset.background='custom'");
    const background = await measure(pc);
    assert(background.bottom<=background.viewBottom+1&&background.client>=64,JSON.stringify(background));
    pass('A taller custom-background page heading still leaves the shelf inside the viewport');
    await run(pc,"document.documentElement.dataset.background='none'");
    await run(pc, `libraryOpen('${data.book_id}')`);
    pc.setSize(1500,650); await sleep(150);
    await shot(pc,'shelf-desktop');
    const phone = new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
    windows.push(phone);
    phone.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|404/.test(event.message))errors.push(event.message);});
    const ca = new X509Certificate(fs.readFileSync(data.certificate));
    phone.webContents.session.setCertificateVerifyProc((req,callback)=>{let accepted=false;try{accepted=req.hostname==='127.0.0.1'&&new X509Certificate(req.certificate.data).verify(ca.publicKey);}catch{}callback(accepted?0:-3);});
    const name='书架滚动验收手机 '+Date.now();
    const pairing=await run(pc, `fetch('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json())`);
    await phone.loadURL(data.mobile_url+'/#pair='+pairing.pairing_code);
    await until(phone,"typeof mobile!=='undefined'&&$('pairScreen')&&!$('pairScreen').hidden");
    await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
    await until(pc,`fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json()).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
    await run(pc,`(async()=>{const s=await fetch('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(r=>r.json());const d=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});const r=await fetch('/api/mobile/devices/'+d.id+'/approve',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}','Content-Type':'application/json'},body:JSON.stringify({approved:true})});if(!r.ok)throw new Error(await r.text());})()`);
    await until(phone,"mobile.authenticated&&mobile.chat&&typeof libraryOpen==='function'");
    await run(phone, `libraryOpen('${data.book_id}')`);
    await until(phone, `$('bookShelf').querySelectorAll('[data-book-open]').length===${count}`);
    for (const width of [390,320]) {
      phone.setSize(width,844); await sleep(180);
      await run(phone,"$('bookShelf').scrollIntoView({block:'center'});$('bookShelf').scrollTop=0");
      await wheel(phone,'bookShelf',100000);
      const m=await measure(phone);
      assert(m.client>0&&m.client<=180&&m.scroll>=m.total-m.client-2,JSON.stringify(m));
      assert(await run(phone,"$('mobileBookLibrary').scrollWidth-$('mobileBookLibrary').clientWidth<=1"));
      await shot(phone,`shelf-phone-${width}`);
      pass(`Paired mobile shelf reaches the last book at ${width}px without horizontal overflow`);
    }
    assert(!errors.length,JSON.stringify(errors));
    fs.writeFileSync(path.join(folder,'shelf-ui-report.json'),JSON.stringify({passed:true,checks,measurements,console_errors:errors},null,2));
    windows.forEach(win=>win.destroy()); app.exit(0);
  } catch (error) {
    fs.writeFileSync(path.join(folder,'shelf-ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,measurements,console_errors:errors},null,2));
    await shot(pc,'shelf-failed-desktop');
    for(const win of windows.slice(1))if(win.webContents.getURL())await shot(win,'shelf-failed-phone');
    windows.forEach(win=>win.destroy()); app.exit(1);
  }
});
