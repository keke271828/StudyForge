const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {createGitHubReleaseClient,releaseInfo,releaseApi}=require('../desktop/github_releases');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');

function fixture(t,options={}){
  const root=fs.mkdtempSync(path.resolve(__dirname,'../build/github-update-unit-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const data=Buffer.alloc(64*1024,17),meta={tag_name:'v0.0.2',draft:false,prerelease:false,
    html_url:'https://github.com/keke271828/StudyForge/releases/tag/v0.0.2',body:'新的讲解功能',
    assets:[{name:'StudyForge-Setup-0.0.2.exe',state:'uploaded',size:data.length,
      browser_download_url:'https://github.com/keke271828/StudyForge/releases/download/v0.0.2/StudyForge-Setup-0.0.2.exe',
      digest:'sha256:'+crypto.createHash('sha256').update(data).digest('hex')}]};
  const calls={checks:0,downloads:0,quit:0,launch:0,states:[]};
  const releaseClient=createGitHubReleaseClient({request:async url=>{
    if(url===releaseApi){calls.checks++;return new Response(JSON.stringify(meta));}
    calls.downloads++;return new Response(data);}});
  const config={currentVersion:'0.0.1',packaged:false,storageDirectory:root,releaseClient,
    requestQuit:()=>calls.quit++,launchInstaller:()=>calls.launch++,notify:s=>calls.states.push(s),...options};
  const manager=createUpdateManager(config);t.after(()=>manager.dispose());return {manager,root,data,meta,calls,config};
}

test('source mode with an empty feed checks GitHub, downloads, verifies and never launches',async t=>{
  const {manager,calls,data}=fixture(t);assert.equal(manager.snapshot().can_check,true);
  assert.equal((await manager.check()).status,'available');assert.equal(manager.snapshot().can_download,true);
  await manager.download();assert.equal(manager.snapshot().status,'downloaded');assert.equal(manager.snapshot().can_install,false);
  assert.ok(fs.readFileSync(await manager.revealDownload()).equals(data));await assert.rejects(manager.install());
  assert.equal(calls.checks,1);assert.equal(calls.downloads,1);assert.equal(calls.quit+calls.launch,0);
});

test('packaged GitHub download remains manual even if a publisher name exists',async t=>{
  const {manager,calls}=fixture(t,{packaged:true,publishers:['Publisher']});await manager.check();await manager.download();
  assert.equal(manager.snapshot().can_reveal_download,true);assert.equal(manager.snapshot().can_install,false);
  await assert.rejects(manager.install(),/手动运行/);assert.equal(calls.quit+calls.launch,0);
});

test('same-version source users can download the installer; installed users do not reinstall it',async t=>{
  const source=fixture(t,{currentVersion:'0.0.2'});await source.manager.check();assert.equal(source.manager.snapshot().status,'current');
  assert.equal(source.manager.snapshot().can_download,true);await source.manager.download();
  const installed=fixture(t,{currentVersion:'0.0.2',packaged:true});await installed.manager.check();
  assert.equal(installed.manager.snapshot().status,'current');assert.equal(installed.manager.snapshot().can_download,false);
  await assert.rejects(installed.manager.download());
});

test('an older published version is distinguished and cannot trigger a downgrade',async t=>{
  const {manager}=fixture(t,{currentVersion:'0.1.0'});await manager.check();assert.equal(manager.snapshot().status,'ahead');
  assert.equal(manager.snapshot().can_download,false);await assert.rejects(manager.download());
});

test('default automatic download downloads only a newer version and never installs',async t=>{
  const {manager,calls}=fixture(t);manager.save({auto_download:true});await manager.check();
  assert.equal(calls.downloads,1);assert.equal(calls.launch+calls.quit,0);
  const same=fixture(t,{currentVersion:'0.0.2'});same.manager.save({auto_download:true});await same.manager.check();
  assert.equal(same.calls.downloads,0);
});

test('cached downloads survive a source restart and are reverified before revealing',async t=>{
  const {manager,config}=fixture(t);await manager.check();await manager.download();
  const reopened=createUpdateManager(config);t.after(()=>reopened.dispose());assert.equal(reopened.snapshot().status,'downloaded');
  const file=await reopened.revealDownload();fs.writeFileSync(file,Buffer.alloc(64*1024,18));
  await assert.rejects(reopened.revealDownload(),/内容发生变化/);assert.equal(reopened.snapshot().can_reveal_download,false);
});

test('failure can be retried without duplicate requests or installation',async t=>{
  let fail=true,checks=0;const {manager,calls,meta}=fixture(t,{releaseClient:{check:async()=>{checks++;
    if(fail)throw new Error('temporary network problem');return releaseInfo(meta);}}});
  await assert.rejects(manager.check());assert.equal(manager.snapshot().status,'error');fail=false;
  await Promise.all([manager.check(),manager.check()]);assert.equal(checks,2);assert.equal(manager.snapshot().status,'available');
  assert.equal(calls.quit+calls.launch,0);
});

test('cancelling a download is independent of the active download IPC promise',async t=>{
  let started;const ready=new Promise(r=>started=r);const {manager,meta}=fixture(t,{releaseClient:{
    check:async()=>releaseInfo(meta),download:async(info,file,{signal})=>new Promise((resolve,reject)=>{
      started();signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError')),{once:true});})}});
  await manager.check();const pending=manager.download();await ready;assert.equal(manager.snapshot().can_cancel,true);
  manager.cancelDownload();await pending;assert.equal(manager.snapshot().status,'cancelled');assert.equal(manager.snapshot().can_download,true);
});

test('rate limiting prevents scheduled or repeated checks until the retry time',async t=>{
  let calls=0;const {manager}=fixture(t,{releaseClient:{check:async()=>{calls++;const e=new Error('rate limited');
    e.retry_at=new Date(Date.now()+60000).toISOString();throw e;}}});
  await assert.rejects(manager.check());await assert.rejects(manager.check(),/暂时受限/);assert.equal(calls,1);
});

test('release-page and reveal IPC use manager-validated targets and reject foreign frames',async t=>{
  const {manager}=fixture(t);await manager.check();await manager.download();const handlers={},opened=[],revealed=[];
  const mainFrame={url:'http://127.0.0.1:4321/'},win={webContents:{mainFrame}};
  registerUpdateHandlers({handle:(key,callback)=>handlers[key]=callback},'http://127.0.0.1:4321',()=>win,manager,()=>{},()=>false,
    address=>opened.push(address),file=>revealed.push(file));
  const event={sender:win.webContents,senderFrame:mainFrame};handlers['studyforge:update-release'](event);
  await handlers['studyforge:update-reveal'](event);assert.match(opened[0],/^https:\/\/github.com\/keke271828\/StudyForge\/releases\/tag\//);
  assert.equal(revealed[0],await manager.revealDownload());
  for(const handler of Object.values(handlers))assert.throws(()=>handler({sender:win.webContents,senderFrame:{url:mainFrame.url}}));
});

test('automatic checks start after launch in source mode and obey the saved off switch',async t=>{
  t.mock.timers.enable({apis:['setTimeout','setInterval']});
  const active=fixture(t);active.manager.start();t.mock.timers.tick(20000);await active.manager.check();
  assert.equal(active.calls.checks,1);
  active.manager.save({auto_check:false});t.mock.timers.tick(24*3600000);
  assert.equal(active.calls.checks,1);
});
