const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {createStartupManager,launchSettings,isAutostartLaunch,startHidden,registerStartupHandlers}=require('../desktop/startup');
const {windowsArgv}=require('../desktop/windows_startup');

function fixture(t){
  const buildRoot=path.resolve(__dirname,'../build');fs.mkdirSync(buildRoot,{recursive:true});
  const directory=fs.mkdtempSync(path.join(buildRoot,'startup-unit-'));
  t.after(()=>{assert.ok(directory.startsWith(buildRoot+path.sep));fs.rmSync(directory,{recursive:true,force:true});});
  const entries=new Map(),writes=[];
  const app={isPackaged:false,
    getLoginItemSettings:({path:executable})=>({launchItems:[...entries.values()].filter(row=>row.path===executable)}),
    setLoginItemSettings:value=>{writes.push(value);if(value.openAtLogin)entries.set(value.name,
      {name:value.name,path:value.path,args:value.args.map(arg=>arg.replace(/^"(.*)"$/,'$1')),scope:'user',enabled:value.enabled});else entries.delete(value.name);}};
  const make=(extra={})=>createStartupManager({app,storageDirectory:directory,projectRoot:'C:/学习 工作台',executable:'C:/StudyForge/electron.exe',platform:'win32',readEntry:name=>entries.get(name),...extra});
  return {directory,app,entries,writes,make,manager:make()};
}
test('source passes one raw path for native Windows quoting; installed command launches directly',()=>{
  const source=launchSettings({packaged:false,executable:'electron.exe',projectRoot:'C:/学习 工作台'});
  assert.equal(source.args[0],path.resolve('C:/学习 工作台'));
  assert.ok(isAutostartLaunch(source.args)&&startHidden(source.args));
  const installed=launchSettings({packaged:true,executable:'StudyForge.exe',projectRoot:'unused',hidden:false});
  assert.deepEqual(installed.args,['--studyforge-autostart']);assert.equal(startHidden(installed.args),false);
  assert.equal(startHidden(['--studyforge-start-hidden']),false);
});
test('actual Windows commands preserve spaces and distinguish literal escaped quotes',()=>{
  assert.deepEqual(windowsArgv('"C:\\Program Files\\StudyForge\\StudyForge.exe" "C:\\学习 工作台" --studyforge-autostart'),
    ['C:\\Program Files\\StudyForge\\StudyForge.exe','C:\\学习 工作台','--studyforge-autostart']);
  assert.deepEqual(windowsArgv('app.exe "hello\\\"world"'),['app.exe','hello"world']);
  assert.throws(()=>windowsArgv('app.exe "unfinished'),/引号不完整/);
});
test('real startup state is owned-name and arguments specific, not another Electron app',t=>{
  const {manager,entries}=fixture(t);
  entries.set('AnotherApp',{name:'AnotherApp',scope:'user',path:'C:/StudyForge/electron.exe',args:[],enabled:true});
  assert.equal(manager.status().enabled,false);
  assert.equal(manager.save({enabled:true,start_hidden:true}).enabled,true);
  assert.equal(manager.save({enabled:true,start_hidden:false}).start_hidden,false);
  assert.equal(entries.size,2);assert.equal(manager.save({enabled:false,start_hidden:false}).registered,false);
  assert.equal(entries.size,1);assert.ok(entries.has('AnotherApp'));
});
test('Windows disablement is shown and is not silently re-enabled on startup',t=>{
  const {manager,entries,writes}=fixture(t);manager.save({enabled:true,start_hidden:true});
  entries.get('StudyForge').enabled=false;const before=writes.length;
  assert.equal(manager.reconcile().enabled,false);assert.equal(manager.status().blocked_by_windows,true);
  assert.equal(writes.length,before);
  assert.equal(manager.save({enabled:true,start_hidden:true}).enabled,true);
});
test('switching to an installed executable migrates a single enabled owned entry',t=>{
  const {manager,app,make,entries}=fixture(t);manager.save({enabled:true,start_hidden:true});
  app.isPackaged=true;const installed=make({executable:'C:/Program Files/StudyForge/StudyForge.exe'});
  assert.equal(installed.reconcile().enabled,true);assert.equal(entries.size,1);
  assert.equal(entries.get('StudyForge').path,'C:/Program Files/StudyForge/StudyForge.exe');
  assert.deepEqual(entries.get('StudyForge').args,['--studyforge-autostart','--studyforge-start-hidden']);
});
test('migration respects an entry disabled in Windows',t=>{
  const {manager,app,make,entries,writes}=fixture(t);manager.save({enabled:true,start_hidden:true});
  entries.get('StudyForge').enabled=false;const before=writes.length;app.isPackaged=true;
  make({executable:'C:/New/StudyForge.exe'}).reconcile();assert.equal(writes.length,before);
  assert.equal(entries.get('StudyForge').enabled,false);
});
test('invalid inputs and Windows registration failure never claim success',t=>{
  const {manager,app}=fixture(t);assert.throws(()=>manager.save({enabled:'true',start_hidden:true}));
  app.setLoginItemSettings=()=>{};assert.throws(()=>manager.save({enabled:true,start_hidden:true}),/Windows 未确认/);
  assert.equal(manager.status().enabled,false);
});

test('a partially registered command is rolled back when verification fails',t=>{
  const {manager,app,entries,directory}=fixture(t),write=app.setLoginItemSettings;
  app.setLoginItemSettings=value=>{write(value);if(value.openAtLogin)entries.get(value.name).args=['wrong'];};
  assert.throws(()=>manager.save({enabled:true,start_hidden:true}),/Windows 未确认/);
  assert.equal(entries.has('StudyForge'),false);
  assert.equal(fs.existsSync(path.join(directory,'desktop','startup.json')),false);
});

test('native read failure after changing settings restores the prior disabled entry',t=>{
  const {manager,app,make,entries,directory}=fixture(t);manager.save({enabled:true,start_hidden:true});
  entries.get('StudyForge').enabled=false;
  const prior=fs.readFileSync(path.join(directory,'desktop','startup.json'),'utf8');let reads=0;
  const failing=make({readEntry:name=>{if(++reads===2)throw new Error('Windows query unavailable');return entries.get(name);}});
  assert.throws(()=>failing.save({enabled:true,start_hidden:false}),/已恢复原启动项/);
  assert.equal(entries.get('StudyForge').enabled,false);assert.ok(entries.get('StudyForge').args.includes('--studyforge-start-hidden'));
  assert.equal(fs.readFileSync(path.join(directory,'desktop','startup.json'),'utf8'),prior);
});

test('redirected profile preferences save when rename crosses backing volumes',t=>{
  const {make,directory}=fixture(t);
  const files={...fs,renameSync:()=>{throw Object.assign(new Error('redirected profile'),{code:'EXDEV'});}};
  const manager=make({files});assert.equal(manager.save({enabled:true,start_hidden:true}).enabled,true);
  assert.equal(JSON.parse(fs.readFileSync(path.join(directory,'desktop','startup.json'),'utf8')).enabled,true);
  assert.equal(fs.existsSync(path.join(directory,'desktop','startup.json.tmp')),false);
});

test('failed cross-volume copy restores both saved preferences and native startup',t=>{
  const {manager,make,directory,entries}=fixture(t);manager.save({enabled:true,start_hidden:true});
  const file=path.join(directory,'desktop','startup.json'),previous=fs.readFileSync(file,'utf8');
  const files={...fs,renameSync:()=>{throw Object.assign(new Error('redirected profile'),{code:'EXDEV'});},
    copyFileSync:(_,destination)=>{fs.writeFileSync(destination,'{');throw Object.assign(new Error('copy denied'),{code:'EACCES'});}};
  assert.throws(()=>make({files}).save({enabled:false,start_hidden:false}),/已恢复原启动项/);
  assert.equal(fs.readFileSync(file,'utf8'),previous);assert.equal(manager.status().enabled,true);
  assert.ok(entries.get('StudyForge').args.includes('--studyforge-start-hidden'));
  assert.equal(fs.existsSync(file+'.tmp'),false);
});
test('startup IPC rejects foreign frames and exposes no arbitrary registry names',t=>{
  const {manager}=fixture(t),handlers={};
  const win={webContents:{mainFrame:{url:'http://127.0.0.1:1234/'}}};
  registerStartupHandlers({handle:(name,callback)=>{handlers[name]=callback;}},'http://127.0.0.1:1234',()=>win,manager);
  const event={sender:win.webContents,senderFrame:win.webContents.mainFrame};
  assert.equal(handlers['studyforge:startup-status'](event).available,true);
  assert.throws(()=>handlers['studyforge:startup-save']({...event,senderFrame:{url:event.senderFrame.url}},{enabled:true,start_hidden:true}),/主窗口/);
  win.webContents.mainFrame.url='https://external.example/';
  assert.throws(()=>handlers['studyforge:startup-status'](event),/主窗口/);
});
