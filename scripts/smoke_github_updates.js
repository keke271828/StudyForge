// Isolated desktop acceptance: real renderer, IPC and streamed local HTTP; no installer execution.
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {ipcMain}=require('electron');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');
const {createGitHubReleaseClient,releaseApi}=require('../desktop/github_releases');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

exports.runLive=async({app,window:win,sourceManager,updateRequest,report})=>{
  const result={ok:false,full_installer_downloaded:false,installer_executed:false},root=path.dirname(report);
  const evaluate=code=>win.webContents.executeJavaScript(code);
  async function until(check,label){for(let i=0;i<350;i++){if(await check())return;await delay(100);}throw new Error('Live update check timed out: '+label);}
  win.showInactive();
  try{
    result.stage='initialize';await until(()=>evaluate('Boolean(state.settings && state.project)'), 'initialized');
    sourceManager.save({feed_url:'',auto_check:false,auto_download:false,interval_hours:24});
    await evaluate(`(async()=>{showView('settings');showSettingsSection('system');await refreshUpdateControls();$('checkUpdates').click();})()`);
    result.stage='metadata';await until(()=>['current','available','ahead','error'].includes(sourceManager.snapshot().status),'real GitHub check');
    const state=sourceManager.snapshot();if(state.status==='error')throw new Error(state.error);
    result.version=state.candidate.version;result.size=state.candidate.size;result.sha256=state.candidate.sha256;
    result.release_url=state.release_url;result.real_ui_check_passed=true;
    result.stage='download';const response=await updateRequest(state.candidate.asset_api_url||state.candidate.url,{headers:{Accept:'application/octet-stream',Range:'bytes=0-65535'},
      credentials:'omit',signal:AbortSignal.timeout(20000)});
    if(!response.ok||!response.body)throw new Error('Real installer connection failed: '+response.status);
    const reader=response.body.getReader();let count=0;const first=[];
    try{while(count<65536){const part=await reader.read();if(part.done)break;count+=part.value.byteLength;if(first.length<2)first.push(...part.value.subarray(0,2-first.length));}}
    finally{await reader.cancel();reader.releaseLock();}
    assert.ok(count>0);assert.deepEqual(first,[77,90]);result.real_installer_sample_bytes=count;
    result.real_installer_http_status=response.status;result.exe_header_verified=true;
    await evaluate(`$('updateControls').scrollIntoView({block:'start',behavior:'instant'})`);
    await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    await win.webContents.capturePage();await delay(150);
    result.screenshot=path.join(root,'real-github-check.jpg');fs.writeFileSync(result.screenshot,(await win.webContents.capturePage()).toJPEG(88));
    result.ok=true;fs.writeFileSync(report,JSON.stringify(result,null,2));app.quit();
  }catch(error){result.error=error.stack||String(error);console.error(JSON.stringify(result));fs.writeFileSync(report,JSON.stringify(result,null,2));sourceManager.dispose();throw error;}
};

exports.run=async({app,window:win,sourceManager,url,report})=>{
  const root=path.dirname(report),result={ok:false,external_requests:0,installer_executed:false};
  const evaluate=code=>win.webContents.executeJavaScript(code);
  async function until(check,label){for(let i=0;i<180;i++){if(await check())return;await delay(100);}throw new Error('GitHub update UI timed out: '+label);}
  win.showInactive();
  await until(()=>evaluate('Boolean(state.settings && state.project)'), 'initialized');sourceManager.dispose();
  const binary=Buffer.alloc(1024*1024,29);binary.write('MZ-isolated-not-executable');
  const metadata={tag_name:'v0.0.2',draft:false,prerelease:false,
    html_url:'https://github.com/keke271828/StudyForge/releases/tag/v0.0.2',
    body:'# 新版讲解改进\n\n这是隔离验收资料。<img src=x onerror=alert(1)>',
    assets:[{name:'StudyForge-Setup-0.0.2.exe',state:'uploaded',size:binary.length,
      browser_download_url:'https://github.com/keke271828/StudyForge/releases/download/v0.0.2/StudyForge-Setup-0.0.2.exe',
      digest:'sha256:'+crypto.createHash('sha256').update(binary).digest('hex')}]};
  let failCheck=false,brokenDownload=false,downloads=0;
  const feed=http.createServer((req,res)=>{
    if(req.url==='/metadata'){res.writeHead(failCheck?503:200,{'content-type':'application/json'});res.end(JSON.stringify(metadata));return;}
    if(req.url==='/installer'){
      downloads++;res.writeHead(200,{'content-length':binary.length});let offset=0;
      const timer=setInterval(()=>{const chunk=Buffer.from(binary.subarray(offset,offset+32768));
        if(brokenDownload)chunk.fill(31);res.write(chunk);offset+=chunk.length;
        if(offset>=binary.length){clearInterval(timer);res.end();}},20);res.on('close',()=>clearInterval(timer));return;
    }
    res.writeHead(404);res.end();
  });
  await new Promise(resolve=>feed.listen(0,'127.0.0.1',resolve));const base=`http://127.0.0.1:${feed.address().port}`;
  const client=createGitHubReleaseClient({request:(address,options)=>{
    assert.ok([releaseApi,metadata.assets[0].browser_download_url].includes(address));
    return fetch(base+(address===releaseApi?'/metadata':'/installer'),options);
  }});
  const opened=[],revealed=[];
  const manager=createUpdateManager({currentVersion:app.getVersion(),packaged:false,storageDirectory:path.join(root,'update-manager'),
    releaseClient:client,requestQuit:()=>{throw new Error('No automatic install is allowed in this acceptance');},
    launchInstaller:()=>{throw new Error('No installer execution is allowed in this acceptance');},
    notify:value=>win.webContents.send('studyforge:update-changed',value)});
  for(const name of ['status','save','check','download','install','rollback','recovery','cancel','release','reveal'])ipcMain.removeHandler('studyforge:update-'+name);
  registerUpdateHandlers(ipcMain,new URL(url).origin,()=>win,manager,()=>true,()=>false,
    address=>opened.push(address),file=>revealed.push(file));
  app.on('will-quit',()=>{manager.dispose();feed.closeAllConnections();feed.close();});
  try{
    await evaluate(`(async()=>{clearTimeout(readingTimer);showView('settings');showSettingsSection('system');await refreshUpdateControls();})()`);
    assert.equal(await evaluate(`$('updateControls').checkVisibility()`),true);result.update_section_visible=true;
    assert.equal(await evaluate(`$('checkUpdates').disabled`),false);
    assert.equal(await evaluate(`$('updateFeed').value`),'');result.source_default_checks_enabled=true;
    assert.match(await evaluate(`$('updateSourceNote').textContent`),/GitHub.*无需填写/);
    await evaluate(`$('checkUpdates').click()`);await until(()=>manager.snapshot().status==='available','new version');
    await until(()=>evaluate(`!$('downloadUpdate').hidden&&!$('downloadUpdate').disabled`),'download enabled');
    assert.equal(await evaluate(`$('updateNotes').querySelector('img')===null`),true);result.release_notes_safe=true;
    await evaluate(`$('openUpdateRelease').click()`);await until(()=>opened.length===1,'release page');
    result.release_link_correct=opened[0]===metadata.html_url;assert.equal(result.release_link_correct,true);
    await evaluate(`$('downloadUpdate').click()`);await until(()=>manager.snapshot().progress?.transferred>0,'progress');
    assert.equal(await evaluate(`$('cancelUpdateDownload').hidden`),false);
    await evaluate(`$('cancelUpdateDownload').click()`);await until(()=>manager.snapshot().status==='cancelled','cancel');
    await until(()=>evaluate(`!$('downloadUpdate').disabled`),'retry after cancel');result.cancel_works_during_active_download=true;
    brokenDownload=true;await evaluate(`$('downloadUpdate').click()`);await until(()=>manager.snapshot().status==='error','hash mismatch');
    assert.equal(manager.snapshot().can_install,false);assert.equal(manager.snapshot().can_reveal_download,false);
    result.hash_failure_rejected=true;brokenDownload=false;
    await until(()=>evaluate(`!$('downloadUpdate').disabled`),'retry enabled');
    await evaluate(`$('updateFeed').value='https://unsaved.example.test/';$('downloadUpdate').click()`);
    await until(()=>manager.snapshot().progress?.transferred>0,'retry progress');
    assert.equal(await evaluate(`$('updateFeed').value`),'https://unsaved.example.test/');result.progress_preserves_draft=true;
    await until(()=>manager.snapshot().status==='downloaded','downloaded');
    await until(()=>evaluate(`!$('revealUpdateDownload').hidden&&!$('revealUpdateDownload').disabled`),'reveal enabled');
    assert.equal(await evaluate(`$('installUpdate').hidden`),true);result.unsigned_auto_install_hidden=true;
    await evaluate(`$('revealUpdateDownload').click()`);await until(()=>revealed.length===1,'reveal file');
    assert.ok(fs.readFileSync(revealed[0]).equals(binary));result.reveal_verified_file=true;
    await until(()=>evaluate(`!$('checkUpdates').disabled`),'recheck enabled');
    failCheck=true;await evaluate(`$('checkUpdates').click()`);await until(()=>manager.snapshot().status==='error','network error');
    await until(()=>evaluate(`!$('checkUpdates').disabled`),'network retry');failCheck=false;
    await evaluate(`$('checkUpdates').click()`);await until(()=>manager.snapshot().status==='downloaded','retry kept cache');
    assert.equal(downloads,3);result.network_retry_reuses_verified_download=true;
    await evaluate(`(async()=>{showSettingsSection('system');await refreshUpdateControls();$('toast').hidden=true;$('updateControls').scrollIntoView({block:'start',behavior:'instant'});})()`);
    await until(()=>evaluate(`(()=>{const r=$('updateControls').getBoundingClientRect();return r.top>=0&&r.top<innerHeight/2;})()`),'visible update card');
    await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    await win.webContents.capturePage();await delay(200);const capture=await win.webContents.capturePage();
    fs.writeFileSync(path.join(root,'update-controls.jpg'),capture.toJPEG(88));
    result.screenshot=path.join(root,'update-controls.jpg');result.ok=true;fs.writeFileSync(report,JSON.stringify(result,null,2));app.quit();
  }catch(error){result.error=error.stack||String(error);fs.writeFileSync(report,JSON.stringify(result,null,2));manager.dispose();feed.closeAllConnections();feed.close();throw error;}
};
