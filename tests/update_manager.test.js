const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {EventEmitter}=require('node:events');
const {createUpdateManager,registerUpdateHandlers,candidateInfo,preferences,compareVersions}=require('../desktop/updates');
const {releaseConfiguration}=require('../scripts/release_config');

function fixture(t,overrides={}){
  const build=path.resolve(__dirname,'../build');fs.mkdirSync(build,{recursive:true});
  const root=fs.mkdtempSync(path.join(build,'update-unit-'));
  t.after(()=>{assert.ok(path.resolve(root).startsWith(build+path.sep));fs.rmSync(root,{recursive:true,force:true});});
  const data=Buffer.from('MZ isolated non-executable update fixture'),file=path.join(root,'provider.exe');fs.writeFileSync(file,data);
  const info={version:'0.3.5',files:[{url:'StudyForge-Setup-0.3.5.exe',size:data.length,sha512:crypto.createHash('sha512').update(data).digest('base64')}],releaseNotes:'<img src=x onerror=alert(1)> Release notes'};
  const calls={check:0,download:0,verify:0,quit:[],launch:[],changes:[]};
  class Updater extends EventEmitter{
    async checkForUpdates(){calls.check++;if(this.wait)await this.wait;return {updateInfo:info};}
    async downloadUpdate(){calls.download++;this.emit('download-progress',{percent:50,total:data.length,transferred:data.length/2});return [file];}
    async verifyUpdateCodeSignature(names,p){calls.verify++;assert.deepEqual(names,['Test Publisher']);assert.ok(p.startsWith(root+path.sep));return this.signatureError||null;}
  }
  const updater=new Updater();
  const options={currentVersion:'0.3.4',packaged:true,storageDirectory:root,publishers:['Test Publisher'],initialFeed:'https://updates.example.test/windows/',
    createUpdater:()=>updater,requestQuit:action=>calls.quit.push(action),notify:value=>calls.changes.push(value),
    launchInstaller:async p=>calls.launch.push(p),...overrides};
  const manager=createUpdateManager(options);t.after(()=>manager.dispose());return {root,file,data,info,calls,updater,options,manager};
}
test('a source build saves preferences across launch but never downloads or executes',async t=>{
  const {manager,options,calls}=fixture(t,{packaged:false});
  manager.save({feed_url:'https://downloads.example.test/stable',auto_check:false,auto_download:true,interval_hours:6});
  const reopened=createUpdateManager(options);t.after(()=>reopened.dispose());
  assert.equal(reopened.snapshot().settings.interval_hours,6);assert.equal(reopened.snapshot().status,'development');
  for(const method of ['check','download','install'])await assert.rejects(()=>reopened[method](),/项目文件夹打开的测试版/);
  assert.equal(calls.check+calls.download+calls.launch.length,0);
});
for(const bad of ['http://example.test/','file:///C:/Windows/','https://user:password@example.test/','https://example.test/?token=x','https://example.test/latest.yml','https://example.test/update.exe'])
  test('reject update-source bypass: '+bad,()=>assert.throws(()=>preferences({feed_url:bad})));
test('stable version comparison is numeric and automatic downgrade is blocked',async t=>{
  assert.equal(compareVersions('0.3.10','0.3.9'),1);
  const {manager,info,calls}=fixture(t);info.version='0.3.3';info.files[0].url='StudyForge-Setup-0.3.3.exe';
  assert.equal((await manager.check()).status,'current');assert.equal(calls.download,0);
  await assert.rejects(()=>manager.install(),/尚无/);
});
test('check requests coalesce and settings cannot replace an in-flight feed',async t=>{
  const {manager,updater,calls}=fixture(t);let release;updater.wait=new Promise(resolve=>{release=resolve;});
  const a=manager.check(),b=manager.check();assert.throws(()=>manager.save({feed_url:'https://other.example/'}),/等待/);
  release();assert.equal((await a).status,'available');await b;assert.equal(calls.check,1);
});
test('automatic download verifies the binary and does not install on ordinary exit',async t=>{
  const {manager,updater,calls}=fixture(t);manager.save({feed_url:'https://updates.example.test/windows/',auto_download:true});
  const state=await manager.check();assert.equal(state.status,'downloaded');assert.equal(calls.download,1);assert.equal(calls.launch.length,0);
  assert.equal(updater.autoInstallOnAppQuit,false);assert.equal(updater.disableWebInstaller,true);assert.equal(updater.allowDowngrade,false);
  assert.ok(calls.changes.some(x=>x.progress?.percent===50));
});
for(const mutate of [info=>{info.files[0].sha512='bad';},info=>{info.files[0].url='OtherApp.exe';},
                     info=>{info.files[0].url='http://example.test/StudyForge-Setup-0.3.5.exe';},
                     info=>{info.packages={x64:{}};},info=>{info.version='0.3.5-beta';},info=>{info.files[0].size=0;}])
  test('invalid release metadata cannot trigger a download',async t=>{
    const {manager,info,calls}=fixture(t);mutate(info);await assert.rejects(()=>manager.check());assert.equal(calls.download,0);assert.equal(calls.launch.length,0);
  });
test('tampered download content is rejected independently of updater success',async t=>{
  const {manager,file,calls}=fixture(t);await manager.check();fs.writeFileSync(file,Buffer.from('MZ altered provider binary'));
  await assert.rejects(()=>manager.download(),/校验值/);assert.equal(calls.quit.length,0);assert.equal(manager.snapshot().can_install,false);
});
test('publisher mismatch prevents a package becoming installable',async t=>{
  const {manager,updater,calls}=fixture(t);await manager.check();updater.signatureError='not the trusted publisher';
  await assert.rejects(()=>manager.download(),/签名核验失败/);assert.equal(calls.quit.length,0);
});
test('missing signing configuration never runs a cached installer',async t=>{
  const {manager,calls}=fixture(t,{publishers:[]});await manager.check();await manager.download();
  assert.equal(manager.snapshot().can_install,false);await assert.rejects(()=>manager.install(),/尚未设置发布者身份/);assert.equal(calls.quit.length,0);
});
test('installation waits for exit saving and a backup receipt before execution',async t=>{
  const {manager,calls}=fixture(t);await manager.check();await manager.download();await manager.install();
  assert.equal(calls.launch.length,0);assert.equal(calls.quit.length,1);
  await assert.rejects(()=>calls.quit[0].afterStop({}),/尚未确认学习记录已备份/);assert.equal(calls.launch.length,0);
});
test('cache changed before exit never interrupts the current app',async t=>{
  const {manager,root,calls}=fixture(t);await manager.check();await manager.download();
  fs.writeFileSync(path.join(root,'update-installers/StudyForge-Setup-0.3.5.exe'),'altered');
  await assert.rejects(()=>manager.install(),/内容发生变化/);assert.equal(calls.quit.length,0);
});
test('cache changed while shutdown runs cannot be executed',async t=>{
  const {manager,root,calls}=fixture(t);await manager.check();await manager.download();await manager.install();
  fs.writeFileSync(path.join(root,'update-installers/StudyForge-Setup-0.3.5.exe'),'altered after verification');
  await assert.rejects(()=>calls.quit[0].afterStop({backup:{id:'snapshot'}}),/内容发生变化/);assert.equal(calls.launch.length,0);
});
test('download restart, successful switch and manual rollback reuse verified local files',async t=>{
  const {manager,options,calls,info}=fixture(t);await manager.check();await manager.download();
  const restarted=createUpdateManager(options);t.after(()=>restarted.dispose());assert.equal(restarted.snapshot().status,'downloaded');
  await restarted.install();await calls.quit.at(-1).afterStop({backup:{id:'first-backup'}});
  const current=createUpdateManager({...options,currentVersion:'0.3.5'});t.after(()=>current.dispose());
  assert.equal(current.snapshot().recovery.id,'first-backup');assert.equal(current.snapshot().can_rollback,false);
  info.version='0.3.6';info.files[0].url='StudyForge-Setup-0.3.6.exe';await current.check();await current.download();
  await current.install();await calls.quit.at(-1).afterStop({backup:{id:'second-backup'}});
  const next=createUpdateManager({...options,currentVersion:'0.3.6'});t.after(()=>next.dispose());
  assert.equal(next.snapshot().rollback_version,'0.3.5');await next.install(true);
  assert.equal(calls.quit.at(-1).rollback,true);await calls.quit.at(-1).afterStop({backup:{id:'rollback-backup'}});
  assert.match(calls.launch.at(-1),/StudyForge-Setup-0\.3\.5\.exe$/);
});
test('release configuration preserves NSIS, offline backend and user-data policy',()=>{
  const pkg=require('../package.json');
  const release=releaseConfiguration(pkg,{feed_url:'https://updates.example.test/',publishers:['Test Publisher']});
  assert.equal(release.builder.win.forceCodeSigning,true);assert.equal(release.builder.nsis.deleteAppDataOnUninstall,false);
  assert.deepEqual(release.builder.extraResources,pkg.build.extraResources);assert.equal(release.builder.publish[0].provider,'generic');
  assert.throws(()=>releaseConfiguration(pkg,{feed_url:'https://updates.example.test/'}),/签名/);
});
test('all update IPC handlers reject foreign windows and child frames',async t=>{
  const {manager}=fixture(t),handlers={};const mainFrame={url:'http://127.0.0.1:4321/'};
  const win={webContents:{mainFrame}};
  registerUpdateHandlers({handle:(name,callback)=>{handlers[name]=callback;}},'http://127.0.0.1:4321',()=>win,manager,()=>true,()=>false);
  for(const handler of Object.values(handlers))assert.throws(()=>handler({sender:win.webContents,senderFrame:{url:mainFrame.url}}),/主窗口/);
  assert.equal(handlers['studyforge:update-status']({sender:win.webContents,senderFrame:mainFrame}).current_version,'0.3.4');
});
