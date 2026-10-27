// Actual Electron paint, worst-case contrast, UI controls and a full backend restart.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_SURFACES_CASE,root=path.dirname(casePath),input=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(root,'readability-profile'));app.disableHardwareAcceleration();
let win;const errors=[],checks=[],contrastResults=[],pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const regions=[['profile','.profile-evaluation','.profile-evaluation>p'],['profile','.profile-self-assessment','.profile-self-assessment>p'],
 ['profile','.profile-memory-controls','#profileCount'],['profile','.profile-pagination','#profilePage'],
 ['artifacts','.artifact-overview','.artifact-folder-heading .eyebrow'],['artifacts','.artifact-overview','#artifactFolderSummary'],
 ['artifacts','.artifact-overview','.job-history-toggle'],['sources','.library-tools','.library-tools>label'],
 ['artifacts','.artifact-folder-panel','#artifactFolderCount'],['artifacts','#artifacts .card','.artifact-name'],
 ['sources','.list-heading','#sourceCount'],['sources','#categoriesManager>.small-note','#categoriesManager>.small-note'],
 ['study','.model-toolbar','.model-toolbar>label'],['study','.empty-state','.empty-state p'],
 ['study','.workspace-heading','#viewLabel'],['study','.context-footer','.selected-label'],
 ['study','.composer','#agentPermissionHint'],['study','.reading-bar','#readingStatus'],
 ['study','.learning-mode-bar','#learningModeHint'],
 ['settings','.surface-settings-heading','.surface-settings-heading p'],['settings','.readability-settings','.readability-settings p']];
async function run(code){try{return await win.webContents.executeJavaScript(code);}catch(error){throw new Error(code.slice(0,220)+'\n'+error.message+'\n'+errors.join('\n'));}}
async function until(code){for(let i=0;i<120;i++){if(await run(code))return;await pause(100);}throw new Error('Timeout: '+code+'\n'+errors.join('\n'));}
async function settle(){await run('flushStudioDraft();studioSave');await until('studioPending===0');await pause(80);}
async function paint(){await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});await pause(100);return win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});}
async function capture(name){const shot=await paint();fs.writeFileSync(path.join(root,name+'.png'),shot.toPNG());return shot;}
function luminance(rgb){return rgb.map(value=>{const c=value/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((a,c,i)=>a+c*[.2126,.7152,.0722][i],0);}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
async function audit(panelSelector,textSelector,theme){
  const result=await run(`(()=>{const panel=document.querySelector(${JSON.stringify(panelSelector)}),text=document.querySelector(${JSON.stringify(textSelector)});if(!panel||!text)throw new Error('Missing ${panelSelector} / ${textSelector}');
    const s=getComputedStyle(panel),t=getComputedStyle(text),canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');
    const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return Array.from(ctx.getImageData(0,0,1,1).data);};
    return {fill:rgba(s.backgroundColor),ink:rgba(t.color),opacity:t.opacity,filter:t.filter,stroke:t.webkitTextStrokeWidth,text:text.textContent};})()`);
  assert.ok(result.fill[3]>=247,panelSelector+' needs a real protective fill '+JSON.stringify(result));
  assert.equal(result.opacity,'1',textSelector+' must not fade');assert.equal(result.filter,'none',textSelector+' must not blur');
  const alpha=result.fill[3]/255;
  const minimum=Math.min(...[[0,0,0],[255,255,255],[244,166,83],[104,111,108]].map(back=>contrast(result.ink.slice(0,3),result.fill.slice(0,3).map((c,i)=>c*alpha+back[i]*(1-alpha)))));
  assert.ok(minimum>=4.5,textSelector+' contrast '+minimum+' '+JSON.stringify(result));
  contrastResults.push({theme,panel:panelSelector,text:textSelector,minimum_contrast:Number(minimum.toFixed(2))});
}
async function chooseView(view){await run(`showView(${JSON.stringify(view)});if(${JSON.stringify(view)}==='settings'){showSettingsSection('appearance');showAppearanceTab('surfaces');}true`);await pause(130);}
async function selectMode(mode){await chooseView('settings');await run(`$('readabilityMode').value=${JSON.stringify(mode)};$('readabilityMode').dispatchEvent(new Event('change',{bubbles:true}));true`);await settle();}
async function cornerPixel(color){
  await run(`document.documentElement.style.setProperty('--background-paint','linear-gradient(${color},${color})');document.querySelector('.profile-evaluation').scrollIntoView({block:'center'});true`);
  const shot=await paint(),p=await run(`(()=>{const r=document.querySelector('.profile-evaluation').getBoundingClientRect();return {x:r.right-12,y:r.bottom-12,w:innerWidth,h:innerHeight};})()`);
  const {width,height}=shot.getSize(),buf=shot.toBitmap(),i=(Math.floor(p.y*height/p.h)*width+Math.floor(p.x*width/p.w))*4;return [...buf.subarray(i,i+3)];
}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1500,height:1080,webPreferences:{contextIsolation:true,sandbox:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error')errors.push(event.message);});
  await win.loadURL(input.url);await until('Boolean(state.ready&&state.project&&state.conversation&&state.settings)');
  let initial=await run(`api('/__surfaces_test__/state')`);
  if(input.phase===1){
    const imagePath=process.env.STUDYFORGE_READABILITY_IMAGE;
    if(imagePath){
      const bytes=fs.readFileSync(imagePath).toString('base64');
      await run(`uploadBackgroundFile(new File([Uint8Array.from(atob(${JSON.stringify(bytes)}),c=>c.charCodeAt(0))],'可读性背景.png',{type:'image/png'}))`);await settle();
      await until(`getComputedStyle(document.documentElement).getPropertyValue('--background-image').includes(studioPreferences.ui_background_asset)`);
      checks.push('通过真实上传入口安装复杂图片背景');
    }
    // Hidden capture windows do not reliably advance transition frames. Measure
    // settled pixels with the product's real reduced-motion option instead.
    await run(`saveStudioPreferences({ui_readability:'auto',ui_theme:'paper',ui_motion:'reduced',ui_background:${imagePath?"'image'":"'dusk'"},ui_background_transparency:0,ui_background_blur:0,ui_background_quiet_focus:false})`);await settle();
    await chooseView('profile');await until(`$('profileCount').textContent.includes('条')`);
    await run(`$('ratingTopic').value='高斯定律';$('ratingValue').value=65;$('saveRating').click();true`);
    await until(`Boolean($('profile').querySelector('.profile-card'))`);initial=await run(`api('/__surfaces_test__/state')`);
    regions.push(['profile','.profile-card','.profile-card>small']);
    await run(`document.querySelector('.profile-evaluation').scrollIntoView({block:'center'});true`);await capture('学习画像-信息底板');
    await chooseView('artifacts');await until(`Boolean($('artifacts').querySelector('.card'))`);await capture('成果文档-项目信息底板');
    await chooseView('sources');await until(`$('sourceCount').textContent.length>0`);await capture('资料库-分类与统计');
    for(const theme of ['paper','forest','night']){
      // An adversarial setup: all original fills transparent, with conflicting custom colors.
      await run(`surfacePreset('clear');saveStudioPreferences({ui_readability:'always',ui_theme:'${theme}',ui_outputs_text_color:'#ffffff',ui_toolbar_text_color:'#ffbb77',ui_controls_text_color:'#ffffff'});`);await settle();
      assert.equal(await run(`document.querySelector('[data-surface-preset=clear]').getAttribute('aria-pressed')`),'false');
      for(const view of ['profile','artifacts','sources','study','settings']){
        await chooseView(view);if(view==='profile')await until(`$('profileCount').textContent.includes('条')`);
        for(const [v,p,t] of regions.filter(row=>row[0]===view))await audit(p,t,theme);
      }
      checks.push(theme+' 在全透明与自定义颜色下的信息文字对比度');
    }
    await chooseView('profile');
    const a=await cornerPixel('#000000'),b=await cornerPixel('#ffffff');assert.ok(a.every((c,i)=>Math.abs(c-b[i])<=10),JSON.stringify({a,b}));
    await selectMode('off');await chooseView('profile');
    const c=await cornerPixel('#000000'),d=await cornerPixel('#ffffff');assert.ok(c.some((v,i)=>Math.abs(v-d[i])>100),JSON.stringify({c,d}));
    assert.equal(await run(`studioPreferences.ui_surface_opacity`),0);assert.equal(await run(`studioPreferences.ui_sidebar_opacity`),0);
    checks.push('开关改变真实像素，关闭后仍可完全透底，未改分区透明度');
    await selectMode('auto');await run(`saveStudioPreferences({ui_background:'none'})`);await settle();assert.equal(await run(`document.documentElement.dataset.readability`),'off');
    await selectMode('always');assert.equal(await run(`document.documentElement.dataset.readability`),'on');
    await selectMode('auto');await run(`saveStudioPreferences({ui_background:'dusk',ui_background_transparency:100})`);await settle();assert.equal(await run(`document.documentElement.dataset.readability`),'off');
    await run(`saveStudioPreferences({ui_background_transparency:0})`);await settle();assert.equal(await run(`document.documentElement.dataset.readability`),'on');
    checks.push('自动模式根据背景及隐藏状态启停，始终启用不依赖背景');
    await selectMode('off');await run(`$('resetSurfacePreferences').click();true`);await settle();
    assert.equal(await run(`studioPreferences.ui_readability`),'auto');assert.equal(await run(`document.documentElement.dataset.readability`),'on');
    checks.push('恢复界面默认同时恢复自动保护，透底预设状态与实际效果一致');
    await run(`surfacePreset('clear')`);await settle();assert.equal(await run(`document.documentElement.dataset.readability`),'off');checks.push('完全透底预设同时关闭信息底板');
    await run(`surfacePreset('soft');saveStudioPreferences({ui_readability:'always',ui_theme:'night',ui_background:${imagePath?"'image'":"'dusk'"},ui_background_transparency:0,ui_background_blur:0,ui_text_size:'large'})`);await settle();
    await chooseView('profile');await capture('学习画像-夜读主题');
    for(const view of ['profile','artifacts','sources','settings']){
      win.setSize(560,820);await pause(180);await chooseView(view);await capture('窄窗口-'+view);
      assert.equal(await run(`document.documentElement.scrollWidth<=innerWidth`),true,view+' narrow-window overflow');
    }
    checks.push('560px 窄窗口与大字模式无横向溢出');
    win.setSize(1500,1080);await chooseView('study');
    await run(`message('assistant',${JSON.stringify('## 先说明条件，再连接推理\n\n$\\nabla\\cdot\\mathbf E=\\rho/\\varepsilon_0$ 描述电场散度与电荷密度的关系。先解释每个量，再说明它为什么适合回答当前问题。\n\n> 原文：把条件与结论连接起来。\n\n~~~python\nprint("保持代码和公式各自的排版")\n~~~')});true`);
    await audit('.message.assistant .message-content','.message.assistant .message-content','night');
    await audit('#prompt','#prompt','night');
    const placeholder=await run(`getComputedStyle($('prompt'),'::placeholder').color`);assert.equal(placeholder,await run(`getComputedStyle($('agentPermissionHint')).color`));
    const danger=await run(`(()=>{const s=getComputedStyle(document.querySelector('[data-delete-artifact]'));return s.color;})()`);assert.notEqual(danger,await run(`getComputedStyle(document.querySelector('[data-rename-artifact]')).color`));
    for(const selector of ['.message .katex','.message code'])assert.equal(await run(`getComputedStyle(document.querySelector(${JSON.stringify(selector)})).webkitTextStrokeWidth`),'0px');
    await capture('学习工作台-导师正文与公式');checks.push('导师正文有独立底板，公式与代码保留原有排版');
    // Appearance edits do not change data; remove only this fixture's demo message
    // from the DOM (message() never writes it to the backend).
    await run(`$('messages').querySelector('.message.assistant').remove();true`);
    const current=await run(`api('/__surfaces_test__/state')`);assert.equal(current.model_calls,0);for(const key of ['sources','jobs','messages','learning_events'])assert.equal(current[key],initial[key]);
    fs.writeFileSync(path.join(root,'phase1.json'),JSON.stringify({checks,contrastResults,initial,config:await run(`api('/api/settings')`)},null,2));
  }else{
    const previous=JSON.parse(fs.readFileSync(path.join(root,'phase1.json'),'utf8'));
    for(const key of ['ui_readability','ui_theme','ui_background','ui_background_asset','ui_text_size','ui_surface_opacity','ui_sidebar_opacity'])assert.equal(await run(`studioPreferences.${key}`),previous.config[key],key);
    assert.equal(await run(`document.documentElement.dataset.readability`),'on');
    await chooseView('profile');await capture('实际重启-可读性设置恢复');
    await chooseView('settings');assert.equal(await run(`$('readabilityMode').value`),'always');
    await run(`(async()=>{const native=api;api=async(url,opt)=>{if(url==='/api/settings'&&opt?.method==='PUT')throw new Error('模拟保存失败');return native(url,opt);};try{await saveStudioPreferences({ui_readability:'off'});}finally{api=native;}})()`);
    assert.equal(await run(`document.documentElement.dataset.readability`),'on');assert.equal(await run(`$('readabilityMode').value`),'always');
    assert.equal(errors.length,0,errors.join('\n'));const current=await run(`api('/__surfaces_test__/state')`);assert.equal(current.model_calls,0);
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({success:true,actual_backend_restart:true,checks:[...previous.checks,'实际后台退出重开恢复设置','保存失败恢复已确认外观'],contrastResults:previous.contrastResults,errors,model_calls:current.model_calls},null,2));
  }
  await run(`prepareDesktopExit()`);win.destroy();app.quit();
}).catch(error=>{fs.writeFileSync(path.join(root,'readability-error.txt'),error.stack+'\n'+errors.join('\n'));console.error(error);app.exit(1);});
