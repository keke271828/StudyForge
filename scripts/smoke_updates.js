// Real Electron updater HTTP/sha512 and renderer tests. No installer is executed.
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {ipcMain}=require('electron');
const {NsisUpdater}=require('electron-updater');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');
const {spawnSync}=require('node:child_process');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

exports.run=async function({app,window:win,lifecycle,backend,url,report,ownerToken,sourceManager,requestQuit}){
  const root=path.dirname(report),result={ok:true,desktop_pid:process.pid,backend_pid:backend.pid,url};
  const request=async(route,method='GET')=>{const response=await fetch(url+route,{method,headers:{'X-StudyForge-Desktop-Token':ownerToken}});if(!response.ok)throw new Error(await response.text());return response.json();};
  async function until(check,label){for(let i=0;i<180;i++){const value=await check();if(value)return value;await delay(100);}throw new Error('Update UI timed out: '+label);}
  const evaluate=code=>win.webContents.executeJavaScript(code);
  await until(()=>evaluate('Boolean(state.settings && state.project)'), 'initialized');
  await evaluate(`(async()=>{clearTimeout(readingTimer);state.selected.clear();showView('settings');await refreshUpdateControls();})()`);
  assert.equal(await evaluate(`$('updateControls').closest('.view').id`),'view-settings');
  assert.equal(await evaluate(`$('checkUpdates').disabled`),true);
  await evaluate(`$('updateFeed').value='https://updates.example.test/windows';$('updateInterval').value=12;$('updateAutoCheck').checked=false;$('saveUpdateSettings').click();`);
  await until(()=>sourceManager.snapshot().settings.interval_hours===12,'source save');
  result.source_settings_saved=sourceManager.snapshot().settings.feed_url==='https://updates.example.test/windows/';
  assert.equal(result.source_settings_saved,true);assert.equal(sourceManager.snapshot().packaged,false);
  result.source_does_not_install=true;
  sourceManager.dispose();

  const binary=Buffer.alloc(512*1024,42);binary.write('MZ-isolated-non-executable-update');
  const hash=crypto.createHash('sha512').update(binary).digest('base64');
  const metadata={version:'0.3.5',files:[{url:'StudyForge-Setup-0.3.5.exe',size:binary.length,sha512:hash}],
    releaseNotes:'测试版本说明：<img src=x onerror=alert(1)> 只应显示文本'};
  let unavailable=false,downloads=0;
  const feed=http.createServer((req,res)=>{
    if(req.url.split('?')[0]==='/latest.yml'){
      if(unavailable){res.writeHead(503);res.end('isolated unavailable');}
      else{res.writeHead(200,{'Content-Type':'text/yaml'});res.end(JSON.stringify(metadata));}return;
    }
    if(req.url==='/StudyForge-Setup-0.3.5.exe'){
      downloads++;res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':binary.length});let index=0;
      const interval=setInterval(()=>{if(index>=binary.length){clearInterval(interval);res.end();return;}
        res.write(binary.subarray(index,index+32768));index+=32768;},100);res.on('close',()=>clearInterval(interval));return;
    }
    res.writeHead(404);res.end('not found');
  });
  await new Promise(resolve=>feed.listen(0,'127.0.0.1',resolve));const feedUrl=`http://127.0.0.1:${feed.address().port}/`;
  const updaterConfig=path.join(root,'dev-app-update.yml');fs.writeFileSync(updaterConfig,JSON.stringify({provider:'generic',url:feedUrl,updaterCacheDirName:'download-cache'}));
  const realUpdater=new NsisUpdater({provider:'generic',url:feedUrl,useMultipleRangeRequest:false});
  realUpdater.updateConfigPath=updaterConfig;realUpdater.forceDevUpdateConfig=true;realUpdater.disableDifferentialDownload=true;
  Object.defineProperty(realUpdater.app,'baseCachePath',{value:path.join(root,'http-cache')});
  // First verify an unsigned fixture using the actual Windows verifier.
  const unsigned=path.join(root,'unsigned.exe');fs.writeFileSync(unsigned,binary);
  const rejected=await realUpdater.verifyUpdateCodeSignature(['StudyForge Test Publisher'],unsigned);
  assert.notEqual(rejected,null);result.windows_unsigned_signature_rejected=true;
  // A test-only signature stand-in permits the UI flow. Launch remains a stand-in too.
  realUpdater.verifyUpdateCodeSignature=async()=>null;
  const manager=createUpdateManager({currentVersion:app.getVersion(),packaged:true,storageDirectory:path.join(root,'manager'),
    initialFeed:feedUrl,publishers:['StudyForge Test Publisher'],allowTestUrls:true,createUpdater:()=>realUpdater,
    requestQuit,notify:value=>win.webContents.send('studyforge:update-changed',value),
    launchInstaller:async file=>{
      assert.ok(backend.exitCode!==null||backend.signalCode!==null);result.backend_stopped_before_install=true;
      assert.equal(fs.readFileSync(file).equals(binary),true);result.real_download_hash_verified=true;result.installation='stand-in only; no executable run';
      const history=JSON.parse(fs.readFileSync(path.join(root,'manager/update-history.json'),'utf8'));
      result.backup=history.pending.backup;assert.ok(result.backup.id);assert.ok(fs.existsSync(path.join(result.backup.path,'manifest.json')));
      result.preinstall_backup_created=true;
      const check=spawnSync(backend.spawnfile,['-c','import sqlite3,sys,json; db=sqlite3.connect(sys.argv[1]); print(json.dumps(db.execute("SELECT status,progress FROM jobs WHERE id=?",(sys.argv[2],)).fetchone()))',
        path.join(result.backup.path,'studyforge.sqlite3'),result.paused_generation],{windowsHide:true,encoding:'utf8'});
      assert.equal(check.status,0);assert.deepEqual(JSON.parse(check.stdout),['paused',85]);result.running_generation_saved_in_backup=true;
      fs.writeFileSync(report,JSON.stringify(result,null,2));
    }});
  for(const name of ['status','save','check','download','install','rollback','recovery'])ipcMain.removeHandler('studyforge:update-'+name);
  registerUpdateHandlers(ipcMain,new URL(url).origin,()=>win,manager,()=>true,()=>false);
  app.on('will-quit',()=>{manager.dispose();feed.closeAllConnections();feed.close();});
  try{
    await evaluate(`(async()=>{await refreshUpdateControls();})()`);
    await evaluate(`$('checkUpdates').click()`);await until(()=>manager.snapshot().status==='available','available');
    await until(()=>evaluate(`!$('downloadUpdate').disabled && !$('downloadUpdate').hidden`),'download button');
    assert.equal(await evaluate(`$('updateNotes').querySelector('img')===null`),true);result.release_notes_text_only=true;
    await evaluate(`$('updateFeed').value='https://unsaved.example.test/';$('downloadUpdate').click();`);
    await until(()=>manager.snapshot().progress?.percent>0,'progress');
    assert.equal(await evaluate(`$('updateFeed').value`),'https://unsaved.example.test/');result.progress_keeps_unsaved_settings=true;
    await until(()=>manager.snapshot().status==='downloaded','downloaded');
    assert.equal(await evaluate(`$('installUpdate').hidden`),false);result.download_completed=true;
    await until(()=>evaluate(`!$('checkUpdates').disabled`),'check ready');
    unavailable=true;await evaluate(`$('checkUpdates').click()`);await until(()=>manager.snapshot().status==='error','offline error');
    await until(()=>evaluate(`!$('checkUpdates').disabled`),'retry ready');
    unavailable=false;await evaluate(`$('checkUpdates').click()`);await until(()=>manager.snapshot().status==='downloaded','retry reuses download');
    assert.equal(downloads,1);result.network_retry_reuses_cache=true;
    result.child_pid=(await request('/qa/tray/info')).child_pid;
    result.paused_generation=(await request('/qa/tray/start/resume','POST')).job_id;
    await until(async()=>{const info=await request('/qa/tray/info');return info.calls.some(x=>x.job_id===result.paused_generation&&x.kind==='exercise');},'generation still in progress');
    await until(()=>evaluate(`!$('installUpdate').disabled && !$('installUpdate').hidden`),'install button');
    fs.writeFileSync(report,JSON.stringify({...result,ok:false,error:'waiting for verified backup and exit'},null,2));
    await evaluate(`$('installUpdate').click();`);
    await until(()=>manager.snapshot().status==='installing','install request');
  }catch(error){manager.dispose();feed.closeAllConnections();feed.close();throw error;}
};
