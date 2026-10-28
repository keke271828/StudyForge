// Native Electron UI checks use the isolated model fixture, never paid services.
const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {createUpdateManager,registerUpdateHandlers}=require('../desktop/updates');
const caseFile=process.env.STUDYFORGE_MODELS_UI_CASE,root=path.dirname(caseFile),data=JSON.parse(fs.readFileSync(caseFile,'utf8'));
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win,manager;const errors=[];const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.on('window-all-closed',()=>{});
async function run(code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,180)+'\n'+error.message+'\n'+errors.join('\n'));}}
async function until(code){for(let n=0;n<120;n++){if(await run(code))return;await pause(100);}throw new Error('Timed out: '+code);}
async function open(url,width=1480,height=960){
  win=new BrowserWindow({show:true,x:-30000,y:-30000,width,height,webPreferences:{preload:path.resolve('desktop/preload.js'),contextIsolation:true,sandbox:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'){errors.push(event.message);console.error('Renderer: '+event.message);}});
  await win.loadURL(url);await until('Boolean(state.settings && state.project && state.deepseekCatalog)');
}
async function capture(name){await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');await pause(150);
  await win.webContents.capturePage();fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function viewportCheck(){
  const sizes=await run(`(() => {
    const rect=id=>{const r=$(id).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom};};
    return {width:innerWidth,height:innerHeight,horizontal:document.documentElement.scrollWidth-innerWidth,
      send:rect('sendMessage'),generate:rect('generate'),messages:rect('messages'),context:document.querySelector('.context-panel').getBoundingClientRect().width};
  })()`);
  assert.ok(sizes.horizontal<=1,JSON.stringify(sizes));
  for(const key of ['send','generate']){assert.ok(sizes[key].w>25&&sizes[key].x>=0&&sizes[key].right<=sizes.width&&sizes[key].bottom<=sizes.height,JSON.stringify(sizes));}
  assert.ok(sizes.messages.h>=110,JSON.stringify(sizes));return sizes;
}
app.whenReady().then(async()=>{
  ipcMain.handle('studyforge:desktop-status',()=>({tray_available:false}));
  await open(data.urls[0]);
  manager=createUpdateManager({currentVersion:'0.3.4',packaged:false,storageDirectory:path.join(root,'update-manager'),
    createUpdater:()=>{throw new Error('source must not connect');},requestQuit:()=>{throw new Error('source must not install');}});
  registerUpdateHandlers(ipcMain,new URL(data.urls[0]).origin,()=>win,manager,()=>true,()=>false);
  await run(String.raw`(async()=>{
    const category=await api('/api/projects/'+state.project.id+'/categories',jsonOptions('POST',{name:'概念与论证'}));
    for(const [name,text] of [['结构与证据.txt','结论需要证据。区分相关与因果，并检查解释的适用边界。'],['阅读方法.md','# 阅读的方法\n先理解术语，再重建论证；主动说明自己尚未理解的环节。']]){
      const body=new FormData();body.append('project_id',state.project.id);body.append('category_id',category.id);body.append('file',new File([text],name));
      const imported=await api('/api/import/file',{method:'POST',body});
      for(let n=0;n<80;n++){const job=await api('/api/jobs/'+imported.job_id);if(job.status==='completed')break;if(job.status==='failed')throw new Error(job.error);await new Promise(r=>setTimeout(r,100));}
    }
    await refreshSources();
    message('user','这份资料我能看懂结论，但不知道作者为什么这样构造论证。');
    message('assistant','# 从结论回到思路\n\n先区分“结论是什么”和“怎样得到结论”。我们可以逐步检查：\n\n1. 术语的含义与适用范围；\n2. 每一步依赖了什么前提；\n3. 是否存在更简单的反例。\n\n> 原文：学习时需要区分概念、论证与适用条件。\n\n## 如何想到这种方法\n把论证的目标与已有条件放在一起，找出缺少的桥梁，再选择能补上它的工具。\n\n一个数学排版示例：$E=mc^2$。\n\n你更想继续追问术语，还是独立重建这段论证？');
    $('prompt').value='请把证明的构造动机也讲清楚。';
  })()`);
  const normal=await viewportCheck();await capture('workbench-paper');
  await run(`document.querySelector('.advanced-generation').open=true`);
  assert.equal(await run(`(()=>{const r=document.querySelector('.advanced-grid').getBoundingClientRect();return r.y>=0&&r.right<=innerWidth&&getComputedStyle($('reviewMode')).display!=='none';})()`),true);
  await capture('generation-options');await run(`document.querySelector('.advanced-generation').open=false`);
  await run(`$('openAppearance').click()`);await until(`!$('settings-appearance').hidden`);await capture('appearance-settings');
  // Changes queue in order; reopen at another origin to check real disk persistence.
  await run(`Promise.all([saveStudioPreferences({ui_theme:'forest'}),saveStudioPreferences({ui_theme:'night',ui_text_size:'large',ui_density:'compact',ui_motion:'reduced',ui_send_key:'ctrl-enter'})])`);
  assert.equal(await run(`getComputedStyle(document.documentElement).colorScheme`),'dark');
  await run(`showView('study')`);await capture('workbench-night');
  const teaching=await run(`(()=>{const quote=document.querySelector('.lesson-quote'),content=document.querySelector('.lesson-explanation');return {quote:getComputedStyle(quote).color,text:getComputedStyle(content).color,quoteFont:getComputedStyle(quote).fontFamily,textFont:getComputedStyle(content).fontFamily,math:Boolean(document.querySelector('.katex')),motion:getComputedStyle($('view-study')).animationName};})()`);
  assert.notEqual(teaching.quote,teaching.text);assert.notEqual(teaching.quoteFont,teaching.textFont);assert.equal(teaching.math,true);assert.equal(teaching.motion,'none');
  await run(`$('toggleFocus').click()`);await until(`studioPending===0`);
  assert.equal(await run(`getComputedStyle(document.querySelector('.sidebar')).display`),'none');
  assert.equal(await run(`$('prompt').value`),'请把证明的构造动机也讲清楚。');await capture('focus-night');
  await run(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);await until(`studioPending===0`);
  assert.notEqual(await run(`getComputedStyle(document.querySelector('.context-panel')).display`),'none');
  const keyResult=await run(`(()=>{let calls=0;const original=$('sendMessage').onclick;$('sendMessage').onclick=()=>calls++;
    try{$('prompt').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}));
      $('prompt').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));const before=calls;
      $('prompt').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true,cancelable:true}));return {before,calls};
    }finally{$('sendMessage').onclick=original;}})()`);
  assert.deepEqual(keyResult,{before:0,calls:1});
  await run(`showView('settings');showSettingsSection('appearance');document.querySelector('[data-settings-section=appearance]').focus();document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}));`);
  await until(`!$('settings-system').hidden&&$('updateControls').hidden===false`);
  assert.equal(await run(`document.activeElement.dataset.settingsSection`),'system');assert.equal(await run(`$('checkUpdates').disabled`),false);await capture('runtime-settings');
  await run(`showView('study')`);
  win.setSize(1080,700);await pause(300);const small=await viewportCheck();await capture('workbench-small');
  win.setSize(1480,960);await pause(200);
  await run(`showView('study');$('generate').click()`);
  await until(`state.view==='artifacts'&&!state.busy&&Boolean($('artifacts').querySelector('.card'))`);
  await capture('artifacts-night');
  await run(`(async()=>{const items=await api('/api/projects/'+state.project.id+'/lesson-feedback');await openLessonFeedback(items[0].id);})()`);
  await until(`Boolean(document.querySelector('.lesson-questionnaire'))`);await capture('questionnaire-night');
  for(const view of ['sources','exercises','profile']){await run(`showView('${view}')`);await pause(200);await capture(view+'-night');}
  // Change the theme back for source acceptance, keeping only isolated data.
  await run(`saveStudioPreferences({ui_theme:'paper',ui_density:'comfortable',ui_text_size:'standard'})`);
  await run(`(async()=>{saveStudioPreferences({ui_theme:'forest'});await prepareDesktopExit();if(studioPending)throw new Error('exit did not await appearance');})()`);
  win.destroy();for(const channel of ['status','save','check','download','install','rollback','recovery','cancel','release','reveal'])ipcMain.removeHandler('studyforge:update-'+channel);
  await open(data.urls[1]);
  assert.equal(await run(`studioPreferences.ui_send_key`),'ctrl-enter');assert.equal(await run(`studioPreferences.ui_motion`),'reduced');
  assert.equal(await run(`studioPreferences.ui_theme`),'forest');
  const navigation=await run(`(()=>{document.dispatchEvent(new KeyboardEvent('keydown',{key:'2',ctrlKey:true,bubbles:true,cancelable:true}));const library=state.view;document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',ctrlKey:true,bubbles:true,cancelable:true}));return {library,view:state.view,input:document.activeElement.id};})()`);
  assert.deepEqual(navigation,{library:'sources',view:'study',input:'prompt'});
  assert.equal(errors.length,0,errors.join('\n'));
  fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({ok:true,normal,small,teaching,keyboard:keyResult,navigation,persistence_across_origins:true,models:'isolated mocks only'},null,2));
  console.log(JSON.stringify({ok:true,report:path.join(root,'result.json')}));manager.dispose();win.destroy();app.quit();
}).catch(error=>{console.error(error.stack);manager?.dispose();if(win&&!win.isDestroyed())win.destroy();app.exit(1);});
