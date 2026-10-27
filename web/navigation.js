/* Folder navigation is persisted locally in the database, independently of chat activity. */
const navigationUI = {projects:[], preferences:{sort:'manual',expanded:[]}, loaded:false,
  expanded:new Set(), request:0, revision:0, editing:null, dragging:null, menuTarget:null};
let navigationSave = Promise.resolve();
const navigationIcons = {
  project:'<svg class="navigation-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M2 5h6l2 2h8v9H2V5Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  conversation:'<svg class="navigation-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M3 3h14v11H8l-5 3V3Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>'
};

function navigationMutation(path, body, method='PUT') {
  ++navigationUI.revision; // A pre-mutation poll must not overwrite a completed edit.
  navigationSave = navigationSave.catch(()=>{}).then(()=>api(path, body === null ? {method} : jsonOptions(method,body)));
  return navigationSave;
}
function saveNavigationPreferences() {
  navigationUI.preferences.expanded = [...navigationUI.expanded];
  return navigationMutation('/api/navigation/preferences',navigationUI.preferences).catch(error);
}
function navigationItem(kind,id) {
  if(kind==='project')return navigationUI.projects.find(row=>row.id===id);
  for(const project of navigationUI.projects){const row=project.conversations.find(chat=>chat.id===id);if(row)return row;}
  return null;
}
function orderedNavigation(items) {
  const mode = navigationUI.preferences.sort;
  return [...items].sort((a,b)=>Number(b.pinned)-Number(a.pinned) ||
    (mode==='name' ? (a.name||a.title).localeCompare(b.name||b.title,'zh-CN') :
     mode==='recent' ? String(b.updated_at||b.latest_message_at||b.created_at).localeCompare(String(a.updated_at||a.latest_message_at||a.created_at)) :
     Number(a.position)-Number(b.position) || String(b.created_at).localeCompare(String(a.created_at))) || a.id.localeCompare(b.id));
}
function placeNavigationNodes(host,nodes) {
  const wanted=new Set(nodes);
  for(const child of [...host.children])if(!wanted.has(child))child.remove();
  nodes.forEach((node,index)=>{if(host.children[index]!==node)host.insertBefore(node,host.children[index]||null);});
}
function navigationRow(kind,row,existing) {
  const node=existing||document.createElement('div');
  node.dataset.navKind=kind;node.dataset.navId=row.id;node.dataset.navProject=kind==='project'?row.id:row.project_id;
  node.className=`navigation-row navigation-${kind} ${((kind==='project'?state.project?.id:state.conversation)===row.id)?'active':''}`;
  node.setAttribute('role','treeitem');node.setAttribute('aria-selected',String(node.classList.contains('active')));
  const editing=navigationUI.editing?.id===row.id;
  node.draggable=!editing&&!$('navigationSearch').value.trim();
  if(editing){node.classList.add('is-editing');return node;}
  const label=row.name||row.title, signature=JSON.stringify([label,row.pinned,row.pending_count,row.message_count,row.last_message,row.has_draft,row.conversations?.length]);
  if(node.dataset.signature!==signature){
    node.dataset.signature=signature;
    node.innerHTML=(kind==='project'?`<button class="navigation-toggle" type="button" data-nav-action="expand" aria-label="展开或收起项目">›</button>`:'')+
      `<button class="navigation-open" type="button" data-nav-action="open">${navigationIcons[kind]}<span class="navigation-label">${escapeHtml(label)}</span>${row.pinned?'<span class="navigation-pin" title="已置顶">◆</span>':''}${row.pending_count?'<span class="navigation-task-dot" title="有进行中的任务"></span>':''}${kind==='project'?`<small class="navigation-count">${row.conversations.length}</small>`:''}</button>`+
      `<button type="button" class="navigation-more" data-nav-action="menu" aria-label="管理${escapeHtml(label)}" title="更多操作">⋯</button>`;
  }
  node.querySelector('.navigation-open').title=kind==='project'?label:
    `${label}\n${row.has_draft?'有未发送草稿 · ':''}${row.last_message||'还没有聊天。新对话默认不勾选任何资料。'}\n${row.updated_at?new Date(row.updated_at).toLocaleString('zh-CN'):''}`;
  return node;
}
function renderNavigation() {
  const host=$('projects'),scroll=host.scrollTop,query=$('navigationSearch').value.trim().toLocaleLowerCase();
  const nodes=[];
  // Move the compatibility ID before building new folders so it is always unique.
  const activeHost=$('conversations');if(activeHost&&activeHost!==host)activeHost.removeAttribute('id');
  for(const project of orderedNavigation(navigationUI.projects)){
    const matchesProject=project.name.toLocaleLowerCase().includes(query);
    const chats=orderedNavigation(project.conversations).filter(chat=>!query||matchesProject||chat.title.toLocaleLowerCase().includes(query)||chat.last_message?.toLocaleLowerCase().includes(query));
    if(query&&!matchesProject&&!chats.length)continue;
    let folder=[...host.children].find(node=>node.dataset.folder===project.id);
    if(!folder){folder=document.createElement('section');folder.className='navigation-folder';folder.dataset.folder=project.id;folder.append(document.createElement('div'),document.createElement('div'));folder.lastElementChild.className='navigation-chats';folder.lastElementChild.setAttribute('role','group');}
    const row=navigationRow('project',project,folder.firstElementChild);if(row!==folder.firstElementChild)folder.prepend(row);
    const expanded=!!query||navigationUI.expanded.has(project.id);
    row.setAttribute('aria-expanded',String(expanded));row.querySelector('.navigation-toggle')?.setAttribute('aria-expanded',String(expanded));
    const list=folder.lastElementChild;list.hidden=!expanded;
    if(project.id===state.project?.id)list.id='conversations';
    const chatNodes=chats.map(chat=>navigationRow('conversation',chat,[...list.children].find(node=>node.dataset.navId===chat.id)));
    let newButton=list.querySelector('.navigation-new-chat');
    if(!newButton){newButton=document.createElement('button');newButton.type='button';newButton.className='navigation-new-chat';newButton.dataset.navAction='new';newButton.dataset.project=project.id;newButton.textContent='＋ 新建对话';}
    chatNodes.push(newButton);placeNavigationNodes(list,chatNodes);nodes.push(folder);
  }
  if(!nodes.length){const empty=document.createElement('p');empty.className='navigation-empty';empty.textContent=query?'没有匹配的项目或对话':'创建一个项目，开始整理你的学习。';nodes.push(empty);}
  placeNavigationNodes(host,nodes);host.scrollTop=scroll;
  if(!$('conversations')){const parked=document.querySelector('.navigation-parking')||document.createElement('div');parked.className='navigation-parking';parked.id='conversations';parked.hidden=true;host.after(parked);}
  else document.querySelectorAll('#conversations').forEach((node,index)=>{if(index)node.remove();});
  $('navigationSort').value=navigationUI.preferences.sort;
}
async function refreshNavigation() {
  const request=++navigationUI.request,revision=navigationUI.revision;
  const result=await api('/api/navigation');
  if(request!==navigationUI.request||revision!==navigationUI.revision)return null;
  navigationUI.projects=result.projects;
  if(!navigationUI.loaded){navigationUI.preferences=result.preferences;navigationUI.expanded=new Set(result.preferences.expanded);navigationUI.loaded=true;}
  if(navigationUI.editing&&!navigationItem(navigationUI.editing.kind,navigationUI.editing.id))cancelNavigationRename();
  renderNavigation();return result;
}
function syncNavigationConversations() {
  const project=navigationUI.projects.find(row=>row.id===state.project?.id);
  if(project){project.conversations=conversationUI.items.map(chat=>({...project.conversations.find(row=>row.id===chat.id),...chat}));}
  renderNavigation();
}
function expandNavigation(id,expanded=true) {
  if(expanded)navigationUI.expanded.add(id);else navigationUI.expanded.delete(id);
  renderNavigation();return saveNavigationPreferences();
}
async function openNavigationItem(kind,id,view='study') {
  const row=navigationItem(kind,id);if(!row)return;
  const projectId=kind==='project'?id:row.project_id,project=navigationItem('project',projectId);
  expandNavigation(projectId,true);
  if(projectId!==state.project?.id)await selectProject(project,{conversationId:kind==='conversation'?id:null});
  else if(kind==='conversation')await selectConversation(id);
  showView(view);
}
function navigationElement(kind,id) {return [...$('projects').querySelectorAll('.navigation-row')].find(row=>row.dataset.navKind===kind&&row.dataset.navId===id);}
function closeNavigationMenu(restoreFocus=false) {
  $('navigationContext').hidden=true;const target=navigationUI.menuTarget;navigationUI.menuTarget=null;
  if(restoreFocus&&target)navigationElement(target.kind,target.id)?.querySelector('.navigation-open').focus({preventScroll:true});
}
function openNavigationMenu(kind,id,x,y) {
  if(navigationUI.editing)return;
  const item=navigationItem(kind,id);if(!item)return;
  navigationUI.menuTarget={kind,id};
  const actions=[['open','打开',''],...(kind==='project'?[['new','新建对话','Ctrl+N']]:[]),['rename','重命名','F2'],['pin',item.pinned?'取消置顶':'置顶',''],
    ['artifacts','查看项目成果',''],...(kind==='project'?[['sources','查看项目资料','']]:[]),['delete',kind==='project'?'移入项目回收站':'删除对话','Delete']];
  const menu=$('navigationContext');menu.innerHTML=`<div class="navigation-context-caption">${escapeHtml(item.name||item.title)}</div>`+
    actions.map(([action,label,key])=>`<button type="button" role="menuitem" data-nav-menu="${action}" ${action==='delete'?'class="danger-action"':''}>${label}<small>${key}</small></button>`).join('');
  menu.hidden=false;menu.style.left=Math.max(8,Math.min(x,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-menu.offsetHeight-8))+'px';
  menu.querySelector('button').focus({preventScroll:true});
}
function cancelNavigationRename() {
  const edit=navigationUI.editing;if(!edit)return;
  navigationUI.editing=null;const row=navigationElement(edit.kind,edit.id);if(row)delete row.dataset.signature;
  renderNavigation();row?.querySelector('.navigation-open').focus({preventScroll:true});
}
function beginNavigationRename(kind,id) {
  closeNavigationMenu();cancelNavigationRename();
  const item=navigationItem(kind,id);if(!item)return;
  if(kind==='conversation')expandNavigation(item.project_id,true);
  const row=navigationElement(kind,id);if(!row)return;
  const input=document.createElement('input');input.className='navigation-inline-name';input.maxLength=120;input.value=item.name||item.title;input.setAttribute('aria-label',kind==='project'?'项目名称':'对话名称');
  navigationUI.editing={kind,id,input,saving:false};row.classList.add('is-editing');row.draggable=false;
  row.querySelector('.navigation-label').replaceWith(input);input.focus();input.select();
  input.addEventListener('click',event=>event.stopPropagation());
  input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();event.stopPropagation();commitNavigationRename().catch(error);}else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancelNavigationRename();}});
  input.addEventListener('blur',()=>{if(navigationUI.editing?.input===input&&!navigationUI.editing.saving)commitNavigationRename().catch(error);});
}
async function commitNavigationRename() {
  const edit=navigationUI.editing;if(!edit||edit.saving)return;
  const name=edit.input.value.trim();
  if(!name){edit.input.setCustomValidity('名称不能为空');edit.input.reportValidity();edit.input.focus();return;}
  const item=navigationItem(edit.kind,edit.id);if(name===(item.name||item.title)){cancelNavigationRename();return;}
  edit.saving=true;edit.input.disabled=true;
  try{
    await navigationMutation(`/api/navigation/${edit.kind}/${edit.id}`,{name});
    if(edit.kind==='project'){item.name=name;if(state.project?.id===edit.id){state.project.name=name;$('projectTitle').textContent=name;}}
    else {item.title=name;const active=conversationUI.items.find(row=>row.id===edit.id);if(active)active.title=name;if(state.conversation===edit.id){state.conversationConfig.title=name;$('conversationTitle').textContent=name;}}
    cancelNavigationRename();setArtifactFolderProjects(navigationUI.projects);
    await refreshNavigation().catch(error);refreshArtifacts().catch(error);toast('名称已保存');
  }catch(err){edit.saving=false;edit.input.disabled=false;edit.input.focus();throw err;}
}
function resetEmptyWorkspace() {
  ++conversationUI.token;clearTimeout(conversationUI.draftTimer);clearTimeout(readingTimer);conversationUI.restoring=false;
  state.conversation=null;state.conversationConfig=null;state.reading=null;state.readPromise=null;state.selected=new Set();state.learningScope=null;
  applyLearningGoalFocus(null);
  $('prompt').value='';$('conversationTitle').textContent='尚未创建对话';$('messages').innerHTML='<div class="empty-state"><div class="empty-symbol">✦</div><h3>在项目里新建一段对话</h3><p>点击侧边栏的「＋ 新建对话」。资料和成果仍保存在项目中。</p></div>';
  $('lessonFeedbackNotice').hidden=true;renderSourceUI();setConversationLoading(false);renderConversations();
}
async function requestNavigationDelete(kind,id) {
  closeNavigationMenu();
  const impact=await api(`/api/navigation/${kind}/${id}/impact`),dialog=$('navigationDeleteDialog');
  dialog.dataset.kind=kind;dialog.dataset.item=id;dialog.dataset.project=impact.project_id;
  $('navigationDeleteTitle').textContent=kind==='project'?`移入回收站：${impact.name}`:`删除对话：${impact.name}`;
  $('navigationDeleteDescription').textContent=kind==='project'?'项目会移到回收站，暂时不再显示或供 AI 使用。里面的资料、成果和聊天仍保留，恢复后可以继续。':'将删除这段对话的聊天记录、未发送的草稿和 AI 内部会话。项目中的资料、已生成成果及有效学习画像保留。此操作不能撤销。';
  $('navigationDeleteImpact').textContent=(kind==='project'?`${impact.conversation_count} 个对话 · ${impact.source_count} 份资料 · ${impact.artifact_count} 份成果。`:`${impact.message_count} 条消息。`)+
    (impact.pending_count?` ${impact.pending_count} 项未完成任务会被停止${kind==='conversation'?'并移除任务历史':''}。`:'没有未完成的生成任务。');
  $('confirmNavigationDelete').textContent=kind==='project'?'移入回收站':'删除对话';dialog.showModal();$('cancelNavigationDelete').focus();
}
async function confirmNavigationDelete() {
  const dialog=$('navigationDeleteDialog'),kind=dialog.dataset.kind,id=dialog.dataset.item,projectId=dialog.dataset.project,button=$('confirmNavigationDelete');
  button.disabled=true;
  try{
    if(state.conversation===id||kind==='project'&&state.project?.id===id)await flushConversation();
    const result=await navigationMutation(kind==='project'?`/api/projects/${id}`:`/api/conversations/${id}?project_id=${encodeURIComponent(projectId)}`,null,'DELETE');
    dialog.close();
    if(kind==='project')navigationUI.projects=navigationUI.projects.filter(row=>row.id!==id);
    else {
      const folder=navigationItem('project',projectId);if(folder)folder.conversations=folder.conversations.filter(row=>row.id!==id);
      if(state.project?.id===projectId)conversationUI.items=conversationUI.items.filter(row=>row.id!==id);
      conversationUI.scrolls.delete(id);
    }
    if(kind==='project'&&state.project?.id===id){resetEmptyWorkspace();state.project=null;resetLearningGoals();state.sources=[];state.categories=[];state.sourceSignature=null;conversationUI.items=[];$('projectTitle').textContent='选择或创建一个项目';for(const host of ['jobs','artifacts','exercises'])$(host).replaceChildren();}
    else if(kind==='conversation'&&state.conversation===id)resetEmptyWorkspace();
    await refreshProjects();
    if(kind==='conversation'&&state.project?.id===projectId){const chats=await refreshConversations();if(!state.conversation&&chats.active_conversation_id)await selectConversation(chats.active_conversation_id);await refreshArtifacts();}
    toast(result.note);
  }catch(err){error(err);}finally{button.disabled=false;}
}
async function openProjectRecycle() {
  closeNavigationMenu();const dialog=$('projectRecycleDialog');if(!dialog.open)dialog.showModal();
  const rows=await api('/api/recycle-bin/projects');
  const cleanup=await api('/api/recycle-bin/cleanup');
  $('projectRecycleCleanup').hidden=!cleanup.pending_count;
  $('projectRecycleCleanup').textContent=cleanup.pending_count?`${cleanup.pending_count} 处文件清理或恢复尚未完成。请关闭占用文件后重新打开回收站，软件会重试；已删除项目的记录不会恢复。`:'';
  $('projectRecycleItems').innerHTML=rows.length?rows.map(row=>`<div class="navigation-recycled"><div><strong>${escapeHtml(row.name)}</strong><small>${row.source_count} 份资料 · ${row.artifact_count} 份成果 · ${escapeHtml(new Date(row.removed_at).toLocaleDateString('zh-CN'))}</small></div><div class="recycle-actions"><button type="button" data-restore-project="${row.id}">恢复</button><button type="button" class="secondary danger-action" data-purge-project="${row.id}">彻底删除</button></div></div>`).join(''):'<p>回收站是空的。</p>';
}
async function requestPermanentProjectDelete(id){
  const impact=await api(`/api/recycle-bin/projects/${id}/impact`),dialog=$('projectPurgeDialog');
  dialog.dataset.project=id;dialog.dataset.name=impact.name;
  $('projectPurgeTitle').textContent=`彻底删除：${impact.name}`;
  const bytes=impact.file_bytes,size=bytes<1024?`${bytes} B`:bytes<1024*1024?`${(bytes/1024).toFixed(1)} KB`:`${(bytes/1024/1024).toFixed(1)} MB`;
  $('projectPurgeImpact').textContent=`${impact.conversation_count} 个对话（${impact.message_count} 条消息） · ${impact.source_count} 份资料 · ${impact.artifact_count} 份成果 · ${impact.task_count} 条任务 · ${impact.profile_event_count} 条本项目的学习记录。将删除只有本项目使用的 ${impact.file_count} 个软件内文件，共 ${size}。`;
  $('projectPurgeName').value='';$('confirmProjectPurge').disabled=true;$('projectPurgeStatus').textContent='';
  dialog.showModal();$('projectPurgeName').focus();
}
async function confirmPermanentProjectDelete(){
  const dialog=$('projectPurgeDialog'),button=$('confirmProjectPurge'),cancel=$('cancelProjectPurge');
  if($('projectPurgeName').value!==dialog.dataset.name)return;
  button.disabled=true;cancel.disabled=true;$('projectPurgeName').disabled=true;dialog.dataset.saving='true';
  $('projectPurgeStatus').textContent='正在清理项目记录与软件保存的文件…';
  try{
    const result=await navigationMutation(`/api/recycle-bin/projects/${dialog.dataset.project}`,{confirmation_name:$('projectPurgeName').value},'DELETE');
    dialog.close();await openProjectRecycle();await refreshProjects();toast(result.note);
  }catch(err){$('projectPurgeStatus').textContent=err.message;}
  finally{delete dialog.dataset.saving;cancel.disabled=false;$('projectPurgeName').disabled=false;button.disabled=$('projectPurgeName').value!==dialog.dataset.name;}
}
async function navigationAction(action,target) {
  const {kind,id}=target,item=navigationItem(kind,id);if(!item)return;
  closeNavigationMenu();
  if(action==='rename')return beginNavigationRename(kind,id);
  if(action==='delete')return requestNavigationDelete(kind,id);
  if(action==='pin'){await navigationMutation(`/api/navigation/${kind}/${id}`,{pinned:!item.pinned});await refreshNavigation();return;}
  if(action==='new'){await openNavigationItem('project',kind==='project'?id:item.project_id);return createConversation();}
  return openNavigationItem(kind,id,action==='artifacts'?'artifacts':action==='sources'?'sources':'study');
}
async function finishNavigationDrag(event) {
  const drag=navigationUI.dragging,row=event.target.closest('.navigation-row');
  if(!drag||!row)return;
  event.preventDefault();
  const target=navigationItem(row.dataset.navKind,row.dataset.navId),item=navigationItem(drag.kind,drag.id);
  if(!target||!item||drag.kind!==row.dataset.navKind||(drag.kind==='conversation'&&item.project_id!==target.project_id))return toast('对话只能在所属项目内排序');
  if(!!item.pinned!==!!target.pinned)return toast('请在相同置顶分组内拖动，或先修改置顶状态');
  const projectId=drag.kind==='conversation'?item.project_id:null;
  const rows=orderedNavigation(projectId?navigationItem('project',projectId).conversations:navigationUI.projects).filter(value=>value.id!==drag.id);
  const index=rows.findIndex(value=>value.id===target.id),rect=row.getBoundingClientRect();rows.splice(index+(event.clientY>=rect.top+rect.height/2?1:0),0,item);
  await navigationMutation('/api/navigation/order',{kind:drag.kind,project_id:projectId,ids:rows.map(value=>value.id)});
  navigationUI.preferences.sort='manual';await refreshNavigation();toast('固定顺序已保存');
}
function initializeNavigation() {
  const menu=document.createElement('div');menu.id='navigationContext';menu.className='navigation-context';menu.setAttribute('role','menu');menu.setAttribute('aria-label','项目或对话操作');menu.hidden=true;document.body.append(menu);
  const dialogs=document.createElement('div');dialogs.innerHTML=`<dialog id="navigationDeleteDialog" class="navigation-dialog" aria-labelledby="navigationDeleteTitle"><h2 id="navigationDeleteTitle"></h2><p id="navigationDeleteDescription"></p><div id="navigationDeleteImpact" class="navigation-impact"></div><div class="dialog-actions"><button type="button" id="cancelNavigationDelete">取消</button><button type="button" id="confirmNavigationDelete" class="navigation-delete-confirm">删除</button></div></dialog><dialog id="projectRecycleDialog" class="navigation-dialog" aria-labelledby="projectRecycleTitle"><h2 id="projectRecycleTitle">项目回收站</h2><p>恢复会找回项目资料、成果和聊天。被停止的任务不会自动重启，可到成果文档区重新发起。</p><div id="projectRecycleItems"></div><div class="dialog-actions"><button type="button" id="closeProjectRecycle">关闭</button></div></dialog>`;document.body.append(...dialogs.children);
  const cleanupNote=document.createElement('p');cleanupNote.id='projectRecycleCleanup';cleanupNote.hidden=true;cleanupNote.setAttribute('role','status');$('projectRecycleItems').before(cleanupNote);
  const purgeDialog=document.createElement('dialog');purgeDialog.id='projectPurgeDialog';purgeDialog.className='navigation-dialog';purgeDialog.setAttribute('aria-labelledby','projectPurgeTitle');
  purgeDialog.innerHTML='<h2 id="projectPurgeTitle">彻底删除项目</h2><p>项目、对话、任务、成果和来自本项目的学习证据将永久清理，无法从回收站恢复。你原来放在软件外的文件、其他项目仍使用的文件，以及单独填写的跨项目自评会保留。</p><div id="projectPurgeImpact" class="navigation-impact"></div><label for="projectPurgeName">输入项目完整名称确认</label><input id="projectPurgeName" type="text" autocomplete="off"><p id="projectPurgeStatus" role="status" aria-live="polite"></p><div class="dialog-actions"><button id="cancelProjectPurge" type="button">取消</button><button id="confirmProjectPurge" type="button" class="navigation-delete-confirm" disabled>永久删除项目</button></div>';document.body.append(purgeDialog);
  $('projectPurgeName').oninput=()=>{$('confirmProjectPurge').disabled=$('projectPurgeName').value!==purgeDialog.dataset.name;};
  $('cancelProjectPurge').onclick=()=>purgeDialog.close();$('confirmProjectPurge').onclick=confirmPermanentProjectDelete;
  purgeDialog.addEventListener('cancel',event=>{if(purgeDialog.dataset.saving)event.preventDefault();});
  $('cancelNavigationDelete').onclick=()=>$('navigationDeleteDialog').close();$('confirmNavigationDelete').onclick=confirmNavigationDelete;
  $('closeProjectRecycle').onclick=()=>$('projectRecycleDialog').close();$('openProjectRecycle').onclick=()=>openProjectRecycle().catch(error);
  $('projectRecycleItems').onclick=async event=>{const button=event.target.closest('[data-restore-project],[data-purge-project]');if(!button)return;button.disabled=true;try{if(button.dataset.purgeProject){await requestPermanentProjectDelete(button.dataset.purgeProject);return;}await navigationMutation(`/api/projects/${button.dataset.restoreProject}/restore`,{},'POST');await refreshProjects();await openProjectRecycle();toast('项目已恢复，任务不会自动重启');}catch(err){error(err);}finally{button.disabled=false;}};
  $('navigationSearch').oninput=renderNavigation;
  $('navigationSort').onchange=()=>{navigationUI.preferences.sort=$('navigationSort').value;renderNavigation();saveNavigationPreferences();};
  $('projects').onclick=event=>{if(event.target.closest('input'))return;const action=event.target.closest('[data-nav-action]');if(!action)return;const row=action.closest('.navigation-row');if(!row){if(action.dataset.navAction==='new')navigationAction('new',{kind:'project',id:action.dataset.project}).catch(error);return;}
    const {navKind:kind,navId:id}=row.dataset;
    if(action.dataset.navAction==='expand'){expandNavigation(id,!navigationUI.expanded.has(id));return;}
    if(action.dataset.navAction==='menu'){const rect=action.getBoundingClientRect();openNavigationMenu(kind,id,rect.right,rect.bottom);return;}
    openNavigationItem(kind,id).catch(error);
  };
  $('projects').oncontextmenu=event=>{if(event.target.closest('input'))return;const row=event.target.closest('.navigation-row');if(!row)return;event.preventDefault();openNavigationMenu(row.dataset.navKind,row.dataset.navId,event.clientX,event.clientY);};
  menu.onclick=event=>{const button=event.target.closest('[data-nav-menu]');if(button&&navigationUI.menuTarget)navigationAction(button.dataset.navMenu,{...navigationUI.menuTarget}).catch(error);};
  menu.onkeydown=event=>{const items=[...menu.querySelectorAll('button')],index=items.indexOf(document.activeElement);let next;if(event.key==='ArrowDown')next=(index+1)%items.length;else if(event.key==='ArrowUp')next=(index+items.length-1)%items.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=items.length-1;else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeNavigationMenu(true);}if(next!==undefined){event.preventDefault();items[next].focus();}};
  document.addEventListener('pointerdown',event=>{if(!menu.hidden&&!menu.contains(event.target))closeNavigationMenu();},true);
  window.addEventListener('resize',()=>closeNavigationMenu());
  $('projects').addEventListener('scroll',()=>closeNavigationMenu(),{passive:true});
  $('projects').ondragstart=event=>{const row=event.target.closest('.navigation-row');if(!row||!row.draggable){event.preventDefault();return;}navigationUI.dragging={kind:row.dataset.navKind,id:row.dataset.navId};row.classList.add('dragging');event.dataTransfer.setData('application/x-studyforge-navigation',JSON.stringify(navigationUI.dragging));event.dataTransfer.effectAllowed='move';};
  $('projects').ondragover=event=>{if(!navigationUI.dragging)return;const row=event.target.closest('.navigation-row');if(!row)return;event.preventDefault();document.querySelectorAll('.drag-target').forEach(node=>node.classList.remove('drag-target'));row.classList.add('drag-target');row.dataset.placement=event.clientY<row.getBoundingClientRect().top+row.offsetHeight/2?'before':'after';};
  $('projects').ondrop=event=>{finishNavigationDrag(event).catch(error).finally(()=>{navigationUI.dragging=null;document.querySelectorAll('.drag-target,.dragging').forEach(node=>node.classList.remove('drag-target','dragging'));});};
  $('projects').ondragend=()=>{navigationUI.dragging=null;document.querySelectorAll('.drag-target,.dragging').forEach(node=>node.classList.remove('drag-target','dragging'));};
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented||event.isComposing)return;
    const target=event.target instanceof Element?event.target:document.activeElement;
    const editing=target?.closest('input,textarea,select,[contenteditable=true]');
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='p'&&!document.querySelector('dialog[open]')){event.preventDefault();restoreConversationLayout();if(studioPreferences.ui_focus)$('toggleFocus').click();$('navigationSearch').focus();$('navigationSearch').select();return;}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='n'&&!document.querySelector('dialog[open]')){event.preventDefault();if(event.shiftKey){restoreConversationLayout();if(studioPreferences.ui_focus)$('toggleFocus').click();$('newProject').click();}else createConversation().catch(error);return;}
    if(editing)return;
    const row=target?.closest('.navigation-row');if(!row)return;
    const {navKind:kind,navId:id}=row.dataset;
    if(event.key==='F2'){event.preventDefault();beginNavigationRename(kind,id);}
    else if(event.key==='Delete'){event.preventDefault();requestNavigationDelete(kind,id).catch(error);}
    else if(event.key==='F10'&&event.shiftKey){event.preventDefault();const rect=row.getBoundingClientRect();openNavigationMenu(kind,id,rect.right,rect.bottom);}
    else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const visible=[...$('projects').querySelectorAll('.navigation-open')].filter(node=>node.getClientRects().length);const index=visible.indexOf(row.querySelector('.navigation-open'));visible[Math.max(0,Math.min(visible.length-1,index+(event.key==='ArrowDown'?1:-1)))]?.focus();}
    else if(event.key==='ArrowRight'&&kind==='project'){event.preventDefault();expandNavigation(id,true);}
    else if(event.key==='ArrowLeft'){event.preventDefault();if(kind==='project')expandNavigation(id,false);else navigationElement('project',row.dataset.navProject)?.querySelector('.navigation-open').focus();}
  },true);
  $('renameConversation').hidden=true;$('deleteConversation').hidden=true;
  const more=document.createElement('button');more.id='conversationMore';more.type='button';more.textContent='⋯';more.setAttribute('aria-label','管理当前对话');more.title='管理当前对话';$('conversationTitle').after(more);
  more.onclick=()=>{const rect=more.getBoundingClientRect();if(state.conversation)openNavigationMenu('conversation',state.conversation,rect.right,rect.bottom);};
}
