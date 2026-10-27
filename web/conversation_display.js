/* Temporary layout controls. Keep the same conversation, DOM and task state. */
const conversationDisplay={expanded:false,toolsVisible:true,preferredToolsVisible:true,fullscreen:false,busy:false,
  session:null,exitAfterTransition:false,revision:0,viewportRevision:0};
let conversationWindowPoll,conversationWindowPollBusy=false;

async function refreshConversationWindowState() {
  if(conversationWindowPollBusy||conversationDisplay.busy||!window.studyforgeDesktop?.windowState)return;
  conversationWindowPollBusy=true;const revision=conversationDisplay.revision;
  try{
    const value=await window.studyforgeDesktop.windowState();
    if(revision===conversationDisplay.revision&&!conversationDisplay.busy&&Boolean(value.fullscreen)!==conversationDisplay.fullscreen)reflectConversationFullscreen(value.fullscreen);
  }catch(_){/* A closing or hidden window can reconcile when it becomes visible. */}
  finally{conversationWindowPollBusy=false;}
}

function watchConversationWindowState() {
  const needed=window.studyforgeDesktop?.windowState&&conversationDisplay.fullscreen;
  if(needed&&!conversationWindowPoll)conversationWindowPoll=setInterval(refreshConversationWindowState,500);
  else if(!needed&&conversationWindowPoll){clearInterval(conversationWindowPoll);conversationWindowPoll=null;}
}

function changeConversationViewport(update) {
  const host=$('messages'),rect=host.getBoundingClientRect();
  if(!host.clientHeight){update();return;}
  const bottom=host.scrollHeight-host.clientHeight-host.scrollTop<=32;
  const blocks=[...host.querySelectorAll('.message p,.message li,.message pre,.message h1,.message h2,.message h3,.homework-questionnaire fieldset')];
  const anchor=blocks.find(el=>el.getBoundingClientRect().bottom>rect.top+8)||[...host.children].find(el=>el.getBoundingClientRect().bottom>rect.top+8);
  const offset=anchor?anchor.getBoundingClientRect().top-rect.top:0,oldTop=host.scrollTop;
  update();const revision=++conversationDisplay.viewportRevision;
  requestAnimationFrame(()=>{
    if(revision!==conversationDisplay.viewportRevision||state.view!=='study'||!host.clientHeight)return;
    if(bottom)host.scrollTop=host.scrollHeight;
    else if(anchor?.isConnected)host.scrollTop+=anchor.getBoundingClientRect().top-host.getBoundingClientRect().top-offset;
    else host.scrollTop=oldTop;
  });
}

function syncConversationDisplay() {
  const mode=conversationDisplay,expanded=mode.expanded&&state.view==='study';
  changeConversationViewport(()=>{
    document.documentElement.dataset.chatExpanded=String(expanded);
    document.documentElement.dataset.chatTools=String(mode.toolsVisible);
  });
  const expand=$('expandConversation'),fullscreen=$('fullscreenConversation'),tools=$('toggleConversationTools');
  if(!expand)return;
  expand.textContent=expanded?'还原布局':'放大对话';expand.setAttribute('aria-pressed',String(expanded));
  expand.title=expanded?'重新显示项目栏和资料快选 · Esc':'占满当前窗口 · Ctrl+Shift+E';
  fullscreen.textContent=mode.busy?'切换中…':mode.fullscreen?'退出全屏':'全屏';
  fullscreen.setAttribute('aria-pressed',String(mode.fullscreen));fullscreen.title='隐藏窗口边框，进入全屏 · F11';
  expand.disabled=fullscreen.disabled=mode.busy;
  tools.hidden=false;tools.textContent=mode.toolsVisible?'收起导师工具':'展开导师工具';
  tools.title='显示或收起模型、学习模式、通读和生成设置；已选选项不变';
  tools.setAttribute('aria-expanded',String(mode.toolsVisible));
  $('conversationDisplayHint').textContent=expanded?(mode.fullscreen?'全屏对话 · F11 退出 · Esc 还原':'放大对话 · F11 全屏 · Esc 还原'):'';
  watchConversationWindowState();
  if(conversationLayoutReady)requestConversationLayout();
}

function applyConversationToolsPreference(visible) {
  conversationDisplay.preferredToolsVisible=Boolean(visible);
  if(!conversationDisplay.expanded&&!conversationDisplay.session)conversationDisplay.toolsVisible=Boolean(visible);
  syncConversationDisplay();
}

async function toggleConversationTools() {
  if(!conversationDisplay.expanded&&!conversationDisplay.session)
    return saveStudioPreferences({ui_tutor_tools_visible:!conversationDisplay.preferredToolsVisible});
  conversationDisplay.toolsVisible=!conversationDisplay.toolsVisible;
  syncConversationDisplay();
}

function startConversationFullscreenSession() {
  if(conversationDisplay.session)return;
  conversationDisplay.session={expanded:conversationDisplay.expanded,toolsVisible:conversationDisplay.toolsVisible};
  conversationDisplay.expanded=true;conversationDisplay.toolsVisible=false;
}

function finishConversationFullscreenSession() {
  const previous=conversationDisplay.session;if(!previous)return;
  conversationDisplay.session=null;conversationDisplay.expanded=previous.expanded;
  conversationDisplay.toolsVisible=previous.expanded?previous.toolsVisible:conversationDisplay.preferredToolsVisible;
}

function reflectConversationFullscreen(value) {
  const was=conversationDisplay.fullscreen;
  conversationDisplay.fullscreen=Boolean(value);
  if(!conversationDisplay.busy){
    if(value&&state.view==='study')startConversationFullscreenSession();
    else if(!value&&was)finishConversationFullscreenSession();
  }
  syncConversationDisplay();
}

async function setConversationFullscreen(value) {
  const mode=conversationDisplay;
  if(mode.busy){if(!value)mode.exitAfterTransition=true;return;}
  if(!value&&!mode.fullscreen&&!mode.session)return;
  mode.busy=true;mode.revision++;
  if(value)startConversationFullscreenSession();
  syncConversationDisplay();
  try{
    if(window.studyforgeDesktop?.setFullscreen){
      const result=await window.studyforgeDesktop.setFullscreen(value);
      mode.fullscreen=Boolean(result.fullscreen);
      if(mode.fullscreen!==value)throw Error('窗口未完成全屏切换，请重试');
    }else{
      if(value){
        if(!document.documentElement.requestFullscreen)throw Error('当前浏览器不支持全屏，可以使用“放大对话”');
        await document.documentElement.requestFullscreen();
      }else if(document.fullscreenElement)await document.exitFullscreen();
      mode.fullscreen=Boolean(document.fullscreenElement);
      if(mode.fullscreen!==value)throw Error('浏览器未完成全屏切换，请重试');
    }
    if(!value)finishConversationFullscreenSession();
  }catch(failure){
    try{mode.fullscreen=window.studyforgeDesktop?.windowState?Boolean((await window.studyforgeDesktop.windowState()).fullscreen):Boolean(document.fullscreenElement);}
    catch(_){/* Preserve the last native notification if the window is closing. */}
    if(!mode.fullscreen)finishConversationFullscreenSession();
    error(failure);
  }finally{
    mode.busy=false;syncConversationDisplay();
    if(mode.exitAfterTransition){mode.exitAfterTransition=false;await setConversationFullscreen(false);}
  }
}

function restoreConversationLayout() {
  if(conversationDisplay.session){conversationDisplay.session.expanded=false;conversationDisplay.session.toolsVisible=conversationDisplay.preferredToolsVisible;}
  conversationDisplay.expanded=false;conversationDisplay.toolsVisible=conversationDisplay.preferredToolsVisible;
  syncConversationDisplay();
  if(conversationDisplay.fullscreen||conversationDisplay.busy||conversationDisplay.session)setConversationFullscreen(false).catch(error);
}

function toggleConversationExpansion() {
  if(conversationDisplay.expanded||conversationDisplay.fullscreen||conversationDisplay.session)return restoreConversationLayout();
  conversationDisplay.expanded=true;conversationDisplay.toolsVisible=false;syncConversationDisplay();
}

function conversationDisplayViewChanged(view) {
  if(view!=='study')restoreConversationLayout();else syncConversationDisplay();
}

function initializeConversationDisplay() {
  const heading=document.querySelector('.conversation-heading');
  const controls=document.createElement('div');controls.className='conversation-display-controls';controls.setAttribute('role','group');controls.setAttribute('aria-label','对话显示大小');
  controls.innerHTML='<button id="toggleConversationTools" type="button" aria-controls="learningMode readingBar studyModel outputFormat summaryLevel" aria-expanded="true">收起导师工具</button><button id="expandConversation" type="button" aria-pressed="false">放大对话</button><button id="fullscreenConversation" type="button" aria-pressed="false">全屏</button>';
  heading.append(controls);
  const hint=document.createElement('small');hint.id='conversationDisplayHint';hint.className='conversation-display-hint';hint.setAttribute('role','status');heading.after(hint);
  $('expandConversation').onclick=toggleConversationExpansion;
  $('fullscreenConversation').onclick=()=>setConversationFullscreen(!(conversationDisplay.fullscreen||conversationDisplay.session)).catch(error);
  $('toggleConversationTools').onclick=()=>toggleConversationTools().catch(error);
  heading.addEventListener('dblclick',event=>{if(!event.target.closest('button,input,select,a')){event.preventDefault();toggleConversationExpansion();}});
  document.addEventListener('fullscreenchange',()=>reflectConversationFullscreen(Boolean(document.fullscreenElement)));
  if(window.studyforgeDesktop?.onWindowChanged){
    window.studyforgeDesktop.onWindowChanged(value=>reflectConversationFullscreen(value.fullscreen));
    const revision=conversationDisplay.revision;
    window.studyforgeDesktop.windowState().then(value=>{if(revision===conversationDisplay.revision)reflectConversationFullscreen(value.fullscreen);}).catch(()=>{});
    window.addEventListener('focus',refreshConversationWindowState);
    window.addEventListener('resize',refreshConversationWindowState);
  }
  document.addEventListener('keydown',event=>{
    if(event.isComposing||event.defaultPrevented)return;
    if(event.key==='F11'&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&state.view==='study'){
      event.preventDefault();event.stopImmediatePropagation();
      if(!event.repeat)setConversationFullscreen(!(conversationDisplay.fullscreen||conversationDisplay.session)).catch(error);return;
    }
    if(document.querySelector('dialog[open]')||!$('navigationContext')?.hidden||navigationUI.editing||document.querySelector('.advanced-generation[open]'))return;
    if(event.ctrlKey&&event.shiftKey&&!event.altKey&&!event.metaKey&&event.key.toLowerCase()==='e'&&state.view==='study'){
      event.preventDefault();event.stopImmediatePropagation();if(!event.repeat)toggleConversationExpansion();return;
    }
    if(event.key==='Escape'&&(conversationDisplay.fullscreen||conversationDisplay.session||conversationDisplay.expanded)){
      event.preventDefault();event.stopImmediatePropagation();
      if(event.repeat)return;
      if(conversationDisplay.fullscreen||conversationDisplay.session)setConversationFullscreen(false).catch(error);
      else restoreConversationLayout();
    }
  },true);
  syncConversationDisplay();
}
