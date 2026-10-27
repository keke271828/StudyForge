const { app, BrowserWindow, clipboard, dialog, ipcMain, session, Tray, Menu, shell, Notification } = require('electron');
const {randomBytes} = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { registerClipboardHandler } = require('./clipboard');
const { registerBrowserImporter } = require('./browser_import');
const {createDesktopLifecycle,registerDesktopHandlers} = require('./lifecycle');
const {attachWindowControls,registerWindowHandlers}=require('./window_controls');
const {createUpdateManager,registerUpdateHandlers}=require('./updates');
const {createNotificationManager,registerNotificationHandlers}=require('./notifications');
const {ensureNotificationIdentity}=require('./notification_identity');
const {registerMobileHandlers}=require('./mobile');
const {createStartupManager,registerStartupHandlers,isAutostartLaunch,startHidden}=require('./startup');

let backend;
let window;
let url;
let backendFailure;
let desktopLifecycle;
let windowOpening;
let updateManager;
let updateExit;
let notificationManager;
let startupManager;
let mainReady;
const desktopToken=randomBytes(32).toString('hex');
const smokeReport = process.env.STUDYFORGE_SMOKE_REPORT;
const smokeCodexRequests = [];
const backendAlive=()=>Boolean(backend&&backend.exitCode===null&&backend.signalCode===null);
app.setName('StudyForge');
if(process.platform==='win32')app.setAppUserModelId(app.isPackaged?'org.studyforge.desktop':'org.studyforge.desktop.source');
if (smokeReport) app.setPath('userData', path.join(path.dirname(smokeReport), 'electron-profile'));

function backendCommand() {
  if (app.isPackaged) {
    const command = path.join(process.resourcesPath, 'backend', 'StudyForgeBackend.exe');
    if (!fs.existsSync(command)) throw new Error('安装文件不完整，请重新安装 StudyForge。');
    return { command, args: [] };
  }
  const python = findPython();
  const moduleName=smokeReport&&process.env.STUDYFORGE_SMOKE_STARTUP==='1'?'scripts.smoke_startup_backend':
    smokeReport&&process.env.STUDYFORGE_SMOKE_TRAY==='1'?'scripts.smoke_tray_backend':'studyforge.server';
  return { command: python.command, args: [...python.prefix, '-m', moduleName] };
}

function findPython() {
  const root = path.resolve(__dirname, '..');
  const saved = path.join(root, '.studyforge-python');
  const candidates = [process.env.STUDYFORGE_PYTHON];
  if (fs.existsSync(saved)) candidates.push(fs.readFileSync(saved, 'utf8').trim());
  if (process.env.LOCALAPPDATA) {
    for (const version of ['Python313', 'Python312', 'Python314'])
      candidates.push(path.join(process.env.LOCALAPPDATA, 'Programs', 'Python', version, 'python.exe'));
  }
  candidates.push('python', 'py');
  for (const command of candidates.filter(Boolean)) {
    if (path.isAbsolute(command) && !fs.existsSync(command)) continue;
    const prefix = command === 'py' ? ['-3.12'] : [];
    const check = spawnSync(command, [...prefix, '-c', 'import studyforge'],
      { cwd: root, windowsHide: true, timeout: 10000, encoding: 'utf8' });
    if (check.status === 0) return { command, prefix };
  }
  throw new Error('缺少启动软件所需的 Python 环境。请运行项目文件夹里的 setup_studyforge.cmd 完成安装。');
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)); });
    server.on('error', reject);
  });
}

async function waitForBackend() {
  for (let i = 0; i < 150; i++) {
    if (backendFailure) throw backendFailure;
    try {
      const response = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch (_) { /* server is starting */ }
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  throw new Error('学习服务没有及时启动。请重新打开软件；仍失败时，可查看学习资料文件夹里的 logs/backend.log。');
}

async function createWindow() {
  const port = await freePort();
  url = `http://127.0.0.1:${port}`;
  const launch = backendCommand();
  const dataDirectory = path.resolve(process.env.STUDYFORGE_DATA_DIR
    || path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'StudyForge'));
  const logDirectory = path.join(dataDirectory, 'logs');
  fs.mkdirSync(logDirectory, { recursive: true });
  const logFile = path.join(logDirectory, 'backend.log');
  // Bound the startup log without touching learning materials or the database.
  if (fs.existsSync(logFile) && fs.statSync(logFile).size > 5 * 1024 * 1024)
    fs.renameSync(logFile, `${logFile}.previous`);
  const log = fs.openSync(logFile, 'a');
  backend = spawn(launch.command, launch.args, {
    cwd: app.isPackaged ? dataDirectory : path.resolve(__dirname, '..'),
    windowsHide: true,
    stdio: ['ignore', log, log],
    env: { ...process.env, PYTHONUTF8: '1', STUDYFORGE_PORT: String(port),
      STUDYFORGE_DATA_DIR: dataDirectory, STUDYFORGE_PARENT_PID: String(process.pid),
      STUDYFORGE_APPLICATION_ROOT: app.isPackaged ? path.dirname(app.getPath('exe')) : path.resolve(__dirname, '..'),
      STUDYFORGE_DESKTOP_TOKEN:desktopToken }
  });
  fs.closeSync(log);
  startupManager=createStartupManager({app,storageDirectory:dataDirectory,projectRoot:path.resolve(__dirname,'..'),
    ...(smokeReport?{name:'StudyForge.Acceptance.'+path.basename(path.dirname(smokeReport))}:{})});
  try{startupManager.reconcile();}catch(error){console.error('开机启动设置：'+error.message);}
  backend.on('error', error => { backendFailure = error; });
  backend.on('exit', (code, signal) => {
    backendFailure = new Error(`本机服务已退出（${code ?? signal}）。日志：${logFile}`);
  });
  const localOrigin = new URL(url).origin;
  if (smokeReport) session.defaultSession.webRequest.onBeforeRequest(
    { urls: [`${localOrigin}/api/codex/*`] }, (details, callback) => {
      smokeCodexRequests.push(details.url); callback({ cancel: false });
    });
  registerClipboardHandler(ipcMain, clipboard, localOrigin);
  ipcMain.handle('studyforge:choose-directory', async event => {
    const frame = event.senderFrame;
    if (!frame || frame !== event.sender.mainFrame || new URL(frame.url).origin !== localOrigin) throw new Error('只允许 StudyForge 窗口选择目录');
    const selected = await dialog.showOpenDialog(window, { title: '选择 AI 可访问的目录', properties: ['openDirectory'] });
    return selected.canceled ? null : selected.filePaths[0];
  });
  registerBrowserImporter(ipcMain, localOrigin, () => window);
  const isLocal = value => {
    try { return new URL(value).origin === localOrigin; } catch (_) { return false; }
  };
  session.defaultSession.setPermissionCheckHandler((_contents, permission, requestingOrigin) =>
    permission === 'media' && isLocal(requestingOrigin));
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(permission === 'media' && isLocal(details.requestingUrl || contents.getURL()));
  });
  const desktopRequest=(resource,method='GET',body)=>fetch(url+resource,{method,
    headers:{'X-StudyForge-Desktop-Token':desktopToken,...(body?{'Content-Type':'application/json'}:{})},
    ...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(resource.startsWith('/api/mobile/')?20000:3000)});
  desktopLifecycle=createDesktopLifecycle({app,Tray,Menu,icon:path.join(__dirname,'assets','studyforge.ico'),
    getWindow:()=>window,showWindow:view=>openMainWindow(true,view).catch(error=>console.error(error.message)),
    readStatus:async()=>{const response=await desktopRequest('/api/desktop/status');if(!response.ok)throw new Error('本机状态暂不可用');return response.json();},
    prepareShutdown:async()=>{
      if(window&&!window.isDestroyed()&&new URL(window.webContents.getURL()).origin===localOrigin){
        await Promise.race([window.webContents.executeJavaScript('typeof prepareDesktopExit === "function" ? prepareDesktopExit() : null'),
          new Promise(resolve=>{const timer=setTimeout(resolve,1200);timer.unref();})]).catch(()=>{});
      }
      if(!backendAlive())return;
      const query=updateExit?'?'+new URLSearchParams({current_version:updateExit.from,target_version:updateExit.target}):'';
      const response=await desktopRequest('/api/desktop/shutdown'+query,'POST');
      if(!response.ok)throw new Error('任务状态未收到退出确认，下次启动将恢复中断状态');
      return response.json();
    },stopBackend:async()=>{
      if(!backendAlive())return;
      await new Promise((resolve,reject)=>{
        const ended=()=>{clearTimeout(timeout);resolve();};backend.once('exit',ended);
        const timeout=setTimeout(()=>{backend.removeListener('exit',ended);reject(new Error('后台尚未结束，已取消安装'));},2500);
        backend.kill();
      });
    },
    onError:error=>console.error('桌面运行：'+error.message)});
  registerDesktopHandlers(ipcMain,localOrigin,()=>window,desktopLifecycle);
  registerStartupHandlers(ipcMain,localOrigin,()=>window,startupManager);
  registerMobileHandlers(ipcMain,localOrigin,()=>window,desktopRequest,dialog);
  registerWindowHandlers(ipcMain,localOrigin,()=>window);
  if(!smokeReport){
    try{ensureNotificationIdentity({app,shell,root:path.join(__dirname,'..'),icon:path.join(__dirname,'assets','studyforge.ico')});}
    catch(error){console.error('Windows 通知身份：'+error.message);}
  }
  notificationManager=createNotificationManager({Notification,icon:path.join(__dirname,'assets','studyforge.ico'),
    getWindow:()=>window,showWindow:target=>openMainWindow(true,target),
    readFeed:async()=>{const response=await desktopRequest('/api/desktop/notifications');if(!response.ok)throw new Error('桌面通知暂时无法读取本机服务');return response.json();},
    acknowledge:async(ids,status)=>{const response=await desktopRequest('/api/desktop/notifications/ack','POST',{ids,status});if(!response.ok)throw new Error('桌面通知回执未保存');},
    notify:value=>{if(window&&!window.isDestroyed())window.webContents.send('studyforge:notification-changed',value);},
    onError:error=>console.error('桌面通知：'+error.message)});
  registerNotificationHandlers(ipcMain,localOrigin,()=>window,notificationManager);
  app.on('before-quit',()=>notificationManager.dispose());
  backend.on('exit',()=>{if(!desktopLifecycle.status().quitting)notificationManager.backendStopped();});
  desktopLifecycle.start();
  await openMainWindow();
  if(!smokeReport)await notificationManager.start();
  const releaseConfig=require('./release-config.json');
  const requestUpdateQuit=action=>{if(desktopLifecycle.status().quitting)throw new Error('应用正在退出');updateExit=action;
    setImmediate(()=>{try{desktopLifecycle.quitAfterSave(action);}catch(error){updateExit=null;action.onFailure(error);}});};
  updateManager=createUpdateManager({currentVersion:app.getVersion(),packaged:app.isPackaged,
    storageDirectory:app.getPath('userData'),publishers:releaseConfig.publishers,initialFeed:releaseConfig.feed_url,
    createUpdater:options=>new (require('electron-updater').NsisUpdater)(options),
    requestQuit:requestUpdateQuit,
    launchInstaller,
    notify:state=>{if(window&&!window.isDestroyed())window.webContents.send('studyforge:update-changed',state);notificationManager.update(state);}});
  registerUpdateHandlers(ipcMain,localOrigin,()=>window,updateManager,
    async()=>{const folder=path.join(dataDirectory,'update-backups');fs.mkdirSync(folder,{recursive:true});
      const error=await shell.openPath(folder);if(error)throw new Error(error);return true;},
    async()=>{const result=await dialog.showMessageBox(window,{type:'question',title:'恢复软件安装',
      message:`使用已保存的 ${updateManager.snapshot().rollback_version} 安装包恢复安装？`,
      detail:'将备份当前数据库和设置，再重新安装。学习资料继续保留；请确认所选安装包支持当前学习数据。',
      buttons:['取消','保存并恢复安装'],defaultId:0,cancelId:0});return result.response===1;});
  updateManager.start();app.on('will-quit',()=>updateManager.dispose());
  if(smokeReport&&process.env.STUDYFORGE_SMOKE_STARTUP==='1'){
    await require('../scripts/smoke_desktop_startup').run({app,window,lifecycle:desktopLifecycle,backend,url,report:smokeReport,
      startupManager,ownerToken:desktopToken});return;
  }
  if(smokeReport&&process.env.STUDYFORGE_SMOKE_UPDATES==='1'){
    await require('../scripts/smoke_updates').run({app,window,lifecycle:desktopLifecycle,backend,url,report:smokeReport,
      ownerToken:desktopToken,sourceManager:updateManager,requestQuit:requestUpdateQuit});return;
  }
  if(smokeReport&&process.env.STUDYFORGE_SMOKE_TRAY==='1'){
    await require('../scripts/smoke_desktop_tray').run({app,window,lifecycle:desktopLifecycle,backend,url,report:smokeReport,ownerToken:desktopToken});
    return;
  }
  if (smokeReport) {
    await runStartupSmoke(launch);
  }
}

async function launchInstaller(file,needsElevation){
  // The path comes only from the manager's hash and publisher-verified local cache.
  const args=['--updated','/S','--force-run'];
  const launch=(command,arguments_)=>new Promise((resolve,reject)=>{
    const installer=spawn(command,arguments_,{detached:true,windowsHide:true,stdio:'ignore'});
    installer.once('error',reject);installer.once('spawn',()=>{installer.unref();resolve();});
  });
  const elevated=()=>launch(path.join(process.resourcesPath,'elevate.exe'),[file,...args]);
  if(needsElevation)return elevated();
  try{await launch(file,args);}catch(error){if(['EACCES','UNKNOWN'].includes(error.code))await elevated();else throw error;}
}

async function openMainWindow(show=false,view) {
  if(windowOpening)await windowOpening;
  if(window&&!window.isDestroyed()){
    if(show){revealWindow(window);
      window.webContents.send('studyforge:desktop-visible');}
    if(view)window.webContents.send('studyforge:desktop-navigate',view);
    return window;
  }
  windowOpening=(async()=>{
  window = new BrowserWindow({
    width: 1480, height: 960, minWidth: 1080, minHeight: 700,
    title: 'StudyForge', backgroundColor: '#f5f6f2',
    show: !smokeReport&&(!startHidden(process.argv)||!desktopLifecycle.status().tray_available||show), autoHideMenuBar: true,
    icon: path.join(__dirname, 'assets', 'studyforge.ico'),
    webPreferences: {
      nodeIntegration: false, contextIsolation: true, sandbox: true,
      backgroundThrottling: !smokeReport,
      preload: path.join(__dirname, 'preload.js')
    }
  });
  if(smokeReport)window.setPosition(-30000,-30000);
  desktopLifecycle.attachWindow(window);
  attachWindowControls(window);
  window.on('closed',()=>{window=null;});
  if (!app.isPackaged) window.on('page-title-updated', (event, title) => {
    event.preventDefault(); window.setTitle(`${title} · 源码运行`);
  });
  window.webContents.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith('https://')) require('electron').shell.openExternal(target);
    return { action: 'deny' };
  });
  await window.loadFile(path.join(__dirname, 'loading.html'));
  await waitForBackend();
  await window.loadURL(url);
  if(show)revealWindow(window);
  if(view)window.webContents.send('studyforge:desktop-navigate',view);
  return window;
  })();
  try{return await windowOpening;}finally{windowOpening=null;}
}

function revealWindow(win){
  if(win.isMinimized())win.restore();win.show();
  // Windows can pass SW_HIDE to a login launch. Its first ShowWindow call
  // consumes that startup state; a manual open must still reveal the window.
  if(!win.isVisible()){win.hide();win.show();}
  win.focus();
}

async function runStartupSmoke(launch) {
    for (let i = 0; i < 50; i++) {
      if (await window.webContents.executeJavaScript('Boolean(state.settings)')) break;
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    const health = await (await fetch(`${url}/api/health`)).json();
    let models;
    if (process.env.STUDYFORGE_SMOKE_MODELS === '1' && health.codex_available) {
      const catalog = await (await fetch(`${url}/api/codex/models`, { signal: AbortSignal.timeout(45000) })).json();
      if (!catalog.models?.length) throw new Error(`安装版无法读取 Codex 模型：${JSON.stringify(catalog)}`);
      models = { count: catalog.models.length, source: catalog.source, warning: catalog.warning };
    }
    const project = await (await fetch(`${url}/api/projects`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: '安装版自检' }) })).json();
    const form = new FormData();
    form.append('project_id', project.id);
    form.append('file', new Blob(['牛顿第二定律：F = ma。'], { type: 'text/plain' }), 'physics.txt');
    const stored = await (await fetch(`${url}/api/import/file`, { method: 'POST', body: form })).json();
    if(stored.status!=='stored'||stored.job_id!==null||!stored.source_id)
      throw new Error('安装版上传未遵循先入库后主动解析：'+JSON.stringify(stored));
    const imported = await (await fetch(`${url}/api/sources/${stored.source_id}/parse`, {method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'full'})})).json();
    if(!imported.job_id)throw new Error('安装版主动解析未启动：'+JSON.stringify(imported));
    let job;
    for (let i = 0; i < 100; i++) {
      job = await (await fetch(`${url}/api/jobs/${imported.job_id}`)).json();
      if (['completed', 'failed'].includes(job.status)) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const ui = await window.webContents.executeJavaScript(`({
      title: document.title, projectForm: Boolean(document.getElementById('newProject')),
      desktopBridge: typeof window.studyforgeDesktop?.copyText === 'function',
      modelPicker: Boolean(document.getElementById('studyModel')),
      provider: document.getElementById('provider').value,
      codexRequests: ${JSON.stringify(smokeCodexRequests)}
    })`);
    ui.quoteStyles = await window.webContents.executeJavaScript(`(() => {
      const container = message('assistant', '> 原文引用\\n\\nAI 讲解\\n<img src=x onerror=alert(1)>');
      const quote = container.querySelector('.lesson-quote');
      const explanation = container.querySelector('.lesson-explanation');
      const sourceStyle = getComputedStyle(quote), aiStyle = getComputedStyle(explanation);
      return Boolean(quote && explanation && sourceStyle.color !== aiStyle.color
        && sourceStyle.fontFamily !== aiStyle.fontFamily && !container.querySelector('img'));
    })()`);
    ui.assessmentControls = await window.webContents.executeJavaScript(`(() => {
      const provider = $('provider'), model = $('studyModel'), effort = $('reasoningEffort');
      const prior = { provider: provider.value, models: model.innerHTML, model: model.value,
        efforts: effort.innerHTML, effort: effort.value };
      try {
        model.innerHTML = '<option value="acceptance-model">Acceptance</option>';
        effort.innerHTML = '<option value="high">high</option>';
        provider.value = 'codex';
        const selection = assessmentSelection(), upload = assessmentUpload(new File(['answer'], 'answer.txt'));
        if (selection.model !== 'acceptance-model' || selection.reasoning_effort !== 'high'
          || upload.get('model') !== 'acceptance-model' || upload.get('reasoning_effort') !== 'high') return false;
        provider.value = 'deepseek';
        if (assessmentSelection().reasoning_effort !== 'high'
          || assessmentUpload(new File(['answer'], 'answer.txt')).get('reasoning_effort') !== 'high') return false;
        effort.value = '';
        return assessmentSelection().reasoning_effort === null
          && !assessmentUpload(new File(['answer'], 'answer.txt')).has('reasoning_effort');
      } finally {
        provider.value = prior.provider; model.innerHTML = prior.models; model.value = prior.model;
        effort.innerHTML = prior.efforts; effort.value = prior.effort;
      }
    })()`);
    ui.apiNetworkControls = await window.webContents.executeJavaScript(`(async () => {
      const prior = apiNetworkSettings.confirmed;
      showView('settings');$('settings-tab-models').click();
      const select=$('apiConnectionMode');
      if(!select?.checkVisibility())return false;
      async function selectMode(mode){
        select.value=mode;select.dispatchEvent(new Event('change'));
        for(let i=0;i<100&&apiNetworkSettings.pending;i++)await new Promise(resolve=>setTimeout(resolve,50));
        const saved=await api('/api/settings');
        return !apiNetworkSettings.pending&&apiNetworkSettings.confirmed===mode&&saved.api_connection_mode===mode;
      }
      try{return await selectMode('direct')&&await selectMode('system');}
      finally{await selectMode(prior);showView('study');}
    })()`);
    ui.userGuide = await window.webContents.executeJavaScript(`(async () => {
      const prompt = $('prompt').value, chat = state.conversation;
      window.studyforgeUserGuide.open('materials');
      const dialog = $('userGuideDialog');
      let document;
      for (let n = 0; n < 100; n++) {
        document = dialog.querySelector('iframe').contentDocument;
        if (document?.getElementById('guideSearch') && dialog.querySelector('.user-guide-loading').hidden) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (!document?.getElementById('guideSearch')) throw Error('安装版未载入内置指南');
      const sections = ['start','map','models','projects','materials','library','tutor','teaching','outputs',
        'feedback','homework','profile','goals','permissions','phone','background','appearance','troubleshooting','teaching-review'];
      const complete = document.querySelectorAll('.guide-section').length === sections.length
        && sections.every(id => document.getElementById(id)?.classList.contains('guide-section'))
        && document.getElementById('materials').querySelectorAll('.guide-steps > li').length >= 3
        && document.getElementById('library').querySelectorAll('.guide-steps > li').length >= 5
        && Boolean(document.getElementById('library').querySelector('[data-guide-action="library"]'));
      document.getElementById('guideSearch').value = '完整提交';
      document.getElementById('guideSearch').dispatchEvent(new Event('input'));
      const searched = !document.getElementById('homework').hidden
        && document.querySelectorAll('.guide-section:not([hidden])').length < sections.length;
      dialog.close();
      return complete && searched && $('prompt').value === prompt && state.conversation === chat;
    })()`);
    ui.historyRenderer = await window.webContents.executeJavaScript(`(() => {
      const history = window.studyforgeMessageHistory, host = document.createElement('div');
      if (!history?.sync) return false;
      const rows = [{id:'native-first',role:'assistant',content:'已保存公式 $F=ma$'}];
      const create = row => makeMessage(row.role,row.content);
      history.sync(host,rows,create,{scope:'native-test'});
      const original = host.firstChild;
      rows.push({id:'native-second',role:'assistant',content:'独立任务已经完成'});
      const changes = history.sync(host,rows,create,{scope:'native-test'});
      return changes.rendered === 1 && changes.retained === 1 && host.firstChild === original
        && host.children.length === 2 && Boolean(original.querySelector('.katex'))
        && history.matches(host,rows,'native-test');
    })()`);
    if (!health.ok || !project.id || job.status !== 'completed' || !ui.projectForm || !ui.desktopBridge || !ui.quoteStyles || !ui.assessmentControls || !ui.apiNetworkControls || !ui.userGuide || !ui.historyRenderer)
      throw new Error(`安装版自检失败：${JSON.stringify({ health, project, job, ui })}`);
    let startup;
    try{
      startup=await window.webContents.executeJavaScript('window.studyforgeDesktop.saveStartupSettings({enabled:true,start_hidden:true})');
      if(!startup.enabled||!startup.start_hidden)throw new Error('安装版启动设置未启用');
      const entry=require('./windows_startup').readWindowsEntry(startup.launch_name);
      if(app.isPackaged&&JSON.stringify(entry.args)!==JSON.stringify(['--studyforge-autostart','--studyforge-start-hidden']))
        throw new Error('安装版启动项仍引用源码项目路径');
      ui.startupControls=await window.webContents.executeJavaScript("Boolean(document.getElementById('desktopAutoStart')&&document.getElementById('desktopStartHidden'))");
      if(!ui.startupControls)throw new Error('安装版缺少开机启动控件');
      startup={...startup,native_command:entry.command};
    }finally{startupManager.save({enabled:false,start_hidden:true});}
    fs.writeFileSync(smokeReport, JSON.stringify({ ok: true, packaged: app.isPackaged, version:app.getVersion(),startup,
      backend: launch.command, backend_pid: backend.pid, desktop_pid: process.pid,
      url, health, ui, stored, imported, models }, null, 2));
    app.quit();
}

if (app.requestSingleInstanceLock()) {
  mainReady=app.whenReady().then(createWindow).catch(error => {
    if (smokeReport) fs.writeFileSync(smokeReport, JSON.stringify({ ok: false, error: error.stack }));
    else dialog.showErrorBox('StudyForge 启动失败', error.message);
    app.quit();
  });
  app.on('second-instance', (_event,commandLine) => {
    if(isAutostartLaunch(commandLine))return;
    const open=()=>{
      if(desktopLifecycle&&!desktopLifecycle.status().quitting)
        return openMainWindow(true);
    };
    (desktopLifecycle?Promise.resolve().then(open):mainReady.then(open)).catch(error=>console.error(error.message));
  });
} else {
  app.quit();
}
