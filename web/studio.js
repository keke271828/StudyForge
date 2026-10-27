/* Presentation preferences are local settings, independent of AI task options. */
const studioDefaults={ui_theme:'paper',ui_text_size:'standard',ui_density:'comfortable',ui_motion:'system',ui_focus:false,ui_send_key:'enter',...backgroundDefaults,...surfaceDefaults,...fontDefaults,...readabilityDefaults,...conversationLayoutDefaults};
let studioPreferences={...studioDefaults},studioConfirmed={...studioDefaults},studioPending=0,studioRevision=0;
let studioSave=Promise.resolve(),studioSettingsSection='appearance';
let studioDraft={},studioDraftTimer;
function applyStudioPreferences(config,force=false,readRevision=studioRevision){
  if(!force&&(studioPending||Object.keys(studioDraft).length||readRevision!==studioRevision)){
    if(state.settings)for(const key of Object.keys(studioDefaults))state.settings[key]=studioPreferences[key];
    return;
  }
  const next={};for(const key of Object.keys(studioDefaults))next[key]=config[key]??studioDefaults[key];
  studioPreferences=next;if(!force)studioConfirmed={...next};
  const root=document.documentElement;
  Object.assign(root.dataset,{theme:next.ui_theme,textSize:next.ui_text_size,density:next.ui_density,
    motion:next.ui_motion,focus:String(next.ui_focus),sendKey:next.ui_send_key});
  for(const [id,key] of [['uiTheme','ui_theme'],['uiTextSize','ui_text_size'],['uiDensity','ui_density'],['uiMotion','ui_motion'],['uiSendKey','ui_send_key']]){
    const el=document.getElementById(id);if(el)el.value=next[key];
  }
  const focus=document.getElementById('toggleFocus');focus.setAttribute('aria-pressed',String(next.ui_focus));
  focus.textContent=next.ui_focus?'退出专注':'专注模式';
  document.getElementById('sendKeyHint').textContent=next.ui_send_key==='ctrl-enter'?'Ctrl+Enter 发送 · Enter 换行':'Enter 发送 · Shift+Enter 换行';
  applyBackgroundPreferences(next);
  applySurfacePreferences(next);
  applyConversationLayoutPreferences(next);
}
function queueStudioOperation(operation,delta={}){
  const next={...studioPreferences,...delta},revision=++studioRevision;studioPending++;
  applyStudioPreferences(next,true);
  setAppearanceStatus('正在保存…');
  studioSave=studioSave.catch(()=>{}).then(async()=>{
    try{
      const config=await operation();
      for(const key of Object.keys(studioDefaults)){studioConfirmed[key]=config[key];if(state.settings)state.settings[key]=config[key];}
      if(revision===studioRevision){applyStudioPreferences(config,true);setAppearanceStatus('已保存，立即生效');}
      else{
        for(const key of ['ui_background_asset','ui_background_name','ui_font_asset','ui_font_name'])studioPreferences[key]=config[key];
        applyBackgroundPreferences(studioPreferences);
        applySurfacePreferences(studioPreferences);
      }
    }catch(failure){
      if(revision===studioRevision){applyStudioPreferences(studioConfirmed,true);setAppearanceStatus('保存失败，已恢复上次设置');}
      error(failure);
    }finally{studioPending--;}
  });
  return studioSave;
}
function setAppearanceStatus(text){
  for(const id of ['appearanceStatus','backgroundSaveStatus','surfaceSaveStatus']){const el=document.getElementById(id);if(el)el.textContent=text;}
}
function flushStudioDraft(){
  clearTimeout(studioDraftTimer);
  if(!Object.keys(studioDraft).length)return studioSave;
  const delta={...studioDraft};studioDraft={};
  return queueStudioOperation(()=>api('/api/settings',jsonOptions('PUT',delta)),delta);
}
function previewStudioPreferences(delta){
  studioRevision++;studioDraft={...studioDraft,...delta};
  applyStudioPreferences({...studioPreferences,...delta},true);setAppearanceStatus('预览中，自动保存…');
  clearTimeout(studioDraftTimer);studioDraftTimer=setTimeout(flushStudioDraft,250);
}
function saveStudioPreferences(delta){
  flushStudioDraft();
  return queueStudioOperation(()=>api('/api/settings',jsonOptions('PUT',delta)),delta);
}
function saveStudioAction(operation){flushStudioDraft();return queueStudioOperation(operation);}
function showSettingsSection(name,focusTab=false){
  if(!document.getElementById('settings-'+name))return;
  studioSettingsSection=name;
  document.querySelectorAll('.settings-section').forEach(el=>{el.hidden=el.id!=='settings-'+name;});
  document.querySelectorAll('[data-settings-section]').forEach(el=>{
    const active=el.dataset.settingsSection===name;el.setAttribute('aria-selected',String(active));el.tabIndex=active?0:-1;
    if(active&&focusTab)el.focus();
  });
  document.querySelector('.settings-save').hidden=['appearance','system','notifications'].includes(name);
}
function initializeStudio(){
  const paths={study:'M4 5h16v11H8l-4 4V5Z',sources:'M3 7h7l2-3h9v16H3V7Z',library:'M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3V4Z M12 6v16',artifacts:'M6 3h8l4 4v14H6V3Z M14 3v5h5 M9 12h6 M9 16h6',
    exercises:'M7 4h13v16H7 M3 8l2 2 4-4 M10 9h6 M10 14h6',profile:'M4 20v-6h4v6 M10 20V9h4v11 M16 20V4h4v16',settings:'M4 7h16 M4 17h16 M8 4v6 M16 14v6',goals:'M5 3v5h14v5H5v5h14v3 M3 3h4 M17 21h4'};
  document.querySelectorAll('.studio-nav [data-view]').forEach(button=>{
    const text=button.textContent;button.textContent='';
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');
    const line=document.createElementNS(icon.namespaceURI,'path');line.setAttribute('d',paths[button.dataset.view]||paths.study);icon.append(line);
    const label=document.createElement('span');label.textContent=text;button.append(icon,label);
    if(button.dataset.view==='study')button.setAttribute('aria-current','page');
  });
  const view=document.getElementById('view-settings'),grid=view.querySelector('.settings-grid');
  const original=[...grid.children];
  const nav=document.createElement('div');nav.className='settings-nav';nav.setAttribute('role','tablist');nav.setAttribute('aria-label','设置分类');
  const groups=[['appearance','外观与操作'],['generation','生成偏好'],['models','模型与语音'],['tools','工具与联动'],['notifications','桌面通知'],['system','运行与更新']];
  for(const [id,label] of groups){
    const button=document.createElement('button');button.type='button';button.id='settings-tab-'+id;button.dataset.settingsSection=id;
    button.setAttribute('role','tab');button.setAttribute('aria-controls','settings-'+id);button.textContent=label;
    button.onclick=()=>showSettingsSection(id);nav.append(button);
    const panel=document.createElement('section');panel.className='settings-section';panel.id='settings-'+id;
    panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);grid.append(panel);
  }
  grid.before(nav);
  const appearance=document.createElement('div');appearance.className='settings-card appearance-card';
  appearance.innerHTML=`<div class="settings-card-head"><span>为你调整</span><h3>让学习更舒适</h3><p>外观选项立即生效并自动保存，不改变模型、学习模式或生成任务。</p></div>
    <div class="appearance-grid"><label>界面主题<select id="uiTheme"><option value="paper">暖纸 · 明亮</option><option value="forest">青绿 · 明亮</option><option value="night">夜读 · 深色</option></select><small>选择适合当前环境的背景与配色</small></label>
    <label>阅读字号<select id="uiTextSize"><option value="standard">标准</option><option value="large">大字</option></select><small>调整导师回复、原文和练习的阅读字号</small></label>
    <label>界面密度<select id="uiDensity"><option value="comfortable">舒适</option><option value="compact">紧凑</option></select><small>调整控件间距，保留清晰的操作区域</small></label>
    <label>动画与过渡<select id="uiMotion"><option value="system">跟随系统</option><option value="reduced">减少动画</option></select><small>尊重系统偏好，也可在这里主动关闭动效</small></label>
    <label>聊天发送方式<select id="uiSendKey"><option value="enter">Enter 发送 · Shift+Enter 换行</option><option value="ctrl-enter">Ctrl+Enter 发送 · Enter 换行</option></select><small>中文输入法选词不会触发发送</small></label></div>
    <p id="appearanceStatus" class="small-note" role="status">设置会保存在本机，重开后仍保留</p>
    <div class="shortcut-guide"><h4>少一点操作，多一点思考</h4><p>项目与对话支持右键管理、行内编辑和拖动排序。专注模式可收起两侧栏；标题旁可放大对话或进入真正的全屏。</p><dl><div><dt>Ctrl + K</dt><dd>回到工作台并输入问题</dd></div><div><dt>Ctrl + P</dt><dd>搜索项目与对话</dd></div><div><dt>Ctrl + N</dt><dd>在当前项目新建对话</dd></div><div><dt>Ctrl + Shift + N</dt><dd>新建学习项目</dd></div><div><dt>F2 / Delete</dt><dd>重命名 / 删除侧边栏焦点项</dd></div><div><dt>Ctrl + Shift + F</dt><dd>切换专注模式</dd></div><div><dt>Ctrl + Shift + E</dt><dd>放大 / 还原对话</dd></div><div><dt>F11</dt><dd>进入 / 退出对话全屏</dd></div><div><dt>Ctrl + 1—6</dt><dd>切换左侧六个工作区</dd></div><div><dt>Esc</dt><dd>先关闭弹窗，再退出全屏、放大或专注</dd></div></dl></div>`;
  document.getElementById('settings-appearance').append(appearance);
  initializeBackground();
  initializeSurfaces();
  for(const [index,name] of [[0,'generation'],[1,'models'],[2,'tools'],[3,'tools'],[4,'system']])document.getElementById('settings-'+name).append(original[index]);
  document.getElementById('settings-system').append(document.getElementById('updateControls'));
  document.getElementById('settings-notifications').append(document.getElementById('desktopNotificationControls'));
  document.getElementById('openAppearance').onclick=()=>{showView('settings');showSettingsSection('appearance');};
  document.getElementById('toggleFocus').onclick=()=>saveStudioPreferences({ui_focus:!studioPreferences.ui_focus});
  for(const [id,key] of [['uiTheme','ui_theme'],['uiTextSize','ui_text_size'],['uiDensity','ui_density'],['uiMotion','ui_motion'],['uiSendKey','ui_send_key']])
    document.getElementById(id).onchange=event=>saveStudioPreferences({[key]:event.target.value});
  nav.onkeydown=event=>{
    const index=groups.findIndex(([id])=>id===studioSettingsSection);let target;
    if(event.key==='ArrowRight')target=(index+1)%groups.length;if(event.key==='ArrowLeft')target=(index+groups.length-1)%groups.length;
    if(event.key==='Home')target=0;if(event.key==='End')target=groups.length-1;
    if(target!==undefined){event.preventDefault();showSettingsSection(groups[target][0],true);}
  };
  document.addEventListener('keydown',event=>{
    if(event.isComposing||document.querySelector('dialog[open]'))return;
    if(event.key==='Escape'&&document.querySelector('.advanced-generation[open]')){
      const menu=document.querySelector('.advanced-generation');menu.open=false;menu.querySelector('summary').focus();event.preventDefault();return;
    }
    if(event.ctrlKey&&!event.altKey&&!event.metaKey){
      if(!event.shiftKey&&event.key.toLowerCase()==='k'){event.preventDefault();showView('study');document.getElementById('prompt').focus();}
      else if(event.shiftKey&&event.key.toLowerCase()==='f'){event.preventDefault();document.getElementById('toggleFocus').click();}
      else if(!event.shiftKey&&/^[1-6]$/.test(event.key)){event.preventDefault();showView(['study','sources','artifacts','exercises','profile','settings'][Number(event.key)-1]);}
    }else if(event.key==='Escape'&&studioPreferences.ui_focus){document.getElementById('toggleFocus').click();}
  });
  showSettingsSection('appearance');applyStudioPreferences(studioDefaults);
}
