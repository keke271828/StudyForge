/* A submission belongs to one worksheet and one chat, independently of tutor streaming. */
const homeworkState={items:[],projectId:null,sets:[],scope:null,token:0,drafts:new Map(),causeDrafts:new Map(),causeTimers:new Map(),pendingDrafts:new Map(),draftChains:new Map(),busy:false,activeResult:null};
const homeworkLabels={accepted:'作答已保存',grading:'导师批改中',awaiting_causes:'等待错因问卷',awaiting_grade_review:'评分还需确认 · 未定分',clarified:'补讲与导出中',completed:'批改已完成',failed:'批改失败，可重试',cancelled:'批改已取消',source_changed:'原题已变更 · 仅可回看',source_unavailable:'无法确认当时的原题'};
const homeworkExtensions={python:'.py',javascript:'.js',typescript:'.ts',cpp:'.cpp',matlab:'.m',wolfram:'.wl'};

function homeworkLinks(item){
  return [item.solution_artifact&&`<a class="homework-download" href="${escapeHtml(item.solution_artifact.download_url)}" download>原题和参考解析 ↓</a>`,item.feedback_artifact&&`<a class="homework-download" href="${escapeHtml(item.feedback_artifact.download_url)}" download>${item.grading_verification_required?'评分还需确认说明':'批改与错题讲解'} ↓</a>`,(item.solution_artifact||item.feedback_artifact)&&`<button type="button" data-homework-read="${escapeHtml(item.id)}">按题回看</button>`].filter(Boolean).join('')+homeworkRepairAction(item);
}
function homeworkRow(item){
  const retry=item.can_retry?`<button type="button" data-homework-retry="${item.id}">${item.status==='awaiting_grade_review'?'重新检查原作答':item.status==='cancelled'?'继续原批改':'重试批改'}</button>`:'';
  return `<article class="homework-record"><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(homeworkLabels[item.status]||item.status)}${item.score!=null?` · ${item.score} 分`:item.provisional&&!item.grading_verification_required?' · 只看代码得出的反馈，未确定成绩':''}</small><small>来源对话：${escapeHtml(item.conversation_title||'未关联对话')}</small>${item.version_notice?`<p class="small-note" data-homework-version-notice>${escapeHtml(item.version_notice)}</p>`:''}${item.is_regrade?'<small>重新检查评分 · 沿用原作答与已保存条件，不是新增作答</small>':''}</div><div class="homework-links">${homeworkLinks(item)}${item.waiting_for_causes?`<button type="button" data-homework-open="${item.id}">填写错因问卷</button>`:''}${retry}</div></article>`;
}
function syncHomework(items,projectId){
  if(state.project?.id!==projectId)return;
  homeworkState.items=items;homeworkState.projectId=projectId;
  const own=items.filter(x=>x.conversation_id===state.conversation),pending=own.filter(x=>x.waiting_for_causes);
  const notice=$('homeworkNotice');
  if(notice){notice.hidden=!own.length;notice.innerHTML=`<button type="button" data-homework-history>作业反馈 <span>${own.length}</span>${pending.length?` · ${pending.length} 份待填写问卷`:''}</button>${own[0]?homeworkLinks(own[0]):''}`;}
  const host=$('messages');
  host.querySelectorAll('[data-homework-questionnaire]').forEach(card=>{
    if(!pending.some(x=>x.id===card.dataset.homeworkQuestionnaire)){captureCauseDraft(card);card.remove();}
  });
  for(const item of pending)renderCauseQuestionnaire(item);
  const button=$('submitHomework');if(button)button.disabled=state.projectLoading||conversationUI.restoring||!state.conversation;
  if($('homeworkDialog')?.open&&homeworkState.scope?.projectId===projectId){
    $('homeworkHistory').innerHTML=items.map(homeworkRow).join('')||'<p class="small-note">提交后，两份文档和批改进度会保存在这里。</p>';
    const current=items.find(x=>x.id===homeworkState.activeResult);
    if(current)paintHomeworkResult(current);
  }
}
function captureCauseDraft(card){
  const fields=[...card.querySelectorAll('[data-cause-index]')].map(field=>({index:Number(field.dataset.causeIndex),kinds:[...field.querySelectorAll('input:checked')].map(x=>x.value),text:field.querySelector('textarea').value}));
  homeworkState.causeDrafts.set(card.dataset.homeworkQuestionnaire,fields);
}
async function persistCauseDraft(id){
  const draft=homeworkState.pendingDrafts.get(id);if(!draft)return homeworkState.draftChains.get(id);
  clearTimeout(homeworkState.causeTimers.get(id));homeworkState.causeTimers.delete(id);
  const previous=homeworkState.draftChains.get(id)||Promise.resolve();
  const save=previous.catch(()=>{}).then(()=>api(`/api/homework/${id}/draft?project_id=${encodeURIComponent(draft.projectId)}`,jsonOptions('PUT',{responses:draft.responses})));
  homeworkState.draftChains.set(id,save);
  try{await save;if(homeworkState.pendingDrafts.get(id)===draft)homeworkState.pendingDrafts.delete(id);}
  finally{if(homeworkState.draftChains.get(id)===save)homeworkState.draftChains.delete(id);}
}
async function flushHomeworkDrafts(){
  await Promise.all([...homeworkState.pendingDrafts.keys()].map(persistCauseDraft));
  await Promise.all([...homeworkState.draftChains.values()]);
}
function renderCauseQuestionnaire(item){
  let card=$('messages').querySelector(`[data-homework-questionnaire="${item.id}"]`);
  const signature=JSON.stringify([item.title,item.questions,item.options]);
  if(card?.dataset.signature===signature)return card; // Progress updates preserve a half-written questionnaire.
  if(card){captureCauseDraft(card);card.remove();}
  card=document.createElement('section');card.className='homework-questionnaire';card.dataset.homeworkQuestionnaire=item.id;
  card.dataset.signature=signature;
  card.innerHTML=`<span class="eyebrow">有些错因还不清楚，请补充说明</span><h3>${escapeHtml(item.title)}</h3><p>导师已核查评分，但这些题仅凭作答不能确定原因。请回忆当时的思路，可多选或补充；解析文档已经可以下载。</p><div class="homework-links">${homeworkLinks(item)}</div><form>${item.questions.map(q=>`<fieldset data-cause-index="${q.index}"><legend>第 ${q.index+1} 题 · ${escapeHtml(q.topic)}</legend><p class="cause-prompt">${escapeHtml(q.prompt)}</p><details><summary>查看原题和我的作答</summary><div data-cause-question="${q.index}"></div><h4>我的作答</h4><pre>${escapeHtml(q.student_answer)}</pre></details><div class="cause-options">${item.options.map(option=>`<label><input type="checkbox" value="${escapeHtml(option.id)}"><span>${escapeHtml(option.label)}</span></label>`).join('')}</div><label>其他补充 / 当时的思路<textarea maxlength="3000" placeholder="例如：我把面积当成了封闭面体积；或概念会，但把数值抄错了。仍不确定也可以写出尝试过的步骤。"></textarea></label></fieldset>`).join('')}<p class="small-note">你的回答会作为你自己的说明保留。填写后，导师会继续讲解并生成批改文件，不会重新计算原分数。</p><p role="status" class="homework-form-status"></p><button type="submit" class="primary">提交错因并继续批改文档</button></form>`;
  item.questions.forEach(q=>{
    renderLessonText(card.querySelector(`[data-cause-question="${q.index}"]`),q.question);
    const field=card.querySelector(`[data-cause-index="${q.index}"]`),old=field.querySelector('.cause-prompt');
    const prompt=document.createElement('div');prompt.className='cause-prompt';old.replaceWith(prompt);renderLessonText(prompt,q.prompt);
  });
  const drafts=homeworkState.causeDrafts.get(item.id)||item.cause_draft||item.cause_answers;
  for(const entry of drafts){const field=card.querySelector(`[data-cause-index="${entry.index}"]`);if(!field)continue;field.querySelector('textarea').value=entry.text;field.querySelectorAll('input').forEach(x=>x.checked=entry.kinds.includes(x.value));}
  card.addEventListener('input',()=>{
    captureCauseDraft(card);clearTimeout(homeworkState.causeTimers.get(item.id));
    homeworkState.pendingDrafts.set(item.id,{projectId:item.project_id,responses:homeworkState.causeDrafts.get(item.id)});
    homeworkState.causeTimers.set(item.id,setTimeout(async()=>{
      try{await persistCauseDraft(item.id);}
      catch(e){if(card.isConnected&&homeworkState.items.some(x=>x.id===item.id&&x.waiting_for_causes))card.querySelector('[role="status"]').textContent='草稿尚未保存：'+e.message;}
      finally{homeworkState.causeTimers.delete(item.id);}
    },500));
  });
  card.querySelector('form').onsubmit=async event=>{
    event.preventDefault();captureCauseDraft(card);
    clearTimeout(homeworkState.causeTimers.get(item.id));homeworkState.causeTimers.delete(item.id);
    const responses=homeworkState.causeDrafts.get(item.id);
    const status=card.querySelector('[role="status"]'),button=card.querySelector('[type="submit"]');
    if(responses.some(x=>!x.kinds.length&&!x.text.trim())){status.textContent='每道待定位的题，请至少选择一项或补充思路。';return;}
    button.disabled=true;status.textContent='正在保存你的回答…';
    try{
      await persistCauseDraft(item.id);await homeworkState.draftChains.get(item.id);
      const result=await api(`/api/homework/${item.id}/causes?project_id=${encodeURIComponent(item.project_id)}`,jsonOptions('POST',{responses}));
      homeworkState.causeDrafts.delete(item.id);
      await refreshArtifacts();watchOutcomeTask(result.job_id).catch(error);
      toast('错因已保存，导师继续针对性补讲；原评分不会重复计算');
    }catch(e){status.textContent=e.message;error(e);if(button.isConnected)button.disabled=false;}
  };
  $('messages').append(card);return card;
}
async function openHomeworkCauses(id){
  const projectId=state.project?.id,item=homeworkState.items.find(x=>x.id===id)||await api(`/api/homework/${id}?project_id=${encodeURIComponent(projectId)}`);
  if(state.project?.id!==projectId)return;
  if(!item.conversation_id)return toast('这份作业没有关联对话，请在作业记录查看文档');
  if($('homeworkDialog').open)$('homeworkDialog').close();
  if(state.conversation!==item.conversation_id)await selectConversation(item.conversation_id);
  if(state.project?.id!==projectId||state.conversation!==item.conversation_id)return;
  showView('study');syncHomework(homeworkState.items,projectId);
  const card=renderCauseQuestionnaire(item);card.scrollIntoView({block:'nearest',behavior:'smooth'});
}
function captureHomeworkDraft(){
  const scope=homeworkState.scope,host=$('homeworkQuestions'),id=host?.dataset.homeworkSet;
  if(!scope||!id||host.dataset.homeworkProject!==scope.projectId||host.dataset.homeworkConversation!==scope.conversationId)return;
  const answers=[...$('homeworkQuestions').querySelectorAll('[data-homework-answer]')].map(x=>x.value);
  homeworkState.drafts.set(`${scope.conversationId}:${id}`,{answers,confirmed:$('homeworkComplete').checked,...attemptPayload($('homeworkQuestions'))});
}
function paintHomeworkSet(){
  homeworkState.activeResult=null;
  const worksheet=homeworkState.sets.find(x=>x.id===$('homeworkSet').value),host=$('homeworkQuestions');
  host.dataset.homeworkSet=worksheet?.id||'';
  host.dataset.homeworkProject=homeworkState.scope?.projectId||'';
  host.dataset.homeworkConversation=homeworkState.scope?.conversationId||'';
  if(!worksheet){host.innerHTML='<div class="empty-state"><h3>暂无可提交题单</h3><p>可直接请导师出题，或选择“只生成习题”。已有作业的解析和批改在下方记录中。</p></div>';$('homeworkSubmit').disabled=true;$('homeworkAnswerFile').hidden=true;return;}
  const accepted=homeworkState.items.find(x=>x.exercise_set_id===worksheet.id);
  $('homeworkComplete').disabled=false;$('homeworkExtract').disabled=false;
  if(accepted?.current_version_matches===false){homeworkState.activeResult=accepted.id;paintHomeworkResult(accepted);return;}
  const coding=Boolean(worksheet.questions[0]?.language),extension=homeworkExtensions[worksheet.questions[0]?.language];
  host.innerHTML=worksheet.questions.map(q=>`<section class="homework-question"><h3>第 ${q.index+1} 题 · ${escapeHtml(q.topic)}</h3><div data-homework-statement="${q.index}"></div>${q.starter_code?`<details><summary>起始代码</summary><pre>${escapeHtml(q.starter_code)}</pre></details>`:''}<label>${coding?'粘贴作业代码，或从文件读取':'我的作答'}<textarea data-homework-answer="${q.index}" ${coding?'spellcheck="false" class="homework-code"':''} placeholder="${coding?'粘贴对应语言的完整代码':'填写解题步骤和答案；不会的题请明确写出卡点，不必编造答案'}"></textarea></label></section>`).join('');
  if(!coding)host.insertAdjacentHTML('beforeend',attemptControls(worksheet));
  if(worksheet.practice?.version_notice)host.insertAdjacentHTML('afterbegin','<aside class="small-note practice-repair-reference">'+escapeHtml(worksheet.practice.version_notice)+'</aside>');
  worksheet.questions.forEach(q=>renderLessonText(host.querySelector(`[data-homework-statement="${q.index}"]`),q.question));
  if(!coding){const scope=homeworkState.scope;worksheet.questions.forEach(q=>window.studyforgePracticeHints.append(
    host.querySelector(`[data-homework-statement="${q.index}"]`).closest('section'),worksheet,q,
    {api,active:()=>homeworkState.scope===scope&&state.project?.id===scope.projectId&&state.conversation===scope.conversationId&&$('homeworkDialog').open&&$('homeworkSet').value===worksheet.id}));}
  $('homeworkAnswerFile').hidden=false;$('homeworkAnswerFile').value='';$('homeworkAnswerFile').accept=coding?extension:'.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp';
  $('homeworkExtract').textContent=coding?`读取 ${extension} 文件到代码框`:'提取作答到答题框供我核对';
  const draft=homeworkState.drafts.get(`${homeworkState.scope.conversationId}:${worksheet.id}`);
  host.querySelectorAll('[data-homework-answer]').forEach((x,i)=>x.value=draft?.answers[i]||'');$('homeworkComplete').checked=Boolean(draft?.confirmed);
  if(!coding&&draft){host.querySelector('[data-used-notes]').value=draft.used_notes===true?'true':draft.used_notes===false?'false':'unknown';host.querySelector('[data-recovery-mode]').value=draft.recovery_mode||'adaptive';}
  $('homeworkSubmit').disabled=false;$('homeworkResult').innerHTML='';
  if(accepted){homeworkState.activeResult=accepted.id;paintHomeworkResult(accepted);$('homeworkSubmit').disabled=true;}
}
async function openHomework({history=false}={}){
  if(!state.project||!state.conversation)return toast('请先打开一个学习对话');
  captureHomeworkDraft();const token=++homeworkState.token;
  const scope={projectId:state.project.id,conversationId:state.conversation,selection:backgroundAssessmentSelection()};
  homeworkState.scope=scope;$('homeworkDialog').showModal();$('homeworkContext').textContent=`${state.project.name} / ${$('conversationTitle').textContent}`;$('homeworkSubmit').disabled=true;
  delete $('homeworkQuestions').dataset.homeworkSet;
  $('homeworkQuestions').innerHTML='<p role="status">正在读取本项目题单…</p>';
  const [sets,items]=await Promise.all([api(`/api/projects/${scope.projectId}/exercises`),api(`/api/projects/${scope.projectId}/homework`)]);
  if(token!==homeworkState.token||scope.projectId!==state.project?.id||scope.conversationId!==state.conversation||!$('homeworkDialog').open)return;
  homeworkState.sets=sets.filter(s=>s.status==='assigned'&&!s.homework);syncHomework(items,scope.projectId);
  $('homeworkSet').innerHTML=homeworkState.sets.map(s=>`<option value="${s.id}">${escapeHtml(s.title)} · ${s.questions.length} 题${s.questions[0]?.language?' · '+escapeHtml(s.questions[0].language):''}</option>`).join('');
  paintHomeworkSet();if(history)$('homeworkHistory').scrollIntoView({block:'nearest'});
}
async function extractHomeworkFile(){
  const scope=homeworkState.scope,id=$('homeworkSet').value,token=homeworkState.token;
  const file=$('homeworkAnswerFile').files[0],worksheet=homeworkState.sets.find(x=>x.id===id);if(!file||!worksheet)return toast('请先选择作答文件');
  const button=$('homeworkExtract');button.disabled=true;
  try{
    let answers;
    if(worksheet.questions[0].language){
      const ext=homeworkExtensions[worksheet.questions[0].language];if(!file.name.toLowerCase().endsWith(ext))throw Error('请选择本题对应的 '+ext+' 文件');
      if(file.size>2*1024*1024)throw Error('代码文件超过 2 MB');
      const body=new FormData();body.append('file',file);
      const result=await api(`/api/coding/${id}/preview`,{method:'POST',body});answers=[result.code];
      if(result.encoding!=='utf-8')toast(`按 ${result.encoding} 读取代码，请核对字符后提交`);
    }else{
      const body=new FormData();body.append('file',file);Object.entries(scope.selection).forEach(([key,value])=>{if(['provider','model','reasoning_effort'].includes(key)&&value)body.append(key,value);});
      const result=await api(`/api/exercises/${id}/extract-answers`,{method:'POST',body});answers=result.answers;
      if(result.uncertainties?.length)toast(`有 ${result.uncertainties.length} 处识别不确定，请核对再提交`);
    }
    if(token!==homeworkState.token||scope!==homeworkState.scope||id!==$('homeworkSet').value)return;
    $('homeworkQuestions').querySelectorAll('[data-homework-answer]').forEach((x,i)=>x.value=answers[i]||'');$('homeworkComplete').checked=false;captureHomeworkDraft();toast('作答已放入输入框，请核对后完整提交');
  }finally{button.disabled=false;}
}
async function submitHomework(){
  const scope=homeworkState.scope,id=$('homeworkSet').value,worksheet=homeworkState.sets.find(x=>x.id===id);
  if(!scope||!worksheet||homeworkState.busy)return;
  const answers=[...$('homeworkQuestions').querySelectorAll('[data-homework-answer]')].map(x=>x.value);
  if(answers.some(x=>!x.trim()))return toast('请提交全部题目。不会的题可明确写“不会”及卡点');
  if(!$('homeworkComplete').checked)return toast('请确认作答已完成；提交后会立即开放原题与解析');
  captureHomeworkDraft();homeworkState.busy=true;$('homeworkSubmit').disabled=true;$('homeworkResult').textContent='正在保存作答并导出参考解析…';
  try{
    let options,url;
    if(worksheet.questions[0].language){
      const body=new FormData();body.append('file',new File([answers[0]],'作业'+homeworkExtensions[worksheet.questions[0].language],{type:'text/plain'}));
      Object.entries(scope.selection).forEach(([key,value])=>{if(value!=null)body.append(key,String(value));});
      body.set('detailed_feedback','true');options={method:'POST',body};url=`/api/coding/${id}/submit`;
    }else{options=jsonOptions('POST',{answers,...scope.selection,...attemptPayload($('homeworkQuestions')),detailed_feedback:true});url=`/api/exercises/${id}/submit`;}
    const result=await launchOutcomeTask(url,options);
    if(scope===homeworkState.scope&&$('homeworkDialog').open){
      homeworkState.activeResult=result.id;paintHomeworkResult(result);
      $('homeworkResult').scrollIntoView({block:'nearest',behavior:'smooth'});
    }
    homeworkState.drafts.delete(`${scope.conversationId}:${id}`);
  }catch(e){if(scope===homeworkState.scope)$('homeworkResult').textContent=e.message;error(e);}
  finally{homeworkState.busy=false;if(scope===homeworkState.scope)$('homeworkSubmit').disabled=Boolean(homeworkState.activeResult);}
}
function paintHomeworkResult(result){
  if(result.current_version_matches===false){
    $('homeworkResult').innerHTML=homeworkRow(result);
    $('homeworkQuestions').innerHTML='<p class="small-note">请通过下方“按题回看”查看本次提交时的原题，不会将新题配到旧作答上。</p>';
    $('homeworkAnswerFile').hidden=true;$('homeworkExtract').disabled=true;$('homeworkComplete').disabled=true;$('homeworkSubmit').disabled=true;return;
  }
  $('homeworkResult').innerHTML=`<strong>作答已提交，解析立即可下载</strong><div class="homework-links">${homeworkLinks(result)}</div><p class="small-note">${escapeHtml(homeworkLabels[result.status]||result.status)}。导师另行批改；原因不明时，先在原对话中询问，再交付批改文档。</p>${result.waiting_for_causes?`<button type="button" data-homework-open="${result.id}">去对话填写错因问卷</button>`:''}`;
  const policy={adaptive:'本次低分处理：先找出问题，再选择怎么补学；不会自动加难。',strict:'本次低分处理：原有用自己的话讲解，再做进阶题流程。'}[result.recovery_mode];
  if(policy){const note=document.createElement('p');note.className='small-note';note.textContent=policy;$('homeworkResult').append(note);}
  if(result.is_regrade){const note=document.createElement('p');note.className='small-note';note.textContent='本次是重新检查原作答的分数，不是新增作答；沿用已保存的原条件。';$('homeworkResult').append(note);}
}
function initializeHomework(){
  window.studyforgeRepairPicker?.configure({api,project:()=>state.project?.id,
    scope:()=>`${state.project?.id}:${state.conversation}:${conversationUI.token}`,
    selection:backgroundAssessmentSelection,
    launch:(id,payload)=>launchOutcomeTask('/api/exercises/'+id+'/repair',jsonOptions('POST',payload))});
  window.studyforgeHomeworkReader?.configure({api,render:renderLessonText,
    project:()=>state.project?.id,scope:()=>`${state.project?.id}:${state.conversation}:${conversationUI.token}`,
    async go(id,project){
      if(state.project?.id!==project)return false;
      if($('homeworkDialog').open)$('homeworkDialog').close();
      await selectConversation(id);
      return state.project?.id===project&&state.conversation===id&&!conversationUI.restoring;
    },
    draft(prefix){const input=$('prompt');if(!input.value.includes(prefix))input.value=prefix+'\n'+input.value;
      input.dispatchEvent(new Event('input',{bubbles:true}));saveConversation({draft:input.value});input.focus();}
  });
  const button=document.createElement('button');button.id='submitHomework';button.type='button';button.textContent='✓ 提交作业';button.title='完整提交后立即查看解析，再由导师批改和定位错因';$('recordVoice').after(button);
  const notice=document.createElement('div');notice.id='homeworkNotice';notice.className='homework-notice';notice.hidden=true;$('messages').before(notice);
  const dialog=document.createElement('dialog');dialog.id='homeworkDialog';dialog.className='homework-dialog';
  dialog.innerHTML=`<header><div><span class="eyebrow">HOMEWORK · 作答与反馈</span><h2>提交作业</h2><p id="homeworkContext" class="small-note"></p></div><button type="button" id="closeHomework" aria-label="关闭作业窗口">✕</button></header><div class="homework-dialog-body"><div class="homework-steps"><span>① 完整提交</span><span>② 立即查看参考解析</span><span>③ 找出做错原因，再重新讲解</span></div><label>选择本项目题单<select id="homeworkSet"></select></label><div id="homeworkQuestions"></div><div class="homework-upload"><input type="file" id="homeworkAnswerFile" aria-label="上传已完成的作答"><button type="button" id="homeworkExtract">提取作答到答题框供我核对</button></div><label class="homework-confirm"><input type="checkbox" id="homeworkComplete">我已完成作答（不会的题已注明卡点），提交后查看原题与解析</label><button type="button" class="primary" id="homeworkSubmit">提交作业 · 立即输出解析</button><div id="homeworkResult" role="status"></div><h3>本项目作业记录</h3><div id="homeworkHistory"></div></div>`;
  document.body.append(dialog);
  button.onclick=()=>openHomework().catch(error);$('closeHomework').onclick=()=>dialog.close();dialog.addEventListener('close',captureHomeworkDraft);
  $('homeworkSet').addEventListener('change',()=>{captureHomeworkDraft();paintHomeworkSet();});
  $('homeworkQuestions').addEventListener('input',captureHomeworkDraft);$('homeworkQuestions').addEventListener('change',captureHomeworkDraft);$('homeworkComplete').onchange=captureHomeworkDraft;
  $('homeworkExtract').onclick=()=>extractHomeworkFile().catch(error);$('homeworkSubmit').onclick=()=>submitHomework().catch(error);
  document.addEventListener('click',async event=>{
    const open=event.target.closest('[data-homework-open]'),retry=event.target.closest('[data-homework-retry]');
    try{
      if(event.target.closest('[data-homework-history]'))await openHomework({history:true});
      if(open)await openHomeworkCauses(open.dataset.homeworkOpen);
      if(retry){retry.disabled=true;const result=await api(`/api/homework/${retry.dataset.homeworkRetry}/retry?project_id=${encodeURIComponent(state.project.id)}`,{method:'POST'});await refreshArtifacts();watchOutcomeTask(result.job_id).catch(error);}
    }catch(e){error(e);}finally{if(retry?.isConnected)retry.disabled=false;}
  });
}
