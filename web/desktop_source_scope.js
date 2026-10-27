(()=>{
  const selectable=row=>['ready','stored'].includes(row.status);
  async function open(id){const source=state.sources.find(row=>row.id===id);if(!source)return;const project=state.project.id,conversation=state.conversation;
    return window.studyforgeSourceScope.open(source,{onParsed:async result=>{
      if(state.project?.id!==project||state.conversation!==conversation)return;
      state.selected.delete(source.id);
      if(!result.job_id){await refreshSources();if(state.conversation===conversation)setSourceSelected(result.source_id,true);toast(result.scope==='full'?'资料已解析，可以直接引用。':'只解析了你选择的范围；原文件保留。');return;}
      toast(window.studyforgeSourceScope.policy(source).partial?'已按你的选择开始解析，可以继续处理其他资料。':source.parse_type==='image'?'已开始识别图片，可以继续处理其他资料。':'已开始读取网址内容，可以继续处理其他资料。');
      trackJob(result.job_id).then(job=>{if(job.status==='completed'&&state.project?.id===project&&state.conversation===conversation)setSourceSelected(result.source_id,true);}).catch(error);
      await refreshSources();
    }});
  }
  function decorate(){
    if(!state.sources)return;
    for(const source of state.sources.filter(row=>row.status!=='pending'&&!row.artifact_id)){
      const label=document.querySelector(`[data-quick-source="${source.id}"]`)?.closest('label');
      const actions=document.getElementById('preview-'+source.id)?.previousElementSibling;
      for(const container of [label,actions].filter(Boolean)){
        if(container.querySelector('[data-source-scope]'))continue;
        const action=window.studyforgeSourceScope.action(source,container===label);
        const button=document.createElement('button');button.type='button';button.className='source-scope-button';button.dataset.sourceScope=source.id;button.textContent=action.label;button.title=action.title;button.disabled=action.disabled;button.onclick=async event=>{event.preventDefault();event.stopPropagation();button.disabled=true;try{await open(source.id);}catch(failure){error(failure);}finally{button.disabled=action.disabled;}};container.append(button);
        if(container===label&&['stored','error'].includes(source.status)&&source.origin_url&&window.studyforgeDesktop?.importBrowserPage){const browser=document.createElement('button');browser.type='button';browser.className='source-scope-button';browser.textContent='浏览器读取';browser.title='在桌面浏览器完成登录或验证后读取正文或视频';browser.onclick=async event=>{event.preventDefault();event.stopPropagation();browser.disabled=true;try{await importInBrowser(source.origin_url,state.project.id,source.category_id,state.conversation,source.id);}catch(failure){error(failure);}finally{browser.disabled=false;}};container.append(browser);}
      }
      if(source.status==='stored'&&label){const tag=label.querySelector('em')||document.createElement('em');if(tag.textContent!=='待解析')tag.textContent='待解析';if(!tag.isConnected)label.insertBefore(tag,label.lastChild);}
    }
  }
  for(const id of ['quickSources','sources']){const element=document.getElementById(id);if(element)new MutationObserver(decorate).observe(element,{childList:true,subtree:true});}
  window.openSourceScope=open;decorate();
})();
