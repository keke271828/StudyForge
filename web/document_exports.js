/* One local lecture snapshot, multiple layouts; no new model requests. */
(() => {
  'use strict';
  const phone = typeof mobile !== 'undefined';
  const names = {docx:'Word · DOCX',pdf:'PDF',pptx:'幻灯片 · PPTX',mm:'思维导图 · FreeMind',md:'Markdown',txt:'纯文本'};
  const scope = () => phone ? mobile.project?.id : state.project?.id;
  const dialog = document.createElement('dialog');
  dialog.id='documentExportDialog';dialog.className='document-export-dialog';
  dialog.setAttribute('aria-labelledby','documentExportTitle');
  dialog.innerHTML='<form><header><div><span class="document-export-eyebrow">保存已有讲解</span><h2 id="documentExportTitle">换个格式保存讲解</h2></div><button type="button" data-export-close aria-label="关闭另存窗口">✕</button></header><p data-export-source></p><p class="document-export-note">把现有讲解保存成另一种文件，文字、公式和来源保持原样，不再请 AI 重写。原文件保留，新文件也放在同一项目。</p><label for="documentExportFormat">另存格式</label><select id="documentExportFormat"></select><p class="document-export-limit">这里只换文件格式，不改变讲解。想重新编写内容、制作 Anki 卡片或可运行代码，请回工作台重新生成。</p><p data-export-status role="status"></p><footer><button type="button" data-export-close>取消</button><button type="submit" class="document-export-submit">开始另存</button></footer></form>';
  document.body.append(dialog);
  const form=dialog.querySelector('form'),select=dialog.querySelector('select'),submit=form.querySelector('[type="submit"]');
  const titleLabel=document.createElement('label');titleLabel.textContent='成果名称';titleLabel.hidden=true;
  const titleInput=document.createElement('input');titleInput.type='text';titleInput.maxLength=120;titleInput.setAttribute('aria-label','成果名称');titleLabel.append(titleInput);
  form.insertBefore(titleLabel,select.previousElementSibling);
  const status=dialog.querySelector('[data-export-status]');let target=null,busy=false;
  const requestId=()=>crypto.randomUUID ? crypto.randomUUID().replaceAll('-','') : [...crypto.getRandomValues(new Uint8Array(16))].map(n=>n.toString(16).padStart(2,'0')).join('');
  for(const close of dialog.querySelectorAll('[data-export-close]')) close.onclick=()=>dialog.close();
  select.onchange=()=>{if(target&&!busy){target.requestId=requestId();status.textContent='';}};
  titleInput.oninput=()=>{if(target&&!busy)target.requestId=requestId();};
  function open(kind,row,projectId){
    if(busy){toast('上一份另存请求正在提交，请稍等。');return;}
    const formats=(row.export_formats||[]).filter(fmt=>names[fmt]);if(!formats.length)return;
    target={kind,id:row.id,projectId,requestId:requestId(),conversationId:row.conversationId,content:row.content};select.replaceChildren();
    for(const fmt of formats){const option=document.createElement('option');option.value=fmt;option.textContent=names[fmt];select.append(option);}
    select.value=row.format==='docx'&&formats.includes('pdf')?'pdf':'docx';
    if(!select.value)select.value=formats[0];
    const chat=kind==='messages';titleLabel.hidden=!chat;titleInput.value=chat?(row.title||'导师回答'):'';
    dialog.querySelector('#documentExportTitle').textContent=chat?'保存这条回答':'换个格式保存讲解';
    dialog.querySelector('[data-export-source]').textContent=chat?'原样保存你正在看的这条已完成回答':kind==='artifacts'?row.title:'已保存的完整讲解正文 · 原排版失败';
    dialog.querySelector('.document-export-note').textContent=chat?'把这条回答直接保存成文件，不再请 AI 重写或检查。文件放在这条回答所属的项目，聊天记录保留。':'把现有讲解保存成另一种文件，文字、公式和来源保持原样，不再请 AI 重写。原文件保留，新文件也放在同一项目。';
    status.textContent='';submit.disabled=false;select.disabled=false;titleInput.disabled=false;
    if(!dialog.open)dialog.showModal();
  }
  function attach(kind,row,actions,projectId){
    if(!row.export_formats?.length||!actions)return;
    if(kind==='jobs'&&row.status!=='failed')return;
    const button=document.createElement('button');button.type='button';
    button.dataset.localExport=row.id;button.textContent=kind==='jobs'?'讲解已写完 · 可以换格式保存':'换个格式保存讲解';
    button.title='复用原讲解，不重新调用 AI';
    button.onclick=event=>{event.stopPropagation();open(kind,row,projectId);};actions.append(button);
  }
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!target)return;const current={...target,format:select.value,title:titleInput.value.trim()};
    busy=true;submit.disabled=true;select.disabled=true;titleInput.disabled=true;status.textContent='正在提交本机排版任务…';
    try{
      const payload={project_id:current.projectId,format:current.format,request_id:current.requestId};
      if(current.kind==='messages'){
        if(!current.title)throw new Error('请填写成果名称');
        const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(current.content));
        payload.content_sha256=[...new Uint8Array(digest)].map(n=>n.toString(16).padStart(2,'0')).join('');
        payload.conversation_id=current.conversationId;payload.title=current.title;
      }
      const result=await api('/api/'+current.kind+'/'+current.id+'/export',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)});
      dialog.close();toast(result.status==='completed'?'这份另存已完成，可在原项目成果中下载。':'已开始保存文件，不会再次请求 AI。可在任务列表暂停或继续。');
      if(scope()===current.projectId){if(phone)await refreshProject();else await refreshArtifacts();}
    }catch(error){status.textContent=error.message;}
    finally{busy=false;submit.disabled=false;select.disabled=false;titleInput.disabled=false;}
  };
  function attachMessage(node){
    const row=node.exportMessage;
    if(!row||row.role!=='assistant'||!row.content.trim()||row.content.trimEnd().endsWith('[本次回复已停止，以上内容尚未完成。]')||node.querySelector('[data-save-message]'))return;
    const actions=document.createElement('div');actions.className='message-save-actions';
    const button=document.createElement('button');button.type='button';button.dataset.saveMessage=row.id;
    button.textContent='保存为成果';button.title='直接把这条回答保存成文件，不再请求 AI';
    button.onclick=()=>{
      let title=[...row.content.matchAll(/^#{1,4}\s+([^\n]+)$/gm)].map(m=>m[1].replaceAll('**','').trim()).find(t=>! /^(?:系统性总结|系统总结|总结|summary|systematic summary)$/i.test(t));
      if(!title){let previous=node.previousElementSibling;while(previous&&!previous.matches('.message.user'))previous=previous.previousElementSibling;
        const question=previous?.querySelector('.message-content,.plain-text')?.textContent.trim();title=question?'学习笔记 · '+question.split('\n',1)[0]:'导师回答 · '+new Date().toLocaleDateString('zh-CN');}
      open('messages',{...row,title:title.slice(0,80),export_formats:Object.keys(names)},row.projectId);
    };
    actions.append(button);node.append(actions);
  }
  window.studyforgeDocumentExports={
    attachArtifact:(row,actions,projectId)=>attach('artifacts',row,actions,projectId),
    attachJob:(row,actions,projectId)=>attach('jobs',row,actions,projectId),attachMessage
  };
  document.querySelectorAll('[data-export-message]').forEach(attachMessage);
})();
