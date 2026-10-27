/* Each surface owns its fill and backdrop, never element opacity or foreground blur. */
const surfaceRegions=[
  {id:'canvas',name:'主界面底色',opacity:0,selector:'.main',base:'canvas',hint:'背景图片上方的底色层'},
  {id:'sidebar',name:'侧边栏',opacity:95,selector:'.sidebar',base:'sidebar',hint:'项目、对话与工作区导航'},
  {id:'surface',name:'阅读面板',opacity:96,selector:'.messages,.background-preview-panel,.surface-demo-reading',base:'surface',hint:'聊天正文所在的阅读区域'},
  {id:'context',name:'资料快选栏',opacity:96,selector:'.context-panel,.surface-demo-context',base:'surface',hint:'资料选择与分类区域'},
  {id:'composer',name:'输入栏',opacity:100,selector:'.composer,.surface-demo-composer',base:'surface',hint:'问题输入与成果生成选项'},
  {id:'topbar',name:'顶部栏',opacity:96,selector:'.topbar,.surface-demo-topbar',base:'surface',hint:'项目标题、专注与外观入口'},
  {id:'toolbar',name:'对话选项栏',opacity:100,selector:'.conversation-panel>.section-head,.learning-mode-bar,.conversation-heading,.reading-bar,.page-heading,.surface-demo-toolbar',base:'surface',hint:'模型、模式、通读状态与页面标题'},
  {id:'controls',name:'按钮与表单控件',opacity:100,selector:'input:not([type=range]):not([type=checkbox]):not([type=file]):not([type=color]),select,textarea:not(#prompt),.composer-actions button,.generation-bar button,.generation-bar summary,.quick-actions button,.quick-group-head button,.context-footer button,.model-toolbar button,.reading-bar button,.card-actions button,.workspace-actions button,.dialog-actions button,.surface-demo-control',base:'surface-alt',hint:'分别调整按钮和输入框的底色，不会让文字一起变透明'},
  {id:'messages',name:'消息气泡',opacity:0,selector:'.message,.surface-demo-message',base:'surface-alt',hint:'导师与用户消息的局部底色'},
  {id:'settings',name:'设置区域',opacity:100,selector:'.settings-card,.settings-nav,.appearance-tabs,.surface-demo-settings',base:'surface',hint:'各组设置、外观卡片与设置导航'},
  {id:'dialogs',name:'弹窗与菜单',opacity:100,selector:'dialog,.navigation-context,.advanced-grid',base:'surface',hint:'阅读笔记、知识结构、确认窗口及菜单'},
  {id:'outputs',name:'成果与资料卡片',opacity:100,selector:'.card,.job-card,.profile-card,.memory-card,.artifact-folder-panel,.library-group,.exercise-panel,.lesson-questionnaire,.upload-card,.url-card,.surface-demo-output',base:'surface',hint:'成果、任务、资料、练习与画像卡片'},
];
const surfaceFields={opacity:0,blur:0,text_color:'theme',stroke_width:0,stroke_color:'auto'};
const surfaceDefaults=Object.fromEntries(surfaceRegions.flatMap(region=>Object.entries({...surfaceFields,opacity:region.opacity}).map(([field,value])=>[`ui_${region.id}_${field}`,value])));
const fontDefaults={ui_font_family:'system',ui_font_asset:'',ui_font_name:''};
const readabilityDefaults={ui_readability:'auto'};
const surfaceFontStacks={system:'"Segoe UI","Microsoft YaHei",sans-serif',sans:'"Microsoft YaHei","Segoe UI",sans-serif',serif:'SimSun,"Songti SC",serif',kai:'KaiTi,"STKaiti",serif',custom:'"StudyForgeUserFont","Microsoft YaHei","Segoe UI",sans-serif'};
const surfacePresetValues={paper:[0,100,100,100,100,100,100,100,0,100,100,100],glass:[0,30,22,26,32,18,22,44,0,86,82,30],soft:[0,60,58,58,68,45,55,78,0,96,92,65],clear:Array(12).fill(0)};
let appearanceTab='background',surfaceFontAsset='',surfaceFontToken=0,surfaceFontFace=null,surfaceFontReady=Promise.resolve();
function surfaceKey(id,field){return `ui_${id}_${field}`;}
function surfaceOpacityId(id){return id==='surface'?'surfaceOpacity':`${id}Opacity`;}
function showAppearanceTab(tab){
  if(appearanceTab!==tab)document.getElementById('view-settings').scrollTop=0;
  appearanceTab=tab;
  document.querySelectorAll('[data-appearance-panel]').forEach(node=>{node.hidden=node.dataset.appearancePanel!==tab;});
  document.querySelectorAll('[data-appearance-tab]').forEach(button=>{const active=button.dataset.appearanceTab===tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
}
function surfaceContrast(color){
  const rgb=color.match(/\d+/g)?.slice(0,3).map(Number)||[36,56,47];
  return (rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722)>140?'#101820':'#ffffff';
}
function surfaceColorValue(color,themeColor){
  if(/^#[0-9a-f]{6}$/i.test(color))return color;
  if(/^#[0-9a-f]{6}$/i.test(themeColor))return themeColor;
  const values=themeColor.match(/\d+/g)?.slice(0,3).map(Number);
  return values?'#'+values.map(value=>value.toString(16).padStart(2,'0')).join(''):'#24382f';
}
function applySurfacePreferences(next){
  const root=document.documentElement,theme=getComputedStyle(root),themeInk=theme.getPropertyValue('--ink').trim();
  const readability=next.ui_readability||'auto';
  root.dataset.readability=readability==='always'||(readability==='auto'&&next.ui_background!=='none'&&next.ui_background_transparency<100)?'on':'off';
  const readabilitySelect=document.getElementById('readabilityMode');if(readabilitySelect)readabilitySelect.value=readability;
  const readabilityStatus=document.getElementById('readabilityStatus');if(readabilityStatus)readabilityStatus.textContent=root.dataset.readability==='on'?'已启用 · 文字与文字背后的底色使用 97% 不透明度和主题配色':'未启用 · 使用原来的各区域外观';
  for(const region of surfaceRegions){
    const id=region.id,value=field=>next[surfaceKey(id,field)]??surfaceDefaults[surfaceKey(id,field)];
    root.style.setProperty(`--${id}-opacity`,value('opacity')+'%');
    root.style.setProperty(`--${id}-filter`,value('blur')?`blur(${value('blur')}px)`:'none');
    root.style.setProperty(`--${id}-text`,value('text_color')==='theme'?'initial':value('text_color'));
    root.style.setProperty(`--${id}-muted`,value('text_color')==='theme'?'initial':value('text_color'));
    root.style.setProperty(`--${id}-stroke-width`,value('stroke_width')+'px');
    const ink=value('text_color')==='theme'?themeInk:value('text_color');
    const autoColor=/^#[0-9a-f]{6}$/i.test(ink)?surfaceContrast(`rgb(${parseInt(ink.slice(1,3),16)},${parseInt(ink.slice(3,5),16)},${parseInt(ink.slice(5),16)})`):surfaceContrast(ink);
    root.style.setProperty(`--${id}-stroke-color`,value('stroke_color')==='auto'?autoColor:value('stroke_color')==='theme'?'var(--accent)':value('stroke_color'));
    const opacity=document.getElementById(surfaceOpacityId(id)),blur=document.getElementById(id+'Blur');
    if(opacity)opacity.value=value('opacity');if(blur)blur.value=value('blur');
    for(const [field,inputId,suffix] of [['opacity',surfaceOpacityId(id),'%'],['blur',id+'Blur',' px'],['stroke_width',id+'StrokeWidth',' px']]){
      const input=document.getElementById(inputId),output=document.getElementById(inputId+'Value');if(input)input.value=value(field);if(output)output.value=value(field)+suffix;
    }
    const badge=document.getElementById(id+'SurfaceBadge');if(badge)badge.textContent=value('opacity')+'%';
    for(const field of ['text_color','stroke_color']){
      document.querySelectorAll(`[data-surface-color="${id}:${field}"]`).forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.color===value(field))));
      const input=document.querySelector(`[data-surface-color-input="${id}:${field}"]`);
      if(input)input.value=surfaceColorValue(value(field),themeInk);
    }
  }
  for(const button of document.querySelectorAll('[data-surface-preset]')){
    const name=button.dataset.surfacePreset,values=surfacePresetValues[name];
    const active=surfaceRegions.every((region,index)=>Object.keys(surfaceFields).every(field=>{
      const desired=field==='opacity'?values[index]:field==='blur'?(['glass','soft'].includes(name)&&!['canvas','messages'].includes(region.id)?12:0):surfaceFields[field];
      return next[surfaceKey(region.id,field)]===desired;
    }))&&(name!=='clear'||next.ui_readability==='off')&&(name==='clear'||next.ui_theme===(name==='glass'?'night':'paper'));
    button.setAttribute('aria-pressed',String(active));
  }
  const mode=next.ui_font_family||'system';root.style.setProperty('--ui-font-stack',surfaceFontStacks[mode]||surfaceFontStacks.system);root.dataset.fontFamily=mode;
  const fontSelect=document.getElementById('appearanceFontFamily');if(fontSelect)fontSelect.value=mode;
  const fontName=document.getElementById('appearanceFontName');if(fontName)fontName.textContent=next.ui_font_name||'未上传自定义字体';
  const fontRemove=document.getElementById('removeAppearanceFont');if(fontRemove)fontRemove.disabled=!next.ui_font_asset;
  const customOption=fontSelect?.querySelector('[value=custom]');if(customOption)customOption.disabled=!next.ui_font_asset;
  if(surfaceFontAsset!==next.ui_font_asset){
    surfaceFontAsset=next.ui_font_asset;const token=++surfaceFontToken;
    if(surfaceFontFace){document.fonts.delete(surfaceFontFace);surfaceFontFace=null;}
    if(/^[a-f0-9]{64}$/.test(surfaceFontAsset)){
      const face=new FontFace('StudyForgeUserFont',`url("/api/appearance/font/${surfaceFontAsset}")`);
      surfaceFontReady=face.load().then(loaded=>{if(token!==surfaceFontToken)return;surfaceFontFace=loaded;document.fonts.add(loaded);const status=document.getElementById('appearanceFontNotice');if(status)status.textContent='字体已加载，保存在本机；原文件不改动';}).catch(()=>{if(token!==surfaceFontToken)return;const status=document.getElementById('appearanceFontNotice');if(status)status.textContent='自定义字体暂不可用，已使用系统字体显示；可重新上传或选择其他字体';});
    }else{
      surfaceFontReady=Promise.resolve();const status=document.getElementById('appearanceFontNotice');
      if(status)status.textContent='TTF / OTF / WOFF / WOFF2 · 最大 50 MB · 单独保存在本机';
    }
  }
}
function surfacePreset(name){
  const delta={};
  const values=surfacePresetValues[name];
  if(!values)return;
  surfaceRegions.forEach((region,index)=>{
    for(const [field,value] of Object.entries(surfaceFields))delta[surfaceKey(region.id,field)]=value;
    delta[surfaceKey(region.id,'opacity')]=values[index];
    delta[surfaceKey(region.id,'blur')]=['glass','soft'].includes(name)&&!['canvas','messages'].includes(region.id)?12:0;
  });
  if(name==='glass'||name==='soft')Object.assign(delta,{ui_theme:name==='glass'?'night':'paper',ui_background_blur:0,ui_background_transparency:0,ui_background_quiet_focus:false,
    ui_background:studioPreferences.ui_background==='none'?(name==='glass'?'dusk':'aurora'):studioPreferences.ui_background});
  if(name==='paper')delta.ui_theme='paper';
  if(name==='clear')delta.ui_readability='off';
  return saveStudioPreferences(delta);
}
function surfaceColorControls(region,field){
  const id=region.id,choices=field==='text_color'?[['theme','主题'],['#101820','黑'],['#ffffff','白']]:[['auto','自动'],['theme','主题'],['#101820','黑'],['#ffffff','白']];
  return `<div class="surface-color-row">${choices.map(([color,label])=>`<button type="button" data-surface-color="${id}:${field}" data-color="${color}" aria-pressed="false">${label}</button>`).join('')}<label class="surface-custom-color" title="自定义颜色"><input type="color" data-surface-color-input="${id}:${field}" aria-label="${region.name}${field==='text_color'?'文字':'描边'}自定义颜色"><span>自选</span></label></div>`;
}
function initializeSurfaces(){
  const section=document.getElementById('settings-appearance'),tabs=document.createElement('nav');tabs.className='appearance-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','外观设置');
  tabs.innerHTML=[['background','背景'],['surfaces','各区域外观'],['typography','字体与文字'],['basics','基本设置']].map(([id,name])=>`<button type="button" role="tab" id="appearance-tab-${id}" data-appearance-tab="${id}" aria-controls="appearance-panel-${id}">${name}</button>`).join('');section.prepend(tabs);
  const background=section.querySelector('.background-settings-card');background.dataset.appearancePanel='background';background.id='appearance-panel-background';
  const basics=section.querySelector('.appearance-card');basics.dataset.appearancePanel='basics';basics.id='appearance-panel-basics';
  const surfaces=document.createElement('div');surfaces.className='appearance-panel';surfaces.id='appearance-panel-surfaces';surfaces.dataset.appearancePanel='surfaces';
  surfaces.innerHTML=`<div class="surface-settings-heading"><div><span class="eyebrow">SURFACES</span><h3>每个区域，都由你决定</h3><p>不透明度 0% 为完全透底，100% 为实色。模糊只处理后面的画面，不模糊文字。</p></div><button id="resetSurfacePreferences" type="button">恢复界面默认</button></div><div class="surface-preset-bar" role="group" aria-label="界面外观预设"><button type="button" data-surface-preset="paper">纸面专注</button><button type="button" data-surface-preset="glass">玻璃夜读</button><button type="button" data-surface-preset="soft">轻透留白</button><button type="button" data-surface-preset="clear">完全透底</button></div><div class="surface-layout"><div class="surface-config-grid">${surfaceRegions.map(region=>`<article class="settings-card surface-config-card" data-region-card="${region.id}"><header><div><h4>${region.name}</h4><small>${region.hint}</small></div><span class="surface-badge" id="${region.id}SurfaceBadge"></span><button type="button" class="surface-reset" data-reset-surface="${region.id}" aria-label="恢复${region.name}默认" title="恢复本区默认">↺</button></header><label class="surface-slider" for="${surfaceOpacityId(region.id)}"><span>不透明度 <output id="${surfaceOpacityId(region.id)}Value"></output></span><input id="${surfaceOpacityId(region.id)}" type="range" min="0" max="100" step="1" data-surface-field="${surfaceKey(region.id,'opacity')}"></label><label class="surface-slider" for="${region.id}Blur"><span>背景模糊 <output id="${region.id}BlurValue"></output></span><input id="${region.id}Blur" type="range" min="0" max="40" step="1" data-surface-field="${surfaceKey(region.id,'blur')}"></label><details class="surface-text-options"><summary>文字颜色与边线</summary><label>文字颜色</label>${surfaceColorControls(region,'text_color')}<label class="surface-slider" for="${region.id}StrokeWidth"><span>边线粗细 <output id="${region.id}StrokeWidthValue"></output></span><input id="${region.id}StrokeWidth" type="range" min="0" max="2" step="0.25" data-surface-field="${surfaceKey(region.id,'stroke_width')}"></label><label>描边颜色</label>${surfaceColorControls(region,'stroke_color')}</details><button type="button" class="surface-copy" data-copy-surface="${region.id}">将本区样式应用到全部区域</button></article>`).join('')}</div><aside class="surface-preview-column"><div class="surface-live-preview"><div class="surface-demo-wallpaper"></div><div class="surface-demo-topbar">学习空间 · 预览</div><div class="surface-demo-sidebar">项目<br><br>证明与动机<br><br>概念与边界</div><div class="surface-demo-toolbar">精学 · 同一位导师</div><div class="surface-demo-reading"><strong>先看条件，再看方法。</strong><p>说明为什么这样构造，再把每一步连接起来。</p><div class="surface-demo-message">我想理解证明的动机。</div><div id="surfacePreviewMath"></div></div><div class="surface-demo-context">资料<br><br>原文 A<br>原文 B</div><div class="surface-demo-composer">还有哪里不清楚？<span class="surface-demo-control">发送 →</span></div></div><p class="small-note">实色区域会遮住后面的画面；调低不透明度后更容易看到局部模糊效果。主界面底色可影响其上方的透明区域。</p><p class="small-note" id="surfaceSaveStatus" role="status">即时预览，自动保存</p><p class="small-note">文字保持显示。可随时恢复本区默认或全体界面默认。</p></aside></div>`;
  section.append(surfaces);
  const protection=document.createElement('div');protection.className='readability-settings readable-panel';
  protection.innerHTML=`<div><span class="eyebrow">清楚地读，舒服地看</span><h4>文字可读性保护</h4><p>为说明、导师正文、信息卡片、项目统计与筛选栏加独立底板，使用主题配色。开启后这些内容优先保持清晰；其他区域仍按分区设置显示。想让文字区也完全透底，可关闭保护，原来的透明度和文字颜色会恢复。</p><span id="readabilityStatus" class="small-note" role="status"></span></div><label for="readabilityMode">启用方式<select id="readabilityMode"><option value="auto">有背景时启用（推荐）</option><option value="always">始终启用</option><option value="off">关闭 · 完全自定义</option></select></label>`;
  surfaces.querySelector('.surface-preset-bar').after(protection);
  document.getElementById('readabilityMode').onchange=event=>saveStudioPreferences({ui_readability:event.target.value});
  const jump=document.createElement('select');jump.id='surfaceJump';jump.setAttribute('aria-label','快速定位需要调整的界面区域');
  jump.innerHTML='<option value="">快速定位区域…</option>'+surfaceRegions.map(region=>`<option value="${region.id}">${region.name}</option>`).join('');
  document.getElementById('resetSurfacePreferences').before(jump);
  jump.onchange=()=>{const id=jump.value;if(!id)return;const card=surfaces.querySelector(`[data-region-card="${id}"]`);
    const reduced=studioPreferences.ui_motion==='reduced'||matchMedia('(prefers-reduced-motion: reduce)').matches;
    card.scrollIntoView({block:'center',behavior:reduced?'auto':'smooth'});document.getElementById(surfaceOpacityId(id)).focus({preventScroll:true});jump.value='';};
  const fonts=document.createElement('div');fonts.className='settings-card appearance-panel';fonts.id='appearance-panel-typography';fonts.dataset.appearancePanel='typography';
  fonts.innerHTML=`<div class="settings-card-head"><span>TYPOGRAPHY</span><h3>喜欢的字体，清楚的文字</h3><p>界面与导师正文使用所选字体；代码、公式保留自己的排版，原文引用保留衬线字体。</p></div><label class="appearance-font-select">界面字体<select id="appearanceFontFamily"><option value="system">系统默认</option><option value="sans">微软雅黑 · 清晰无衬线</option><option value="serif">宋体 · 衬线</option><option value="kai">楷体</option><option value="custom">上传的自定义字体</option></select></label><div class="appearance-font-upload"><div><strong id="appearanceFontName">未上传自定义字体</strong><p id="appearanceFontNotice" class="small-note">TTF / OTF / WOFF / WOFF2 · 最大 50 MB · 单独保存在本机</p></div><button id="chooseAppearanceFont" type="button">上传字体</button><button id="removeAppearanceFont" type="button">删除字体副本</button><input id="appearanceFontFile" type="file" accept=".ttf,.otf,.woff,.woff2" hidden></div><div class="appearance-font-sample"><h4>把一个结论讲清楚，也把它的来路讲清楚。</h4><p>理解概念、条件、构造动机和使用边界。Explain the idea before the calculation.</p><blockquote>原文引用仍与讲解区分。</blockquote><pre><code>const idea = "keep code readable";</code></pre></div><p>每个区域的文字颜色与边线在「各区域外观 → 文字颜色与边线」调整。自动边线会选择与文字相反的颜色；0 px 关闭。代码、公式和图标不加描边。</p>`;section.append(fonts);
  const dynamic=document.createElement('style');dynamic.id='surfaceRegionStyles';
  dynamic.textContent=surfaceRegions.map(region=>`html:root body :where(${region.selector},.surface-demo-${region.id}){--sf-fill:color-mix(in srgb,var(--${region.base}) var(--${region.id}-opacity),transparent);--sf-filter:var(--${region.id}-filter);--ink:var(--${region.id}-text,var(--theme-ink));--muted:var(--${region.id}-muted,var(--theme-muted));--lesson-ink:var(--${region.id}-text,var(--theme-lesson-ink));--sf-stroke-width:var(--${region.id}-stroke-width);--sf-stroke-color:var(--${region.id}-stroke-color);background:var(--sf-fill)!important;backdrop-filter:var(--sf-filter);-webkit-backdrop-filter:var(--sf-filter);color:var(--ink);-webkit-text-stroke:var(--sf-stroke-width) var(--sf-stroke-color);paint-order:stroke fill;}`).join('\n');document.head.append(dynamic);
  tabs.onclick=event=>{const button=event.target.closest('[data-appearance-tab]');if(button)showAppearanceTab(button.dataset.appearanceTab);};
  tabs.onkeydown=event=>{const buttons=[...tabs.children],index=buttons.indexOf(document.activeElement);let next;if(event.key==='ArrowRight')next=(index+1)%buttons.length;else if(event.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;if(next!==undefined){event.preventDefault();showAppearanceTab(buttons[next].dataset.appearanceTab);buttons[next].focus();}};
  surfaces.oninput=event=>{const input=event.target;if(input.dataset.surfaceField)previewStudioPreferences({[input.dataset.surfaceField]:Number(input.value)});else if(input.dataset.surfaceColorInput){const [id,field]=input.dataset.surfaceColorInput.split(':');previewStudioPreferences({[surfaceKey(id,field)]:input.value});}};
  surfaces.onchange=()=>flushStudioDraft();
  surfaces.onclick=event=>{const button=event.target.closest('button');if(!button)return;
    if(button.dataset.surfaceColor){const [id,field]=button.dataset.surfaceColor.split(':');saveStudioPreferences({[surfaceKey(id,field)]:button.dataset.color});}
    else if(button.dataset.surfacePreset)surfacePreset(button.dataset.surfacePreset);
    else if(button.dataset.resetSurface){const id=button.dataset.resetSurface;saveStudioPreferences(Object.fromEntries(Object.entries(surfaceDefaults).filter(([key])=>key.startsWith(`ui_${id}_`))));}
    else if(button.dataset.copySurface){const delta={};for(const region of surfaceRegions)for(const field of Object.keys(surfaceFields))delta[surfaceKey(region.id,field)]=studioPreferences[surfaceKey(button.dataset.copySurface,field)];saveStudioPreferences(delta);toast('本区样式已应用到全部区域');}
  };
  document.getElementById('resetSurfacePreferences').onclick=()=>saveStudioAction(()=>api('/api/appearance/surfaces/reset',{method:'POST'}));
  document.getElementById('appearanceFontFamily').onchange=event=>saveStudioPreferences({ui_font_family:event.target.value});
  document.getElementById('chooseAppearanceFont').onclick=()=>document.getElementById('appearanceFontFile').click();
  document.getElementById('appearanceFontFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;const button=document.getElementById('chooseAppearanceFont');button.disabled=true;try{if(file.size>50*1024*1024)throw new Error('字体不能超过 50 MB');const body=new FormData();body.append('file',file);await saveStudioAction(()=>api('/api/appearance/font',{method:'POST',body}));}catch(failure){error(failure);}finally{button.disabled=false;event.target.value='';}};
  document.getElementById('removeAppearanceFont').onclick=()=>saveStudioAction(()=>api('/api/appearance/font',{method:'DELETE'}));
  if(window.katex)katex.render(String.raw`\sum_{i=1}^{n}a_i^2\geq\frac{(\sum a_i)^2}{n}`,document.getElementById('surfacePreviewMath'),{throwOnError:false});
  section.querySelectorAll('[data-appearance-panel]').forEach(panel=>{panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','appearance-tab-'+panel.dataset.appearancePanel);});
  showAppearanceTab(appearanceTab);
}
