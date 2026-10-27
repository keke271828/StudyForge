/* Real desktop/phone button flows, native parsing and OCR, no paid model. */
const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const caseFile=process.env.STUDYFORGE_MOBILE_CASE,root=path.dirname(caseFile),data=JSON.parse(fs.readFileSync(caseFile,'utf8'));
app.setPath('userData',path.join(root,'electron-scope-profile'));app.disableHardwareAcceleration();
let desktop,phone;const errors=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.on('window-all-closed',()=>{});
app.on('certificate-error',(event,_contents,_url,_error,_certificate,callback)=>{event.preventDefault();callback(true);});
async function run(win,code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,180)+'\n'+error.message);}}
async function until(win,code,limit=300){for(let n=0;n<limit;n++){if(await run(win,code))return;await pause(150);}throw Error('Timed out: '+code);}
function windowFor(width,height,preload=false){return new BrowserWindow({show:false,width,height,webPreferences:{...(preload?{preload:path.resolve('desktop/preload.js')}:{ }),contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});}
async function screenshot(win,name){win.webContents.invalidate();await pause(200);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function addUrl(win,url,mobile=false){await run(win,`$('${mobile?'sourceUrl':'composerUrl'}').value=${JSON.stringify(url)};$('${mobile?'urlForm':'composerUrlForm'}').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))`);const list=mobile?'mobile.sources':'state.sources';await until(win,`${list}.some(s=>s.origin_url===${JSON.stringify(url)})`);return run(win,`${list}.find(s=>s.origin_url===${JSON.stringify(url)}).id`);}
async function source(win,id,mobile=false){return run(win,`(async()=>{await ${mobile?'refreshProject':'refreshSources'}();return ${mobile?'mobile.sources':'state.sources'}.find(s=>s.id===${JSON.stringify(id)})})()`);}
async function ready(win,id,mobile=false){const refresh=mobile?'refreshProject':'refreshSources',list=mobile?'mobile.sources':'state.sources';await until(win,`(async()=>{await ${refresh}();return ${list}.find(s=>s.id===${JSON.stringify(id)})?.status==='ready'})()`,500);}
app.whenReady().then(async()=>{
  try {
    for(const [channel,value] of [['desktop-status',{tray_available:false}],['window-state',{fullscreen:false}],['update-status',{state:'idle'}],['notification-status',{supported:false}],['startup-status',{available:false,enabled:false,start_hidden:true}],['mobile-status',{running:false,interfaces:[]}]] )ipcMain.handle('studyforge:'+channel,()=>value);
    ipcMain.handle('studyforge:import-browser-page',(_event,url)=>({url,title:'浏览器读取后的文章',kind:'article',html:'<article><h1>正文标题</h1><p>'+('BROWSER_SOURCE_RECOVERY 完整正文。'.repeat(18))+'</p></article>'}));
    desktop=windowFor(1480,1000,true);await desktop.loadURL(data.desktop_url);await until(desktop,'state.ready && state.conversation && !conversationUI.restoring');
    desktop.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|IPC channel/i.test(event.message))errors.push(event.message);});
    const publicUrl='https://example.org/public',urlId=await addUrl(desktop,publicUrl);
    assert.equal((await source(desktop,urlId)).status,'stored');
    await until(desktop,`document.querySelector('[data-source-scope="${urlId}"]')?.textContent==='解析网址'`);
    assert.ok(await run(desktop,`[...document.querySelector('[data-quick-source="${urlId}"]').closest('label').querySelectorAll('button')].some(b=>b.textContent==='浏览器读取')`),'Browser reading must be available while the URL is still stored');
    assert.equal(await run(desktop,"$('sourceScopeDialog').open"),false);
    assert.equal(await run(desktop,`(async()=>{const rows=await api('/api/projects/${data.project_id}/jobs');return rows.some(j=>j.payload?.source_id==='${urlId}')})()`),false);
    await run(desktop,`document.querySelector('[data-source-scope="${urlId}"]').click()`);await ready(desktop,urlId);
    assert.equal(await run(desktop,"$('sourceScopeDialog').open"),false);
    assert.equal((await source(desktop,urlId)).parse_type,'url');
    const original=await run(desktop,`api('/api/sources/${urlId}')`);assert.ok(original.segments.some(s=>s.text.includes('COMPLETE_SOURCE_BODY')));
    const retryId=await addUrl(desktop,'https://example.org/first-fails');
    await run(desktop,`document.querySelector('[data-source-scope="${retryId}"]').click()`);
    await until(desktop,`(async()=>{await refreshSources();return state.sources.find(s=>s.id==='${retryId}')?.status==='error'})()`);
    await until(desktop,`document.querySelector('[data-source-scope="${retryId}"]')?.textContent==='重试网址'`);
    await run(desktop,`document.querySelector('[data-source-scope="${retryId}"]').click()`);await ready(desktop,retryId);
    const recoveryId=await addUrl(desktop,'https://example.org/needs-login');
    await run(desktop,`document.querySelector('[data-source-scope="${recoveryId}"]').click()`);
    await until(desktop,`(async()=>{await refreshSources();return state.sources.find(s=>s.id==='${recoveryId}')?.status==='error'})()`);
    await until(desktop,`[...document.querySelector('[data-quick-source="${recoveryId}"]').closest('label').querySelectorAll('button')].some(b=>b.textContent==='浏览器读取')`);
    await run(desktop,`[...document.querySelector('[data-quick-source="${recoveryId}"]').closest('label').querySelectorAll('button')].find(b=>b.textContent==='浏览器读取').click()`);
    await until(desktop,`(async()=>{await refreshSources();return !state.sources.some(s=>s.id==='${recoveryId}')&&state.sources.some(s=>s.name==='浏览器读取后的文章'&&s.status==='ready'&&!s.partial_parse_supported)})()`);
    const png=fs.readFileSync(path.join(root,'scope-image.png')).toString('base64');
    const imageId=await run(desktop,`(async()=>{const body=new FormData();body.append('project_id',state.project.id);body.append('file',new File([Uint8Array.from(atob('${png}'),c=>c.charCodeAt(0))],'scope-image.png',{type:'image/png'}));const r=await api('/api/import/file',{method:'POST',body});await refreshSources();return r.source_id})()`);
    assert.equal((await source(desktop,imageId)).status,'stored');await until(desktop,`document.querySelector('[data-source-scope="${imageId}"]')?.textContent==='解析图片'`);
    await run(desktop,`document.querySelector('[data-source-scope="${imageId}"]').click()`);await ready(desktop,imageId);
    assert.equal(await run(desktop,"$('sourceScopeDialog').open"),false);
    const imageRead=await run(desktop,`api('/api/sources/${imageId}')`);assert.ok(imageRead.segments.some(s=>s.kind==='image'&&s.meta.image_path));assert.ok(imageRead.segments.some(s=>/12345/.test(s.text)),JSON.stringify(imageRead.segments));
    const pdf=fs.readFileSync(data.book).toString('base64');
    const pdfId=await run(desktop,`(async()=>{const body=new FormData();body.append('project_id',state.project.id);body.append('file',new File([Uint8Array.from(atob('${pdf}'),c=>c.charCodeAt(0))],'scope-book.pdf',{type:'application/pdf'}));const r=await api('/api/import/file',{method:'POST',body});await refreshSources();return r.source_id})()`);
    await run(desktop,`openSourceScope('${pdfId}')`);assert.equal(await run(desktop,"$('sourceScopeDialog').open && $('scopeMode').value==='pages'"),true);
    await run(desktop,"$('scopePages').value='3';$('sourceScopeForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))");await until(desktop,"!$('sourceScopeDialog').open");
    const excerpt=await run(desktop,"(async()=>{await refreshSources();return state.sources.find(s=>s.name.includes('scope-book.pdf · 第 3 页'))})()");assert.ok(excerpt);
    const pdfRead=await run(desktop,`api('/api/sources/${excerpt.id}')`);assert.ok(JSON.stringify(pdfRead.segments).includes('PRIVATE_PAGE_3'));assert.equal(JSON.stringify(pdfRead.segments).includes('PRIVATE_PAGE_1'),false);
    await screenshot(desktop,'desktop-direct-source-buttons');
    phone=windowFor(390,844);await phone.loadURL(data.mobile_url);await until(phone,"Boolean(window.studyforgeSourceScope&&$('pairCode'))");
    const pairing=await run(phone,`api('/mobile/pair',json('POST',{code:'${data.pairing_code}',name:'网址图片入口验收手机'}))`);
    const decision=await fetch(data.desktop_url+`/api/mobile/devices/${pairing.device_id}/approve`,{method:'POST',headers:{'Content-Type':'application/json','X-StudyForge-Desktop-Token':data.token},body:JSON.stringify({approved:true})});assert.equal(decision.ok,true,await decision.text());
    await run(phone,`api('/mobile/pair/${pairing.device_id}',{headers:{'X-Mobile-Pair-Ticket':'${pairing.ticket}'}})`);await phone.reload();await until(phone,'mobile.authenticated && mobile.chat');
    await run(phone,"openSheet('materialsDialog')");const mobileId=await addUrl(phone,'https://example.org/phone',true);
    await until(phone,"[...$('sourceList').querySelectorAll('.item')].some(c=>c.textContent.includes('https://example.org/phone')&&c.querySelector('button')?.textContent==='解析网址')");
    await run(phone,"[...$('sourceList').querySelectorAll('.item')].find(c=>c.textContent.includes('https://example.org/phone')).querySelector('button').click()");await ready(phone,mobileId,true);
    assert.equal(await run(phone,"$('sourceScopeDialog').open"),false);
    const mobileImageId=await run(phone,`(async()=>{const body=new FormData();body.append('project_id',mobile.project.id);body.append('file',new File([Uint8Array.from(atob('${png}'),c=>c.charCodeAt(0))],'phone-image.png',{type:'image/png'}));const r=await api('/api/import/file',{method:'POST',body});await refreshProject();return r.source_id})()`);
    await run(phone,"[...$('sourceList').querySelectorAll('.item')].find(c=>c.textContent.includes('phone-image.png')).querySelector('button').click()");await ready(phone,mobileImageId,true);
    assert.equal(await run(phone,"$('sourceScopeDialog').open"),false);
    await screenshot(phone,'phone-direct-source-buttons');phone.setSize(320,760);await pause(250);assert.ok(await run(phone,'document.documentElement.scrollWidth<=innerWidth+1'));
    await run(phone,`openSourceScope(mobile.sources.find(s=>s.id==='${pdfId}'))`);assert.equal(await run(phone,"$('sourceScopeDialog').open && $('scopeMode').value==='pages'"),true);
    const calls=path.join(root,'requests.json');assert.equal(fs.existsSync(calls),false,'Source parsing must not invoke a teaching model');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(root,'ui-report.json'),JSON.stringify({passed:true,checks:['store-first URL and image import','desktop direct URL reading without scope dialog','original URL retry after parser failure','browser recovery keeps the old source until success','native image OCR with original image metadata','PDF page 3 remains separate without page 1','actual phone TLS pairing','phone URL and image direct actions','phone PDF scope unchanged','320px layout','no paid model requests']},null,2));console.log('DIRECT_SOURCE_UI_PASS '+root);app.exit(0);
  }catch(error){console.error(error.stack);fs.writeFileSync(path.join(root,'ui-errors.json'),JSON.stringify({error:String(error.stack),console:errors},null,2));if(desktop)await screenshot(desktop,'desktop-failure');if(phone)await screenshot(phone,'phone-failure');app.exit(1);}
});
