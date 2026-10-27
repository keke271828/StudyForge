// Actual browser rendering, disk storage and backend restart; no AI inference.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_BACKGROUND_CASE,root=path.dirname(casePath),input=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,230)+'\n'+error.message+'\n'+errors.join('\n'));}}
async function until(code){for(let n=0;n<120;n++){if(await run(code))return;await pause(100);}throw new Error('Timeout: '+code);}
async function settle(){await run('flushStudioDraft();studioSave');await until('studioPending===0');await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});await pause(300);await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});}
async function capture(name){await pause(200);const shot=await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});fs.writeFileSync(path.join(root,name+'.png'),shot.toPNG());return shot;}
function corner(shot){const size=shot.getSize(),buffer=shot.toBitmap(),index=((size.height-9)*size.width+size.width-9)*4;return [...buffer.subarray(index,index+3)];}
async function dropImage(filename){const bytes=fs.readFileSync(path.join(root,filename)).toString('base64');
  await run(`(()=>{const bytes=Uint8Array.from(atob(${JSON.stringify(bytes)}),char=>char.charCodeAt(0));const transfer=new DataTransfer();transfer.items.add(new File([bytes],${JSON.stringify(filename)},{type:'image/png'}));$('backgroundImageDrop').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));})()`);
  await settle();await until(`getComputedStyle($('workspaceBackdrop')).backgroundImage.includes('/api/appearance/background/')`);
}
async function viewport(){return run(`(()=>{const r=$('sendMessage').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth-innerWidth,sendVisible:r.width>20&&r.right<=innerWidth&&r.bottom<=innerHeight,math:!!document.querySelector('#messages .katex')};})()`);}
async function sampleChat(){
  const lesson=String.raw`# 从目标出发，寻找缺少的桥梁

先列出已知条件与要证明的结论，再判断哪一种变形能把两者连接起来。

> 原文引用：先确定条件，再组织推理。

例如 $\sum_{i=1}^n a_i^2 \ge \frac{(\sum_{i=1}^n a_i)^2}{n}$，需要说明适用条件与等号何时成立。`;
  await run(`showView('study');message('user','我能看懂计算，想进一步理解构造动机。');message('assistant',${JSON.stringify(lesson)});`);
}

app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1480,height:960,webPreferences:{contextIsolation:true,sandbox:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error')errors.push(event.message);});
  await win.loadURL(input.url);await until('Boolean(state.ready&&state.settings&&state.project&&state.conversation)');
  if(input.phase===1){
    await run(`$('openAppearance').click();document.querySelector('[data-background-choice=mist]').click();`);await settle();
    assert.equal(await run(`getComputedStyle($('workspaceBackdrop')).backgroundImage.includes('gradient')`),true);
    await capture('背景设置-山岚');
    await dropImage('验收背景.png');
    const first=(await run('api("/api/settings")')).ui_background_asset;
    fs.unlinkSync(path.join(root,'验收背景.png'));
    await run(`$('backgroundTransparency').value=0;$('backgroundTransparency').dispatchEvent(new Event('input',{bubbles:true}));`);
    assert.equal(await run(`document.documentElement.style.getPropertyValue('--background-alpha')`),'1');
    await settle();await sampleChat();const visible=await capture('工作台-自定义背景');
    await run(`saveStudioPreferences({ui_background_transparency:100})`);await settle();const hidden=await capture('工作台-背景全透明');
    assert.notDeepEqual(corner(visible),corner(hidden),'background transparency must change actual rendered pixels');
    await run(`Promise.all([saveStudioPreferences({ui_background_blur:0}),saveStudioPreferences({ui_background_blur:19,ui_background_transparency:18,ui_background_x:20,ui_background_y:75,ui_surface_opacity:88})])`);await settle();
    assert.equal(await run(`getComputedStyle($('workspaceBackdrop')).filter`),'blur(19px)');
    assert.equal(await run(`getComputedStyle($('workspaceBackdrop')).backgroundPosition`),'20% 75%');
    const reading=await run(`({opacity:getComputedStyle($('messages')).opacity,textOpacity:getComputedStyle(document.querySelector('.lesson-explanation')).opacity,background:getComputedStyle($('messages')).backgroundColor})`);
    assert.equal(reading.opacity,'1');assert.equal(reading.textOpacity,'1');assert.ok(reading.background.includes('0.88'));
    await run(`$('toggleFocus').click()`);await settle();assert.equal(Number(await run(`getComputedStyle($('workspaceBackdrop')).opacity`)),.205,JSON.stringify(await run(`({prefs:studioPreferences,data:{...document.documentElement.dataset},supports:CSS.supports('opacity','calc(.82 * .25)'),matches:$('workspaceBackdrop').matches(':root[data-focus=true][data-quiet-background=true] .workspace-backdrop')})`)));
    await run(`saveStudioPreferences({ui_background_quiet_focus:false})`);await settle();assert.equal(Number(await run(`getComputedStyle($('workspaceBackdrop')).opacity`)),.82);
    await capture('专注模式-独立背景控制');
    await run(`saveStudioPreferences({ui_focus:false,ui_theme:'night',ui_surface_opacity:96,ui_background_quiet_focus:true})`);await settle();await capture('工作台-夜读背景');
    assert.deepEqual(await viewport(),{overflow:0,sendVisible:true,math:true});
    win.setSize(1080,820);await pause(220);assert.deepEqual(await viewport(),{overflow:0,sendVisible:true,math:true});await capture('工作台-较小窗口');
    win.setSize(1480,960);await pause(200);await run(`$('openAppearance').click()`);
    assert.equal(await run(`(()=>{const c=document.createElement('canvas'),ctx=c.getContext('2d');function rgb(el){ctx.fillStyle=getComputedStyle(el).backgroundColor;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].join(',');}return rgb(document.querySelector('[data-background-choice=mist]'))===rgb(document.querySelector('.background-settings-card'));})()`),true);
    await dropImage('第二张背景.png');const second=(await run('api("/api/settings")')).ui_background_asset;
    assert.notEqual(first,second);
    assert.equal(await run(`fetch('/api/appearance/background/${first}',{cache:'reload'}).then(result=>result.status)`),404);
    // A failed save must roll back both the visible control and confirmed disk settings.
    const failure=await run(`(async()=>{const original=api;api=async(url,options)=>{if(url==='/api/settings'&&options?.method==='PUT')throw new Error('模拟保存失败');return original(url,options);};try{await saveStudioPreferences({ui_background:'dusk'});return studioPreferences.ui_background;}finally{api=original;}})()`);
    assert.equal(failure,'image');
    // Switch scheme and immediately adjust a slider: queued asset changes must not be overwritten.
    await run(`(async()=>{document.querySelector('[data-background-choice=aurora]').click();$('backgroundBlur').value=11;$('backgroundBlur').dispatchEvent(new Event('input',{bubbles:true}));await prepareDesktopExit();})()`);
    const config=await run('api("/api/settings")');assert.equal(config.ui_background,'aurora');assert.equal(config.ui_background_blur,11);
    await run(`(async()=>{document.querySelector('[data-background-choice=image]').click();await prepareDesktopExit();})()`);
    await capture('背景设置-本地图片与预览');
    const counters=await run(`api('/__background_test__/state')`);
    assert.equal(counters.model_calls,0);assert.equal(counters.sources,0);assert.equal(counters.jobs,0);assert.equal(counters.learning_events,0);assert.equal(counters.messages,0);
    fs.writeFileSync(path.join(root,'phase1.json'),JSON.stringify({config:await run('api("/api/settings")'),pixelsChanged:true,reading,counters},null,2));
  }else{
    const previous=JSON.parse(fs.readFileSync(path.join(root,'phase1.json'),'utf8'));
    await until(`getComputedStyle($('workspaceBackdrop')).backgroundImage.includes('/api/appearance/background/')`);
    const restored=await run('api("/api/settings")');
    for(const key of Object.keys(previous.config).filter(key=>key.startsWith('ui_')))assert.equal(restored[key],previous.config[key],key);
    assert.equal(restored.ui_background_name,'第二张背景.png');assert.equal(fs.existsSync(path.join(root,'验收背景.png')),false);
    await sampleChat();await capture('实际重启-图片与样式恢复');
    await run(`(async()=>{showView('settings');showSettingsSection('appearance');await refreshSettings();
      const stale=await api('/api/settings'),original=api;let release;const gate=new Promise(resolve=>release=resolve);
      api=async(url,options)=>{if(url==='/api/settings'&&!options)return stale;if(url==='/api/health'){await gate;}return original(url,options);};
      try{const refresh=refreshSettings();$('removeBackgroundImage').click();await studioSave;release();await refresh;}
      finally{release();api=original;}})()`);await settle();
    assert.equal(await run('studioPreferences.ui_background'),'none');assert.equal(await run('studioPreferences.ui_background_asset'),'');
    assert.equal(await run('state.settings.ui_background'),'none');
    await run(`(async()=>{saveStudioPreferences({ui_background:'dusk',ui_background_transparency:72,ui_background_blur:22});$('resetBackground').click();await prepareDesktopExit();})()`);
    const reset=await run('api("/api/settings")');assert.equal(reset.ui_background,'none');assert.equal(reset.ui_background_blur,8);assert.equal(reset.ui_theme,'night');
    win.setSize(560,720);await pause(200);await run(`$('backgroundImageDrop').scrollIntoView({block:'center'})`);await capture('背景设置-窄窗口');
    assert.ok(await run(`document.documentElement.scrollWidth<=innerWidth`));
    assert.equal(errors.length,0,errors.join('\n'));
    const counters=await run(`api('/__background_test__/state')`);assert.equal(counters.model_calls,0);
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({success:true,actual_backend_restart:true,presets_visible:true,
      local_image_copy:true,original_image_deleted_copy_still_works:true,transparency_changes_pixels:true,blur_and_position_applied:true,
      reading_mask_independent:true,text_opacity_preserved:true,focus_dimming_toggle:true,queued_save_and_failure_rollback:true,
      preferences_persisted:true,remove_and_reset:true,stale_settings_refresh_discarded:true,narrow_window:true,controls_follow_dark_theme:true,model_calls:0,learning_events:0},null,2));
  }
  win.destroy();app.quit();
}).catch(error=>{console.error(error.stack);if(win&&!win.isDestroyed())win.destroy();app.exit(1);});
