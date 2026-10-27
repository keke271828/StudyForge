/* Project libraries are shared; messages, selection and drafts belong to a chat. */
const conversationUI = {items: [], token: 0, draftTimer: null, restoring: false, scrolls:new Map(),anchors:new Map()};
let conversationSave = Promise.resolve();

function setConversationLoading(loading) {
  const waiting = loading || !state.ready || state.projectLoading;
  $('openModeGuide').disabled = waiting || !state.conversation;
  document.querySelectorAll('[data-mode-guide-select]').forEach(button => { button.disabled = waiting || !state.conversation; });
  for (const id of ['provider','studyModel','reasoningEffort','reloadStudyModels','learningMode','explanationStyle','outputLanguage','reviewMode','sendMessage','generate','submitHomework','renameConversation','deleteConversation','newConversation','selectAllSources','clearSources','showKnowledge','showReadingNotes']) {
    $(id).disabled = waiting || (id!=='newConversation' && !state.conversation) || (id==='sendMessage'&&liveChats.get(state.conversation)?.cancelRequested) || (id==='generate'&&generationLaunches.has(state.conversation));
  }
  const live=liveChats.get(state.conversation);
  $('sendMessage').textContent=live?.cancelRequested?'正在停止…':live?'■ 停止回复':'发送 →';
  $('sendMessage').title=live?'停止当前对话的回复；其他对话与生成任务继续运行':'发送给当前学习导师';
  $('prompt').readOnly = waiting || !state.conversation;
  $('newConversation').disabled = waiting || !state.project;
  document.querySelectorAll('[data-quick-source]').forEach(input => {
    input.disabled = waiting || !state.conversation || state.sources.find(row => row.id === input.dataset.quickSource)?.status !== 'ready';
  });
  if (!waiting) updateEffortOptions();
  renderReadingStatus();
  window.studyforgeMessageFocus?.changed();
}

function saveConversation(changes, id = state.conversation, projectId = state.project?.id) {
  if (!id || !projectId || conversationUI.restoring) return conversationSave;
  if (id === state.conversation) state.conversationConfig = {...state.conversationConfig, ...changes};
  const payload = {project_id: projectId, ...changes};
  conversationSave = conversationSave.catch(() => {}).then(() =>
    api(`/api/conversations/${id}?include_history=false`, jsonOptions('PUT', payload)));
  conversationSave.catch(err => error(new Error('对话设置尚未保存：' + err.message)));
  return conversationSave;
}

async function flushConversation() {
  clearTimeout(conversationUI.draftTimer);
  if (state.conversation && !conversationUI.restoring) saveConversation({draft: $('prompt').value});
  await conversationSave;
  await window.libraryFlush?.();
}

function renderConversations() {
  syncNavigationConversations();
}

async function refreshConversations() {
  const projectId = state.project?.id;
  if (!projectId) return null;
  const result = await api(`/api/projects/${projectId}/conversations`);
  if (state.project?.id !== projectId) return null;
  conversationUI.items = result.conversations; renderConversations();
  const current = result.conversations.find(row => row.id === state.conversation);
  if (current) $('conversationTitle').textContent = current.title;
  return result;
}

function paintConversation(row) {
  $('conversationTitle').textContent = row.title;
  $('renameConversationForm').hidden = true;
  $('prompt').value = row.draft || '';
  $('messages').querySelectorAll('[data-homework-questionnaire]').forEach(captureCauseDraft);
  window.studyforgeHistoryPages.begin($('messages'),row.id,row);
  window.studyforgeMessageHistory.sync($('messages'),row.messages,item=>makeMessage(item.role,item.content,item.id,state.project?.id,row.id,item.reply_reference),{scope:row.id});
  if (!row.messages.length) {
    $('messages').innerHTML = '<div class="empty-state"><div class="empty-symbol">✦</div><h3>开始这段学习对话</h3><p>默认不选资料。右侧可选项目资料或已生成成果；这里选择的资料和提出的要求只用于本对话。</p></div>';
  }
  state.messageSignature = row.messages.map(item => item.id).join(',');
  attachLiveReply(row);
  installHistoryPager();
  if(!conversationUI.scrolls.has(row.id))$('messages').scrollTop=$('messages').scrollHeight;
  if(homeworkState.projectId===state.project?.id)syncHomework(homeworkState.items,homeworkState.projectId);
  if(conversationUI.scrolls.has(row.id))$('messages').scrollTop=conversationUI.scrolls.get(row.id);
  renderConversations();
}

function installHistoryPager(){window.studyforgeHistoryPages.install($('messages'),()=>loadOlderConversationMessages().catch(error));}
async function loadOlderConversationMessages(){
  const host=$('messages'),pager=window.studyforgeHistoryPages,id=state.conversation,projectId=state.project?.id,ticket=pager.request(host,{older:true});if(!ticket)return;
  const result=await api(`/api/conversations/${id}/messages?project_id=${encodeURIComponent(projectId)}&${ticket.query}`);
  if(id!==state.conversation||projectId!==state.project?.id||conversationUI.restoring)return;
  const oldHeight=host.scrollHeight,oldScroll=host.scrollTop,rows=pager.apply(host,result,ticket);if(!rows)return;
  const preserve=[...host.querySelectorAll('.lesson-questionnaire,[data-homework-questionnaire]')],live=liveChats.get(id);
  if(live&&!live.finished){if(live.output?.parentElement?.parentNode===host)preserve.push(live.output.parentElement);if(live.userNode?.parentNode===host&&!rows.some(row=>row.role==='user'&&row.content===live.text&&!live.priorMessageIds?.has(row.id)))preserve.push(live.userNode);}
  window.studyforgeMessageHistory.sync(host,rows,row=>makeMessage(row.role,row.content,row.id,projectId,id,row.reply_reference),{scope:id,preserve});installHistoryPager();
  host.scrollTop=oldScroll+host.scrollHeight-oldHeight;conversationUI.anchors.set(id,pager.state(host).oldest);
}
async function refreshConversationMessages({force=false}={}) {
  const id = state.conversation, projectId = state.project?.id;
  if (!id || conversationUI.restoring) return;
  const request=conversationUI.messagesRequest=(conversationUI.messagesRequest||0)+1;
  const pager=window.studyforgeHistoryPages,ticket=pager.request($('messages'),{force});
  const result = await api(`/api/conversations/${id}/messages?project_id=${encodeURIComponent(projectId)}${ticket?'&'+ticket.query:''}`);
  if (request!==conversationUI.messagesRequest||id !== state.conversation || projectId !== state.project?.id || conversationUI.restoring) return;
  if(ticket){const rows=pager.apply($('messages'),result,ticket);if(!rows)return;result.messages=rows;}
  installHistoryPager();
  const signature = result.messages.map(item => item.id).join(',');
  if (window.studyforgeMessageHistory.matches($('messages'),result.messages,id)) return;
  const host = $('messages'), nearBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 80;
  const scroll = host.scrollTop, cards = [...host.querySelectorAll('.lesson-questionnaire,[data-homework-questionnaire]')];
  host.querySelectorAll('[data-homework-questionnaire]').forEach(captureCauseDraft);
  const live=liveChats.get(id);
  if(live&&!live.finished){
    if(live.output?.parentElement?.parentNode===host)cards.push(live.output.parentElement);
    const saved=result.messages.some(item=>item.role==='user'&&item.content===live.text&&!live.priorMessageIds?.has(item.id));
    if(!saved&&live.userNode?.parentNode===host)cards.splice(0,0,live.userNode);
  }
  window.studyforgeMessageHistory.sync(host,result.messages,item=>makeMessage(item.role,item.content,item.id,projectId,id,item.reply_reference),{scope:id,preserve:cards});
  if(live&&!live.finished)attachLiveReply({id,messages:result.messages});
  state.messageSignature = signature;
  installHistoryPager();
  if (lessonFeedbackState.projectId === projectId) syncLessonFeedback(lessonFeedbackState.items, projectId);
  if(homeworkState.projectId===projectId)syncHomework(homeworkState.items,projectId);
  host.scrollTop=nearBottom?host.scrollHeight:scroll;
}

async function selectConversation(id, {refresh = false} = {}) {
  if (!refresh && id === state.conversation) { showView('study'); return; }
  closeReadingNotes(true);
  const projectId = state.project?.id, token = ++conversationUI.token;
  if(state.conversation)conversationUI.scrolls.set(state.conversation,$('messages').scrollTop);
  await flushConversation();
  if (token !== conversationUI.token || projectId !== state.project?.id) return;
  clearTimeout(readingTimer);
  conversationUI.restoring = true;
  if($('agentApprovalRequests')){$('agentApprovalRequests').hidden=true;$('agentApprovalRequests').replaceChildren();$('agentApprovalRequests').dataset.identity='';}
  setConversationLoading(true);
  try {
    const anchor=conversationUI.anchors.get(id);
    const row = await api(`/api/conversations/${id}?project_id=${encodeURIComponent(projectId)}&history_limit=60${anchor?'&history_start='+encodeURIComponent(anchor):''}`);
    if (token !== conversationUI.token || projectId !== state.project?.id) return;
    state.conversation = row.id; state.conversationConfig = row;
    applyLearningGoalFocus(row.learning_goal);
    state.selected = new Set(row.source_ids); state.readPromise = null;
    renderProviderChoices(row.provider);
    applyLearningMode(row.learning_mode, false);
    applyExplanationStyle(row.explanation_style, false);
    applyOutputLanguage(row.output_language, false);
    applyReviewMode(row.review_mode, false);
    renderStudyModels();
    state.learningScope = materialScope(); state.reading = row.reading || null;
    if ($('knowledgeDialog').open) $('knowledgeDialog').close();
    renderSourceUI(); paintConversation(row);
    window.libraryConversationChanged?.(row.id,projectId);
    // Chat restoration does not wait for the remote model catalog or reread sources.
    refreshStudyModels().catch(error);
    $('generationProviderLabel').textContent = serviceName(row.provider) + ' · GENERATE';
    await api(`/api/conversations/${id}/activate?project_id=${encodeURIComponent(projectId)}`, {method:'POST'});
    await refreshConversations();
    if (row.removed_source_ids.length) toast('已恢复聊天；已删除或不可用的资料已移出本对话');
    if (row.reading_notice) toast(row.reading_notice);
    if(token===conversationUI.token&&state.conversation===id&&state.project?.id===projectId)restoreReadingTask(row);
  } finally {
    if (token === conversationUI.token) { conversationUI.restoring = false; setConversationLoading(false); }
  }
}

async function createConversation() {
  await flushConversation();
  const projectId = state.project?.id;
  if (!projectId) return;
  const row = await api(`/api/projects/${projectId}/conversations`, jsonOptions('POST', {
    provider: $('provider').value, model: currentModel(), model_choice: $('studyModel').value,
    reasoning_effort: currentEffort(), explanation_style: state.settings?.explanation_style || 'clear',
    output_language: state.settings?.output_language || 'zh', review_mode: state.settings?.review_mode || 'express'
  }));
  if (projectId !== state.project?.id) return;
  expandNavigation(projectId,true);
  await refreshConversations(); await selectConversation(row.id); showView('study');
}

function initializeConversations() {
const deleteButton=document.createElement('button');deleteButton.id='deleteConversation';deleteButton.type='button';deleteButton.className='danger-action';deleteButton.textContent='删除对话';
$('renameConversation').after(deleteButton);
deleteButton.onclick=async()=>{
  if(!state.conversation)return;
  try{await requestNavigationDelete('conversation',state.conversation);}catch(failure){error(failure);}
};
setConversationLoading(true);
$('newConversation').onclick = async () => {
  const button = $('newConversation'); button.disabled = true;
  try { await createConversation(); } catch (err) { error(err); } finally { button.disabled = false; }
};
$('renameConversation').onclick = () => {
  if(state.conversation)beginNavigationRename('conversation',state.conversation);
};
$('cancelConversationRename').onclick = () => { $('renameConversationForm').hidden = true; };
$('renameConversationForm').onsubmit = async event => {
  event.preventDefault();
  try {
    await saveConversation({title: $('conversationName').value.trim()});
    await refreshConversations(); $('renameConversationForm').hidden = true;
  } catch (err) { error(err); }
};
$('prompt').addEventListener('input', () => {
  clearTimeout(conversationUI.draftTimer);
  conversationUI.draftTimer = setTimeout(() => saveConversation({draft: $('prompt').value}), 350);
});
}
