/* Resize the reading/composer split, keeping the same chat and original task options. */
const conversationLayoutDefaults={ui_reading_share:.65,ui_generation_options_visible:true,ui_tutor_tools_visible:true};
let conversationLayoutReady=false,conversationLayoutFrame,conversationLayoutDragging=false;

function applyConversationLayoutPreferences(config){
  document.documentElement.dataset.generationOptions=String(config.ui_generation_options_visible??true);
  applyConversationToolsPreference(config.ui_tutor_tools_visible??true);
  if(!conversationLayoutReady)return;
  const button=$('toggleGenerationOptions'),visible=config.ui_generation_options_visible??true;
  button.textContent=visible?'收起生成选项':'展开生成选项';button.setAttribute('aria-expanded',String(visible));
  requestConversationLayout();
}

function requestConversationLayout(){
  cancelAnimationFrame(conversationLayoutFrame);conversationLayoutFrame=requestAnimationFrame(sizeConversationReading);
}

function readingGeometry(){
  const composer=document.querySelector('.conversation-panel>.composer'),panel=composer.parentElement,textarea=$('prompt');
  if(!panel.clientHeight||!composer.clientHeight||state.view!=='study')return null;
  const style=getComputedStyle(composer);
  let minimum=parseFloat(style.paddingTop)+parseFloat(style.paddingBottom)+32+2;
  for(const child of composer.children){if(child===textarea||!child.getBoundingClientRect().height)continue;const s=getComputedStyle(child);minimum+=child.getBoundingClientRect().height+parseFloat(s.marginTop||0)+parseFloat(s.marginBottom||0);}
  const available=$('messages').getBoundingClientRect().height+composer.getBoundingClientRect().height;
  return {composer,available,minimum:Math.min(minimum,available-80),maximum:Math.max(minimum,available-100)};
}

function sizeConversationReading(){
  const g=readingGeometry();if(!g)return;
  const share=studioPreferences.ui_reading_share??.65;
  const height=Math.max(g.minimum,Math.min(g.maximum,g.available*(1-share)));
  if(Math.abs(g.composer.getBoundingClientRect().height-height)>1)changeConversationViewport(()=>g.composer.style.setProperty('--chat-composer-height',height+'px'));
  const handle=$('readingResizeHandle');handle.setAttribute('aria-valuenow',String(Math.round(100*(1-height/g.available))));
  handle.setAttribute('aria-valuetext','阅读区占可调空间 '+Math.round(100*(1-height/g.available))+'%');
}

function initializeConversationLayout(){
  const composer=document.querySelector('.conversation-panel>.composer');
  const handle=document.createElement('div');handle.id='readingResizeHandle';handle.className='reading-resize-handle';handle.tabIndex=0;
  handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','horizontal');handle.setAttribute('aria-label','拖动调整阅读区与输入区的大小');handle.setAttribute('aria-valuemin','20');handle.setAttribute('aria-valuemax','95');
  handle.title='向下拖动扩大阅读区，向上拖动扩大输入区；双击尽量扩大阅读区；方向键微调';
  handle.innerHTML='<span></span><small>拖动调整阅读区</small>';
  const strip=document.createElement('div');strip.className='reading-resize-strip';strip.append(handle);composer.prepend(strip);
  const button=document.createElement('button');button.id='toggleGenerationOptions';button.type='button';button.title='收起讲解格式、详略与生成选项；保留生成按钮，已选内容不变';
  button.setAttribute('aria-controls','outputFormat summaryLevel generationMode withExercises');
  strip.append(button);button.onclick=()=>saveStudioPreferences({ui_generation_options_visible:!(studioPreferences.ui_generation_options_visible??true)});
  let drag=null;
  handle.onpointerdown=event=>{
    if(event.button!==0)return;const g=readingGeometry();if(!g)return;
    drag={y:event.clientY,height:g.composer.getBoundingClientRect().height,available:g.available,minimum:g.minimum,maximum:g.maximum};
    conversationLayoutDragging=true;handle.setPointerCapture(event.pointerId);event.preventDefault();
  };
  const move=event=>{
    if(!drag)return;
    const height=Math.max(drag.minimum,Math.min(drag.maximum,drag.height+drag.y-event.clientY));
    const share=Math.max(.2,Math.min(.95,1-height/drag.available));
    previewStudioPreferences({ui_reading_share:share});
  };
  const finish=()=>{if(!drag)return;drag=null;conversationLayoutDragging=false;flushStudioDraft();requestConversationLayout();};
  // Continue dragging across textarea and floating controls, including webviews
  // that release pointer capture after a frame/layout change.
  document.addEventListener('pointermove',move);
  document.addEventListener('pointerup',finish);document.addEventListener('pointercancel',finish);
  window.addEventListener('blur',finish);
  const maximize=()=>saveStudioPreferences({ui_generation_options_visible:false,ui_reading_share:.95});
  handle.ondblclick=maximize;
  handle.onkeydown=event=>{
    if(event.key==='Home'){event.preventDefault();maximize();}
    else if(event.key==='End'){event.preventDefault();saveStudioPreferences({ui_reading_share:.2});}
    else if(['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();saveStudioPreferences({ui_reading_share:Math.max(.2,Math.min(.95,(studioPreferences.ui_reading_share??.65)+(event.key==='ArrowDown'?.05:-.05)))});}
  };
  conversationLayoutReady=true;applyConversationLayoutPreferences(studioPreferences);
  new ResizeObserver(requestConversationLayout).observe(composer.parentElement);
  new ResizeObserver(requestConversationLayout).observe(composer);
  window.addEventListener('resize',requestConversationLayout);
}
