// Real desktop paint, local font load, persistence and backend restart. Zero inference.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_SURFACES_CASE,root=path.dirname(casePath),input=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,250)+'\n'+error.message+'\n'+errors.join('\n'));}}
async function until(code){for(let i=0;i<120;i++){if(await run(code))return;await pause(100);}throw new Error('Timeout: '+code+'\n'+errors.join('\n'));}
async function settle(){await run('flushStudioDraft();studioSave');await until('studioPending===0');await paint();}
async function paint(){await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});await pause(120);return win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});}
async function capture(name){await pause(330);const shot=await paint();fs.writeFileSync(path.join(root,name+'.png'),shot.toPNG());return shot;}
function pixel(shot,point){const {width,height}=shot.getSize(),buffer=shot.toBitmap(),i=(Math.floor(point.y*height/point.height)*width+Math.floor(point.x*width/point.width))*4;return [...buffer.subarray(i,i+3)];}
function variance(shot,point){const {width,height}=shot.getSize(),buffer=shot.toBitmap();const values=[];for(let y=0;y<16;y++)for(let x=0;x<16;x++){const i=(Math.floor((point.y+y)*height/point.height)*width+Math.floor((point.x+x)*width/point.width))*4;values.push((buffer[i]+buffer[i+1]+buffer[i+2])/3);}const mean=values.reduce((a,b)=>a+b,0)/values.length;return values.reduce((a,b)=>a+(b-mean)**2,0)/values.length;}
async function point(selector,alignment='bottom'){return run(`(()=>{const element=document.querySelector(${JSON.stringify(selector)}),r=element.getBoundingClientRect();let y=${alignment==='center'?'r.top+r.height/2':alignment==='top'?'r.top+8':'r.bottom-24'};const parent=element.closest('.messages');if(parent)y=Math.max(y,parent.getBoundingClientRect().top+12);return {x:r.right-24,y,width:innerWidth,height:innerHeight};})()`);}
async function wallpaper(color){await run(`document.documentElement.style.setProperty('--background-paint',${JSON.stringify(`linear-gradient(${color},${color})`)});true`);return paint();}
async function sample(){await run(`showView('study');message('user','我能看懂计算，希望进一步理解构造动机。');message('assistant',${JSON.stringify(String.raw`## 条件、思路与结论

把已知与目标放在一起：为什么想到这一步？哪些条件允许这样做？

> 原文：先理解条件，再组织论证。

例如 $\sum a_i^2\geq (\sum a_i)^2/n$，先说明适用条件，再解释等号。

~~~python
def explain(idea):
    return idea
~~~`)});`);}
async function endpoint(id,selector,view='study',alignment='bottom'){
  await run(`showView(${JSON.stringify(view)});if(${JSON.stringify(view)}==='settings'){showSettingsSection('appearance');showAppearanceTab('background');}true`);
  await until(`Boolean(document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect().width)`);
  // Long samples may scroll their first lines out of the reading viewport.
  // Inspect the region's own top padding, rather than a clipped quote/code child.
  if(id==='messages')await run(`document.querySelector('.message.assistant').scrollIntoView({block:'start'});true`);
  const p=await point(selector,alignment);
  assert.ok(p.x>0&&p.y>0&&p.y<win.getSize()[1],id+' test area visible');
  const results={};
  for(const opacity of [0,100]){
    await run(`saveStudioPreferences({ui_${id}_opacity:${opacity},ui_${id}_blur:0})`);await settle();
    const computed=await run(`(()=>{const s=getComputedStyle(document.querySelector(${JSON.stringify(selector)}));return {fill:s.backgroundColor,opacity:s.opacity,blur:s.backdropFilter};})()`);
    const a=pixel(await wallpaper('#135bde'),p),b=pixel(await wallpaper('#f3ab27'),p);
    if(opacity===0)assert.notDeepEqual(a,b,id+' at 0% must reveal the changing wallpaper '+JSON.stringify({p,computed}));
    else assert.deepEqual(a,b,id+' at 100% must hide the changing wallpaper '+JSON.stringify({p,computed}));
    assert.equal(computed.opacity,'1',id+' foreground opacity');
    results[opacity]={...computed,a,b};
  }
  await run(`saveStudioPreferences({ui_${id}_opacity:0})`);await settle();
  return results;
}

app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1540,height:1050,webPreferences:{contextIsolation:true,sandbox:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error')errors.push(event.message);});
  await win.loadURL(input.url);await until('Boolean(state.ready&&state.project&&state.conversation&&state.settings)');
  const initialCounters=await run(`api('/__surfaces_test__/state')`);
  if(input.phase===1){
    await run(`surfacePreset('clear');saveStudioPreferences({ui_motion:'reduced'});`);await settle();
    await run(`saveStudioPreferences({ui_background:'dusk',ui_background_transparency:0,ui_background_blur:0,ui_background_quiet_focus:false})`);await settle();await sample();
    assert.equal(await run(`$('surfaceOpacity').min`),'0');
    const endpoints={};
    for(const [id,selector,view,alignment] of [
      ['canvas','.main','study','bottom'],['sidebar','.sidebar','study','center'],['surface','#messages','study','bottom'],
      ['context','.context-panel','study','center'],['composer','.composer','study','center'],['topbar','.topbar','study','bottom'],
      ['toolbar','.reading-bar','study','center'],['messages','.message.assistant','study','top'],
      ['controls','#studyModel','study','center'],['settings','.background-settings-card','settings','center'],
      ['outputs','#artifacts .card','artifacts','bottom']])endpoints[id]=await endpoint(id,selector,view,alignment);
    await run(`showView('study');document.querySelector('.app-shell').style.visibility='hidden';const d=document.createElement('dialog');d.id='testSurfaceDialog';d.style.cssText='width:380px;height:240px';d.textContent='独立弹窗预览';document.body.append(d);d.showModal();true`);
    endpoints.dialogs=await endpoint('dialogs','#testSurfaceDialog','study','center');
    await run(`$('testSurfaceDialog').close();$('testSurfaceDialog').remove();document.querySelector('.app-shell').style.visibility='';true`);
    await run(`surfacePreset('clear')`);await settle();
    await run(`document.documentElement.style.setProperty('--background-paint','repeating-linear-gradient(90deg,#132337 0px,#132337 14px,#b9d5ef 14px,#b9d5ef 28px)');true`);
    const readPoint=await point('#messages'),sidePoint=await point('.sidebar','center');readPoint.x-=26;readPoint.y+=6;
    const sharp=await paint();const before={reading:variance(sharp,readPoint),sidebar:variance(sharp,sidePoint)};
    await run(`saveStudioPreferences({ui_surface_blur:18})`);await settle();
    await run(`document.documentElement.style.setProperty('--background-paint','repeating-linear-gradient(90deg,#132337 0px,#132337 14px,#b9d5ef 14px,#b9d5ef 28px)');true`);
    const blurred=await capture('局部模糊-仅阅读面板');const after={reading:variance(blurred,readPoint),sidebar:variance(blurred,sidePoint)};
    assert.ok(before.reading>100&&after.reading<before.reading*.2,JSON.stringify({before,after}));
    assert.equal(before.sidebar,after.sidebar,'reading blur must not blur the sidebar');
    assert.equal(await run(`getComputedStyle(document.querySelector('.message-content')).filter`),'none');
    assert.equal(await run(`getComputedStyle(document.querySelector('.message-content')).opacity`),'1');
    await run(`saveStudioPreferences({ui_messages_text_color:'#fafafa',ui_messages_stroke_width:.75,ui_messages_stroke_color:'auto'})`);await settle();
    assert.equal(await run(`getComputedStyle(document.querySelector('.message-content')).webkitTextStrokeWidth`),'0.75px');
    for(const selector of ['.message code','.message .katex','.studio-nav svg'])assert.equal(await run(`getComputedStyle(document.querySelector(${JSON.stringify(selector)})).webkitTextStrokeWidth`),'0px');
    await run(`$('openAppearance').click();showAppearanceTab('surfaces');document.querySelector('[data-surface-preset=glass]').click();`);await settle();
    assert.equal(await run(`studioPreferences.ui_theme`),'night');
    assert.equal(await run(`document.querySelector('[data-surface-preset=glass]').getAttribute('aria-pressed')`),'true');
    assert.equal(await run(`getComputedStyle(document.querySelector('.sidebar')).backdropFilter`),'blur(12px)');
    await capture('外观-分区设置与实时预览');
    await run(`$('surfaceJump').value='composer';$('surfaceJump').dispatchEvent(new Event('change',{bubbles:true}));true`);await pause(500);
    assert.equal(await run(`document.activeElement.id`),'composerOpacity');await capture('外观-输入栏与顶部栏');
    await run(`showView('study')`);await capture('工作台-玻璃夜读');
    await run(`showView('settings');showSettingsSection('appearance');showAppearanceTab('surfaces');
      $('surfaceOpacity').value=0;$('surfaceOpacity').dispatchEvent(new Event('input',{bubbles:true}));
      $('sidebarOpacity').value=13;$('sidebarOpacity').dispatchEvent(new Event('input',{bubbles:true}));
      $('contextBlur').value=23;$('contextBlur').dispatchEvent(new Event('input',{bubbles:true}));`);await settle();
    let config=await run(`api('/api/settings')`);assert.equal(config.ui_surface_opacity,0);assert.equal(config.ui_sidebar_opacity,13);assert.equal(config.ui_context_blur,23);
    await run(`document.querySelector('[data-reset-surface=sidebar]').click();true`);await settle();
    assert.equal(await run(`studioPreferences.ui_sidebar_opacity`),95);assert.equal(await run(`studioPreferences.ui_surface_opacity`),0);
    await run(`document.querySelector('[data-copy-surface=context]').click();true`);await settle();
    config=await run(`api('/api/settings')`);for(const region of Object.keys(endpoints))assert.equal(config['ui_'+region+'_blur'],23);
    await run(`$('resetSurfacePreferences').click();true`);await settle();
    assert.equal(await run(`studioPreferences.ui_background`),'dusk');
    // Force a stale refresh and a save failure while editing two independent regions.
    await run(`(async()=>{const old=await api('/api/settings'),native=api;api=async(url,opt)=>url==='/api/settings'&&!opt?old:native(url,opt);
      try{$('sidebarOpacity').value=14;$('sidebarOpacity').dispatchEvent(new Event('input',{bubbles:true}));await refreshSettings();await prepareDesktopExit();}
      finally{api=native;}})()`);assert.equal(await run(`studioPreferences.ui_sidebar_opacity`),14);
    await run(`(async()=>{const native=api;api=async(url,opt)=>{if(url==='/api/settings'&&opt?.method==='PUT')throw new Error('模拟保存失败');return native(url,opt);};
      try{await saveStudioPreferences({ui_sidebar_opacity:71});}finally{api=native;}})()`);
    assert.equal(await run(`studioPreferences.ui_sidebar_opacity`),14);
    const bytes=fs.readFileSync(path.join(root,'验收字体.ttf')).toString('base64');
    await run(`showAppearanceTab('typography');const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(${JSON.stringify(bytes)}),char=>char.charCodeAt(0))],'验收字体.ttf'));
      $('appearanceFontFile').files=transfer.files;$('appearanceFontFile').dispatchEvent(new Event('change',{bubbles:true}));true`);await settle();await run('surfaceFontReady');
    assert.equal(await run(`document.fonts.check('14px StudyForgeUserFont','Explain A')`),true);
    assert.equal(await run(`surfaceFontFace.status`),'loaded');
    assert.ok((await run(`getComputedStyle(document.querySelector('.appearance-font-sample')).fontFamily`)).includes('StudyForgeUserFont'));
    await capture('外观-自定义字体');
    await run(`surfacePreset('soft');saveStudioPreferences({ui_surface_opacity:0,ui_surface_blur:9,ui_sidebar_opacity:31,ui_context_opacity:42,ui_composer_opacity:25,ui_topbar_opacity:18,ui_outputs_opacity:38,ui_settings_opacity:88,ui_messages_stroke_width:.25});`);await settle();
    await run(`showAppearanceTab('surfaces');true`);await capture('外观-轻透留白');
    win.setSize(570,800);await pause(180);await run(`document.querySelector('[data-region-card=surface]').scrollIntoView({block:'center'});true`);await capture('外观-窄窗口');
    assert.equal(await run(`document.documentElement.scrollWidth<=innerWidth`),true);
    const counters=await run(`api('/__surfaces_test__/state')`);assert.equal(counters.model_calls,0);for(const key of ['learning_events','sources','jobs','messages'])assert.equal(counters[key],initialCounters[key],key+' must not change for appearance edits');
    fs.writeFileSync(path.join(root,'phase1.json'),JSON.stringify({config:await run(`api('/api/settings')`),endpoints,localBlur:{before,after},counters},null,2));
  }else{
    const previous=JSON.parse(fs.readFileSync(path.join(root,'phase1.json'),'utf8'));
    const restored=await run(`api('/api/settings')`);
    for(const key of Object.keys(previous.config).filter(key=>key.startsWith('ui_')))assert.equal(restored[key],previous.config[key],key);
    await run('surfaceFontReady');assert.equal(await run(`surfaceFontFace.status`),'loaded');
    assert.equal(await run(`getComputedStyle($('messages')).backdropFilter`),'blur(9px)');
    await sample();await capture('实际重启-分区与字体恢复');
    await run(`$('openAppearance').click();showAppearanceTab('typography');$('removeAppearanceFont').click();true`);await settle();
    assert.equal(await run(`studioPreferences.ui_font_family`),'system');assert.equal(await run(`surfaceFontFace===null`),true);
    assert.ok(fs.existsSync(path.join(root,'验收字体.ttf')),'original font remains');
    const removedFont=await fetch(input.url+'/api/appearance/font/'+restored.ui_font_asset);assert.equal(removedFont.status,404);
    const counters=await run(`api('/__surfaces_test__/state')`);assert.equal(counters.model_calls,0);assert.equal(counters.learning_events,0);
    assert.equal(errors.length,0,errors.join('\n'));
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({success:true,regions:12,actual_backend_restart:true,
      opacity_zero_reveals_background_each_region:true,opacity_full_hides_background_each_region:true,local_blur_changes_rendered_pixels:true,
      other_region_blur_unchanged:true,text_not_faded_or_blurred:true,code_math_icons_no_outline:true,presets_apply_true_styles:true,
      individual_reset_and_copy_all:true,background_reset_independent:true,stale_refresh_ignored:true,save_failure_rolls_back:true,
      sliders_merge_without_lost_changes:true,custom_font_loaded_and_persisted:true,font_delete_preserves_original:true,narrow_window:true,
      model_calls:counters.model_calls,learning_events:counters.learning_events},null,2));
  }
  win.destroy();app.quit();
}).catch(async error=>{console.error(error.stack);if(win&&!win.isDestroyed()){try{await capture('失败现场');}catch(_){}win.destroy();}app.exit(1);});
