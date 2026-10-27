const lessonFeedbackState = { items: [], projectId: null, sections: new Map() };
const lessonDifficultyLabels={terminology:'术语的意思不懂',prerequisites:'缺少基础知识，跟不上这一步',motivation:'计算能看懂，但不知道为什么要这样设式或构造',method_selection:'会照着做，但不知道什么时候该用这个方法',argumentation:'能重复讲解，但自己证明不出来',implementation:'思路没问题，计算或代码出错'};

function lessonFeedbackDraftKey(id) { return 'sfDesktopLessonDraft:'+id; }
function lessonFeedbackDraft(id) {
  try { return JSON.parse(localStorage.getItem(lessonFeedbackDraftKey(id))||'{}')||{}; } catch { return {}; }
}
function saveLessonFeedbackDraft(form) {
  const data=new FormData(form);
  const previous=lessonFeedbackDraft(form.dataset.questionnaireId),select=form.querySelector('[data-feedback-focus]');
  try { localStorage.setItem(lessonFeedbackDraftKey(form.dataset.questionnaireId),JSON.stringify({
    difficulties:data.getAll('difficulty'),other_text:String(data.get('other_text')||''),
    focus_section_id:select.disabled?(previous.focus_section_id||''):String(data.get('focus_section_id')||''),
    focus_selection:select.disabled?previous.focus_selection:form.querySelector('[data-feedback-passage]')?.passageControl?.value()})); } catch {}
}
function paintLessonFocus(card, item, initial=false) {
  const select=card.querySelector('[data-feedback-focus]'),info=card.querySelector('[data-feedback-focus-info]');
  if(!select)return;
  const sections=lessonFeedbackState.sections.get(item.id),draft=lessonFeedbackDraft(item.id);
  const current=initial?(draft.focus_section_id||''):select.value;
  if(sections){
    select.innerHTML='<option value="">不指定章节，按我的补充定位</option>'+sections.items.map(section=>
      `<option value="${escapeHtml(section.id)}">${escapeHtml(section.path.join(' → '))}</option>`).join('');
    select.value=sections.items.some(section=>section.id===current)?current:'';
    select.disabled=false;card.querySelector('[data-feedback-load-focus]').hidden=true;
    const active=sections.items.find(section=>section.id===select.value);
    info.textContent=active?active.preview+(active.chars>7000?'\n本节较长，可查看后续原句并选中具体卡住的一步。':''):
      current?'上次选择的位置已变化，请重新选择章节；其他填写内容仍保留。':
      sections.omitted?`列出前 ${sections.items.length} 个标题，另有 ${sections.omitted} 个；也可直接在其他补充中粘贴卡住的句子。`:
      sections.items.length?'不用再次上传文档。选择章节后，导师会同时拿到这段历史讲解和原资料。':'这份记录没有可用正文，请在其他补充中填写具体片段。';
  }else{select.disabled=true;info.textContent='可列出这份讲解的实际标题；不会调用 AI，也不会重新解析资料。';}
  const host=card.querySelector('[data-feedback-passage]');
  if(host){
    if(!host.passageControl)host.passageControl=window.studyforgeLessonPassage.create(host,{
      getId:()=>item.id,getSection:()=>select.value,api,isActive:()=>card.dataset.conversation===state.conversation,
      onChange:()=>saveLessonFeedbackDraft(card.querySelector('form'))});
    host.passageControl.setSection(select.value,initial&&sections?(select.value&&select.value===draft.focus_section_id?draft.focus_selection||null:null):undefined);
  }
}
async function loadLessonFocus(id) {
  const card=document.querySelector(`[data-lesson-feedback="${id}"]`);
  if(!card)return;
  const sections=await api(`/api/lesson-feedback/${id}/sections`);
  if(!card.isConnected||card.dataset.conversation!==state.conversation)return;
  lessonFeedbackState.sections.set(id,sections);
  if(lessonFeedbackState.sections.size>30)lessonFeedbackState.sections.delete(lessonFeedbackState.sections.keys().next().value);
  paintLessonFocus(card,{id},true);
}

function renderLessonQuestionnaire(item) {
  const host = $('messages');
  let card = host.querySelector(`[data-lesson-feedback="${item.id}"]`);
  const signature = JSON.stringify([item.status, item.reply_status, item.error, item.focus,item.understanding_check]);
  if (card?.dataset.signature === signature) {
    for(const submit of card.querySelectorAll('button[type="submit"]'))submit.disabled = !item.ready||card.querySelector('form')?.dataset.feedbackPending==='true';
    const waiting = card.querySelector('[data-feedback-waiting]');
    if (waiting) waiting.hidden = item.ready;
    return card;
  }
  if (!card) {
    card = document.createElement('section'); card.className = 'lesson-questionnaire';
    card.dataset.lessonFeedback = item.id; host.append(card);
  }
  card.dataset.signature = signature; card.dataset.conversation = item.conversation_id;
  const heading = `<div class="questionnaire-heading"><span class="eyebrow">${item.kind==='content_check'?'讲解核对':'理解反馈'} · 可选</span><h3>${escapeHtml(item.title)}</h3></div>`;
  if (item.status === 'pending') {
    card.innerHTML = heading + `<p class="small-note">${item.kind==='content_check'?'请写出可能讲错的章节或句子。导师会先对照资料检查；你的质疑不会被记成学习弱项，也不会因此出题或打分。':'哪里卡住了，或讲解哪里可能有误？可以多选，不打分，也不强制练习。指出讲解可能有错，不会被记成你没学会。只有你明确勾选的理解困难，才会作为学习记录。'}</p>
      <form class="questionnaire-form" data-questionnaire-id="${item.id}" data-content-only="${item.kind==='content_check'}">
      <details class="questionnaire-focus"><summary>卡在哪一节或哪句话？（可选）</summary><label>讲解中的位置<select name="focus_section_id" data-feedback-focus></select></label><button type="button" data-feedback-load-focus="${item.id}">列出这份讲解的章节</button><p class="small-note" data-feedback-focus-info></p><div data-feedback-passage></div></details>
      ${item.kind==='content_check'?'<p class="small-note">这是一次新的内容核对，旧反馈保留。这里只核对讲解，不据此评估你的能力。</p><input type="hidden" name="difficulty" value="content_accuracy">':`<fieldset><legend>我希望导师帮我处理的事</legend><div class="questionnaire-options">${item.options.map(option => `<label><input type="checkbox" name="difficulty" value="${escapeHtml(option.id)}"><span>${escapeHtml(lessonDifficultyLabels[option.id]||option.label)}</span></label>`).join('')}</div></fieldset>`}
      <label class="questionnaire-other">其他补充<textarea name="other_text" maxlength="3000" placeholder="写下卡点或你怀疑有误的句子，也可以说明应核对的条件、页码或反例。">${escapeHtml(item.other_text)}</textarea></label>
      <p class="small-note" data-feedback-waiting ${item.ready ? 'hidden' : ''}>这份讲解还在生成，可以先保存反馈。讲解完成后就能请导师补讲，不必等配套习题。</p>
      <div class="questionnaire-actions"><button type="submit" class="secondary" data-submit-feedback ${item.ready ? '' : 'disabled'}>提交并请导师回应</button><button type="submit" data-feedback-action="save" ${item.ready ? '' : 'disabled'}>仅保存反馈</button><button type="button" data-feedback-skip="${item.id}">暂时跳过</button></div></form>`;
    const draft=lessonFeedbackDraft(item.id),form=card.querySelector('form');
    for(const box of form.querySelectorAll('[name="difficulty"]'))box.checked=Array.isArray(draft.difficulties)&&draft.difficulties.includes(box.value);
    if(typeof draft.other_text==='string')form.querySelector('[name="other_text"]').value=draft.other_text;
    paintLessonFocus(card,item,true);
  } else if (item.status === 'skipped') {
    card.innerHTML = heading + '<p class="small-note">已跳过。之后有不明白的地方，随时告诉导师。</p>';
  } else {
    const labels = item.options.filter(option => item.difficulties.includes(option.id)).map(option => option.label);
    const status = item.reply_status === 'completed' ? '补讲已完成，可以继续追问。' : item.reply_status === 'running' ? '导师正在补讲…' : '反馈已保存，等待导师补讲。';
    card.innerHTML = heading + `<p>你的反馈：${escapeHtml(labels.join('；') || '其他补充')}</p>${item.other_text ? `<blockquote>${escapeHtml(item.other_text)}</blockquote>` : ''}
      ${item.content_check?'<p class="small-note">已请求先核对讲解；内容质疑不记成知识薄弱项，未据此评分。</p>':''}
      ${item.focus?`<p class="small-note">这次要检查或补讲的位置：${escapeHtml(item.focus.path.join(' → '))}；只关注你选中的这一处，不代表整份资料都没学会。</p>`:''}
      ${item.focus?.selection?`<p class="small-note">已选定本节第 ${item.focus.selection.start+1}–${item.focus.selection.end} 字符；原句单独交给导师，不作为你的作答记录。</p>`:''}
      <p class="small-note" role="status">${escapeHtml(item.error || status)}</p>
      ${['pending', 'failed'].includes(item.reply_status) ? `<button type="button" class="secondary" data-feedback-retry="${item.id}">${item.content_check?'请导师核对':'请导师补讲'}${item.reply_status === 'failed' ? ' · 重试' : ''}</button>` : ''}`;
    if(item.reply_status==='completed'&&item.kind!=='content_check'){
      const check=item.understanding_check,active=check&&['queued','running','pausing','paused'].includes(check.status);
      card.innerHTML+=`<div class="questionnaire-actions"><button type="button" class="secondary" data-feedback-check="${item.id}">${check?.status==='completed'&&check.exercise_set_id?'查看这道检查题':active?'检查题生成中 · 查看任务':check?.status==='failed'?'重试 1 题理解检查':'用 1 道题检查是否听懂'}</button></div><p class="small-note">这是可选的：用一道新题试试刚才是否听懂。不点击就不会出题；提交作答后才能看解析。</p>`;
    }
  }
  if(item.status!=='pending'&&item.ready)card.innerHTML+=`<div class="questionnaire-actions"><button type="button" class="secondary" data-feedback-content-check="${item.id}">对讲解还有新疑问</button></div><p class="small-note">旧反馈会保留。你可以另选一句话、写下新问题，提交后再请导师检查。</p>`;
  return card;
}

async function startLessonContentCheck(id) {
  const project=state.project?.id,conversation=state.conversation;
  const item=lessonFeedbackState.items.find(row=>row.id===id)||
    (await api(`/api/lesson-feedback/${id}/dialogue`)).questionnaire;
  if(item.project_id!==project||item.conversation_id!==conversation)return toast('请回到这份讲解的原项目、原对话后再核对');
  const created=await api(`/api/lesson-feedback/${id}/content-check`,jsonOptions('POST',{project_id:project,conversation_id:conversation}));
  if(state.project?.id!==project||state.conversation!==conversation)return;
  await openLessonFeedback(created.id);
  if(state.project?.id===project){const rows=await api(`/api/projects/${project}/lesson-feedback`);syncLessonFeedback(rows,project);}
}

function syncLessonFeedback(items, projectId) {
  if (state.project?.id !== projectId) return;
  if(lessonFeedbackState.projectId!==projectId)lessonFeedbackState.sections.clear();
  lessonFeedbackState.items = items; lessonFeedbackState.projectId = projectId;
  const current = items.find(item => item.conversation_id === state.conversation && item.status !== 'skipped');
  if (current) renderLessonQuestionnaire(current);
  const byId=new Map(items.map(item=>[item.id,item]));
  for(const card of $('messages').querySelectorAll('[data-lesson-feedback]')){
    const item=byId.get(card.dataset.lessonFeedback);if(item?.conversation_id===state.conversation)renderLessonQuestionnaire(item);
  }
  const unresolved = items.filter(item => item.status === 'pending' || (item.status === 'submitted' && item.reply_status !== 'completed'));
  const inbox = $('lessonFeedbackNotice');
  const next = unresolved.find(item => !document.querySelector(`[data-lesson-feedback="${item.id}"]`));
  inbox.hidden = !next;
  if (next) inbox.innerHTML = `<span>《${escapeHtml(next.title)}》${next.status === 'pending' ? '有一份可选理解问卷' : '有待继续的补讲'}</span><button type="button" data-feedback-open="${next.id}">查看</button>`;
}

async function openLessonFeedback(id, jobId) {
  const projectId = state.project?.id;
  const item = jobId ? await api(`/api/lesson-feedback/by-job/${jobId}`) : { id };
  const dialogue = await api(`/api/lesson-feedback/${item.id}/dialogue`);
  if (state.project?.id !== projectId) return;
  const feedback = dialogue.questionnaire;
  await selectConversation(feedback.conversation_id, {refresh:true});
  if (state.project?.id !== projectId || state.conversation !== feedback.conversation_id) return;
  lessonFeedbackState.sections.set(feedback.id,dialogue.sections||{items:[],omitted:0});
  if(lessonFeedbackState.sections.size>30)lessonFeedbackState.sections.delete(lessonFeedbackState.sections.keys().next().value);
  // The supplement uses the lecture's captured preferences on the server;
  // opening an old questionnaire must preserve the student's newer choices.
  if (dialogue.reading && [...state.selected].sort().join(',') === [...feedback.source_ids].sort().join(',')) {
    state.reading = dialogue.reading; renderReadingStatus();
  }
  const card = renderLessonQuestionnaire(feedback); showView('study');
  if(feedback.status==='pending')paintLessonFocus(card,feedback,true);
  // An explicit navigation takes precedence over the viewport anchor captured
  // before showView/layout changed. Do not let its pending frame undo this jump.
  conversationDisplay.viewportRevision++;
  const host=$('messages');
  host.scrollTo({top:host.scrollTop+card.getBoundingClientRect().top-host.getBoundingClientRect().top-12,behavior:'instant'});
  conversationUI.scrolls.set(feedback.conversation_id,host.scrollTop);
  return feedback;
}

async function requestFeedbackFollowup(id) {
  const item = await openLessonFeedback(id);
  if (!item || isChatBusy(item.conversation_id)) return toast('此对话正在回复；独立生成和其他对话仍可使用');
  const request=captureStudyRequest(),projectId=request.project_id;
  const live={request,text:null,answer:'',status:'导师正在补讲…',output:message('assistant'),finished:false,controller:new AbortController()};
  liveChats.set(request.conversation_id,live);syncWorkControls();
  try {
    await consumeTutorResponse(await fetch(`/api/lesson-feedback/${id}/followup`,{method:'POST',signal:live.controller.signal}),live);
  } catch (failure) {
    live.answer+='\n\n补讲未完成；问卷回答已保留，可以重试。';paintLiveReply(live);
    if(!live.controller.signal.aborted)error(failure);
  } finally {
    live.finished=true;liveChats.delete(request.conversation_id);syncWorkControls();
    if(inCapturedChat(request))await refreshConversationMessages().catch(error);
    if (state.project?.id === projectId) {
      const items = await api(`/api/projects/${projectId}/lesson-feedback`); syncLessonFeedback(items, projectId);
    }
  }
}

document.addEventListener('submit', event => {
  const form = event.target.closest('.questionnaire-form'); if (!form) return;
  event.preventDefault();
  if(form.dataset.feedbackPending==='true')return;
  form.dataset.feedbackPending='true';
  const saveOnly=event.submitter?.dataset.feedbackAction==='save';
  const data = new FormData(form), id = form.dataset.questionnaireId, projectId = state.project.id;
  if(form.dataset.contentOnly==='true'&&!String(data.get('other_text')||'').trim()&&!data.get('focus_section_id')){
    delete form.dataset.feedbackPending;toast('请写下需要核对的问题，或选择章节／原句，再请导师核对');return;
  }
  const buttons=[...form.querySelectorAll('button')];for(const button of buttons)button.disabled=true;
  (async () => {
    const item = await api(`/api/lesson-feedback/${id}/submit`, jsonOptions('POST', {
      difficulties:data.getAll('difficulty'), other_text:String(data.get('other_text') || ''),focus_section_id:String(data.get('focus_section_id')||'')||null,
      focus_selection:form.querySelector('[data-feedback-passage]')?.passageControl?.value()||null}));
    try { localStorage.removeItem(lessonFeedbackDraftKey(id)); } catch {}
    if (state.project?.id !== projectId) return;
    renderLessonQuestionnaire(item);
    if(saveOnly)toast('理解反馈已保存；需要时可再请导师补讲。');
    else await requestFeedbackFollowup(id);
  })().catch(error).finally(() => { delete form.dataset.feedbackPending;if(form.isConnected)for(const button of buttons)button.disabled=false; });
});

for(const name of ['input','change'])document.addEventListener(name,event=>{
  const form=event.target.closest('.questionnaire-form');if(!form)return;
  if(event.target.matches('[data-feedback-focus]')){
    const item={id:form.dataset.questionnaireId};paintLessonFocus(form.closest('.lesson-questionnaire'),item);
  }
  saveLessonFeedbackDraft(form);
});

document.addEventListener('click', event => {
  const button = event.target.closest('[data-feedback-open],[data-feedback-skip],[data-feedback-retry],[data-feedback-load-focus],[data-feedback-check],[data-feedback-content-check]');
  if (!button) return;
  button.disabled = true;
  (async () => {
    if(button.dataset.feedbackContentCheck)await startLessonContentCheck(button.dataset.feedbackContentCheck);
    else if(button.dataset.feedbackCheck){
      const id=button.dataset.feedbackCheck,item=lessonFeedbackState.items.find(row=>row.id===id);
      if(!item||item.project_id!==state.project?.id||item.conversation_id!==state.conversation)return toast('请回到这份补讲的原对话后再选择检查');
      const check=item.understanding_check;
      if(check?.status==='completed'&&check.exercise_set_id){showView('exercises');await refreshExercises();await openSet(check.exercise_set_id);return;}
      if(check&&['queued','running','pausing','paused'].includes(check.status)){showView('artifacts');await refreshArtifacts();return;}
      const capturedProject=item.project_id,capturedChat=item.conversation_id;
        await api(`/api/lesson-feedback/${id}/check`,jsonOptions('POST',{project_id:capturedProject,conversation_id:capturedChat,
          parallel:!!($('generationParallel')?.checked??state.settings?.generation_parallel)}));
      if(state.project?.id!==capturedProject||state.conversation!==capturedChat)return;
      const rows=await api(`/api/projects/${capturedProject}/lesson-feedback`);syncLessonFeedback(rows,capturedProject);
      toast('已安排本次补讲的1题检查，可以继续聊天；完成后可在这里查看或到练习区作答。');await refreshArtifacts();
    }
    else if (button.dataset.feedbackOpen) await openLessonFeedback(button.dataset.feedbackOpen);
    else if(button.dataset.feedbackLoadFocus)await loadLessonFocus(button.dataset.feedbackLoadFocus);
    else if (button.dataset.feedbackRetry) await requestFeedbackFollowup(button.dataset.feedbackRetry);
    else {
      const item = await api(`/api/lesson-feedback/${button.dataset.feedbackSkip}/submit`, jsonOptions('POST', {skip:true}));
      if (item.project_id === state.project?.id) renderLessonQuestionnaire(item);
      toast('已跳过，不进行补讲或评估');
      await refreshArtifacts();
    }
  })().catch(error).finally(() => { if (button.isConnected) button.disabled = false; });
});
