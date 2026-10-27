/* Explicit plans and assessment evidence; selecting a goal never imports chat history. */
const goalUI={items:[],tasks:[],project:null,focus:null,token:0,poller:null,editing:null,editorToken:0,signature:'',deleteArms:new Map(),busy:new Set()};
const goalIntentLabels={explore:'广泛了解',deep:'重点精学',research:'独立探究'};
const goalCriteria={explore:'先知道在研究什么、常用概念是什么，再决定是否深入学。',deep:'讲清概念和每一步理由，换一种情境也能使用，并知道什么时候不适用。',research:'自己重做关键论证，检查假设和反例，分清已知结论与还没证实的问题。'};
const goalTaskLabels={queued:'排队中',waiting:'等待可用模型',running:'生成中',pausing:'正在暂停，等待当前步骤保存',paused:'已暂停，进度保留'};
function goalRecordLabel(check){
  const stamp=new Date(check.created_at),time=Number.isNaN(stamp.getTime())?'':stamp.toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const status={assigned:'待作答',passed:'已达标',completed:'已提交',repair_required:'待补强',repair_retry:'待补强',feynman_required:'费曼环节',feynman_retry:'费曼环节',grading_review_required:'评分还需确认'}[check.status]||'查看记录';
  return `${time} · ${status}${check.current_scope?'':' · 旧范围'}`;
}
function applyLearningGoalFocus(goal){
  $('focusedGoalName').hidden=!goal;$('clearLearningGoal').hidden=!goal;
  $('focusedGoalName').textContent=goal?(goal.paused?'已暂缓 · ':'目标 · ')+goal.name:'';
  $('focusedGoalName').title=goal?.name||'';goalUI.focus=goal?.id||null;
  if(state.conversationConfig)state.conversationConfig.learning_goal=goal;
}
function resetLearningGoals(){
  goalUI.token++;goalUI.editorToken++;goalUI.items=[];goalUI.tasks=[];goalUI.project=null;goalUI.editing=null;goalUI.signature='';goalUI.deleteArms.clear();
  if($('learningGoalDialog').open)$('learningGoalDialog').close();
  $('learningGoals').replaceChildren();$('goalCounts').replaceChildren();$('goalSearch').value='';$('goalIntentFilter').value='all';
  applyLearningGoalFocus(null);if(state.view==='goals')refreshLearningGoals().catch(error);
}
function learningGoalsViewChanged(view){
  clearInterval(goalUI.poller);goalUI.poller=null;
  if(view==='goals'){refreshLearningGoals().catch(error);goalUI.poller=setInterval(()=>refreshLearningGoals().catch(error),2500);}
}
async function refreshLearningGoals(){
  if(!state.project)return;
  const project=state.project.id,chat=state.conversation,token=++goalUI.token;
  const result=await api(`/api/projects/${project}/learning-goals${chat?'?conversation_id='+encodeURIComponent(chat):''}`);
  if(token!==goalUI.token||project!==state.project?.id||chat!==state.conversation)return;
  goalUI.items=result.items;goalUI.tasks=result.tasks;goalUI.project=project;goalUI.focus=result.focused_goal_id;
  const previous=$('goalDomainFilter').value,domains=[...new Set(result.items.map(g=>g.domain))].sort((a,b)=>a.localeCompare(b));
  $('goalDomainFilter').innerHTML='<option value="">全部领域</option>'+domains.map(d=>`<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join('');
  $('goalDomainFilter').value=domains.includes(previous)?previous:'';
  $('goalCounts').innerHTML=Object.entries(goalIntentLabels).map(([intent,label])=>`<div class="goal-count"><span>${label}</span><strong>${result.counts[intent]}</strong></div>`).join('');
  $('goalRouteStatus').textContent=result.notice+(result.counts.deep+result.counts.research>3?' 同时深入学的主题有些多。可以先暂缓一部分，集中学最重要的；你仍可以自行安排。':'');
  applyLearningGoalFocus(result.items.find(g=>g.id===result.focused_goal_id)||null);renderLearningGoals();
}
function goalEvidenceHtml(item){
  const last=item.latest,score=last?last.pending?'待核实':`${last.score} 分`:'尚未检查';
  const aid=last?(last.pending?'暂不用于能力判断':last.aid==='assisted'?'使用过提示或笔记':last.aid==='self_reported_unassisted'?'自报未借助笔记；外部帮助未验证':'辅助条件未说明'):'按需发起，不强制测验';
  const kind=last?({standard:'理解检查',original_repeat:'原题复习',new_context:'换个情境的题'}[last.kind]||'理解检查'):'';
  return `<div class="goal-evidence-item" data-goal-dimension="${item.dimension}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(score)}</strong><span>${kind?kind+' · ':''}${aid}${item.delayed_record_count?` · ${item.delayed_record_count}次延迟原题记录`:''}${item.new_context_record_count?` · ${item.new_context_record_count}次新情境记录`:''}</span></div>`;
}
function renderLearningGoals(){
  const search=$('goalSearch').value.trim().toLowerCase(),intent=$('goalIntentFilter').value,domain=$('goalDomainFilter').value;
  const items=goalUI.items.filter(g=>(intent==='all'||(intent==='paused'?g.paused:!g.paused&&g.intent===intent))&&(!domain||g.domain===domain)&&(g.name+' '+g.domain+' '+g.criterion).toLowerCase().includes(search));
  const signature=JSON.stringify([items,goalUI.tasks,goalUI.focus,search,intent,domain,[...goalUI.busy],[...goalUI.deleteArms.keys()]]);
  if(signature===goalUI.signature)return;goalUI.signature=signature;
  const expanded=new Set([...$('learningGoals').querySelectorAll('.goal-records[open]')].map(node=>node.closest('[data-goal-card]').dataset.goalCard));
  const focused=document.activeElement,focusAttribute=focused?.closest('#learningGoals')?[...focused.attributes].find(a=>a.name.startsWith('data-')):null;
  const scroll=$('learningGoals').scrollTop;
  $('learningGoals').innerHTML=items.map(g=>{
    const unavailable=!g.sources.length||g.sources.some(s=>!s.available),tasks=goalUI.tasks.filter(t=>t.goal_id===g.id),task=tasks[0],busy=goalUI.busy.has(g.id);
    return `<article class="goal-card card" data-goal-card="${g.id}" data-intent="${g.intent}" data-paused="${g.paused}"><header class="goal-card-heading"><div><span class="eyebrow">${escapeHtml(g.domain)} · ${goalIntentLabels[g.intent]}${g.paused?' · 暂缓':''}</span><h3>${escapeHtml(g.name)}</h3></div>${goalUI.focus===g.id?'<span class="goal-current">当前对话目标</span>':''}</header>
      <p class="goal-criterion-text">${escapeHtml(g.criterion)}</p><p class="small-note">${g.sources.length?g.sources.map(s=>escapeHtml(s.name)+(s.available?'':' · 不可用')).join(' · '):'尚未关联原资料，可先整理兴趣和目标'}</p>
      ${g.prerequisites.length?`<div class="goal-prerequisites"><span>建议先了解</span>${g.prerequisites.map(p=>`<button type="button" class="secondary" data-find-goal="${p.id}" title="${escapeHtml(p.reason)}">${escapeHtml(p.name)}</button>`).join('')}</div>`:''}
      <div class="goal-evidence">${g.evidence.map(goalEvidenceHtml).join('')}</div><p class="goal-recommendation">${escapeHtml(g.recommendation.text)}</p>
      ${g.outdated_record_count?`<p class="small-note">${g.outdated_record_count} 条记录来自较早的目标范围，保留原成绩，未混入当前进度。</p>`:''}
      ${task?`<p class="small-note">理解检查 · ${escapeHtml(goalTaskLabels[task.status]||task.status)} · ${task.progress}% <button type="button" class="secondary" data-goal-task="${task.job_id}" data-task-action="${['pausing','paused'].includes(task.status)?'resume':'pause'}">${['pausing','paused'].includes(task.status)?'继续':'暂停'}</button></p>`:''}
      <div class="card-actions"><button type="button" data-study-goal="${g.id}"${g.paused?' disabled':''} title="为当前对话选择此目标与可用目标资料，切换对应学习模式并准备要求，不自动发送">准备学习</button><button type="button" class="secondary" data-check-goal="${g.id}"${g.paused||unavailable||busy||tasks.some(t=>t.kind==='standard'||!t.kind)?' disabled':''} title="按这个目标的资料出 3 道题，生成无答案 Word；不另外生成讲解">用三道题检查理解</button><button type="button" class="secondary" data-context-check-goal="${g.id}"${g.paused||unavailable||busy||tasks.some(t=>t.kind==='new_context')||!g.evidence.some(e=>e.latest&&!e.latest.pending)?' disabled':''} title="参考做过的题，换条件或问法，难度相近；提交后才能看解析">换个情境再测</button>${g.recommendation.action==='review'?`<button type="button" class="secondary" data-review-goal="${g.id}">加入延迟复习</button>`:''}</div>
      ${g.checks.length?`<details class="goal-records"><summary>查看理解检查与原作答</summary>${g.checks.map(c=>`<button type="button" class="secondary" data-goal-set="${c.exercise_set_id}" title="${escapeHtml(c.title)}">${escapeHtml(goalRecordLabel(c))}</button>`).join('')}</details>`:''}
      <footer class="goal-maintenance"><button type="button" data-edit-goal="${g.id}">修改目标与资料</button><button type="button" data-pause-goal="${g.id}">${g.paused?'恢复计划':'暂缓'}</button><button type="button" data-remove-goal="${g.id}" title="只移除计划；原资料、题单、成绩与成果保留">${goalUI.deleteArms.has(g.id)?'再点确认移除':'移除计划'}</button></footer></article>`;
  }).join('')||`<div class="goal-card card"><h3>${goalUI.items.length?'没有匹配的目标':'从一个好奇的问题开始'}</h3><p>可以手动建立目标，也可以从资料知识结构加入。先广泛了解，再把值得投入的主题转入重点精学。</p></div>`;
  $('learningGoals').scrollTop=scroll;
  for(const node of $('learningGoals').querySelectorAll('.goal-records'))node.open=expanded.has(node.closest('[data-goal-card]').dataset.goalCard);
  if(focusAttribute)$('learningGoals').querySelector(`[${focusAttribute.name}="${CSS.escape(focusAttribute.value)}"]`)?.focus({preventScroll:true});
}
async function openLearningGoalEditor(goal=null){
  if(!state.project)return toast('请先选择学习项目');
  const project=state.project.id,token=++goalUI.editorToken;goalUI.editing={id:goal?.id||null,project,version:goal?.version||null,token};
  $('goalEditorTitle').textContent=goal?'修改学习目标':'新建学习目标';$('goalName').value=goal?.name||'';$('goalDomain').value=goal?.domain||'';
  $('goalIntent').value=goal?.intent||'explore';$('goalIntent').dataset.previous=goal?.intent||'explore';$('goalCriterion').value=goal?.criterion||goalCriteria.explore;$('goalPaused').checked=Boolean(goal?.paused);
  $('goalEditorStatus').textContent='正在读取当前项目资料…';$('saveLearningGoal').disabled=true;
  $('goalSourceChoices').replaceChildren();$('goalPrerequisiteChoices').replaceChildren();$('learningGoalDialog').showModal();
  try{
    const sources=await api(`/api/projects/${project}/sources`);
    if(goalUI.editing?.token!==token||state.project?.id!==project)return;
    const selected=new Set(goal?.source_ids||state.selected);
    $('goalSourceChoices').innerHTML=sources.filter(s=>s.status==='ready').map(s=>`<label><input type="checkbox" value="${s.id}"${selected.has(s.id)?' checked':''}>${escapeHtml(s.name)}</label>`).join('')||'<p class="small-note">项目中尚无可用资料；可以先保存目标，之后补充。</p>';
    $('goalPrerequisiteChoices').innerHTML=goalUI.items.filter(g=>g.id!==goal?.id).map(g=>`<label><input type="checkbox" value="${g.id}"${goal?.prerequisites.some(p=>p.id===g.id)?' checked':''}>${escapeHtml(g.name)} · ${escapeHtml(g.domain)}</label>`).join('')||'<p class="small-note">先建立其他目标，再选择建议先学。</p>';
    $('goalEditorStatus').textContent='保存目标不会请求 AI，也不会改其他对话。修改资料或目标后，旧测验成绩会保留，但不会当成新目标的成绩。';$('saveLearningGoal').disabled=false;$('goalName').focus();
  }catch(failure){if(goalUI.editing?.token===token)$('goalEditorStatus').textContent=failure.message;}
}
async function studyLearningGoal(goal){
  const project=state.project?.id;if(project!==goal.project_id)return;
  if(!state.conversation)await createConversation();
  if(project!==state.project?.id||!state.conversation)return;
  const chat=state.conversation;
  await api(`/api/conversations/${chat}/learning-goal?project_id=${project}`,jsonOptions('PUT',{goal_id:goal.id}));
  if(project!==state.project?.id||chat!==state.conversation)return;
  applyLearningGoalFocus(goal);
  const ids=goal.sources.filter(s=>s.available).map(s=>s.id);
  state.selected=new Set(ids);renderSourceUI();persistSelection();
  applyLearningMode({explore:'overview',deep:'deep',research:'research'}[goal.intent]);
  const materialRequest=ids.length?'先解释当前材料中的核心问题与必要概念，再按我的理解补足方法理由和适用边界。':'我尚未提供这个目标的原资料；先界定问题与必要前置，具体事实注明核实范围，不虚构来源。';
  const request=`请围绕${goal.domain}中的“${goal.name}”帮助我学习。我的目标是：${goal.criterion}。${materialRequest}本次先讲解，不另布置习题；不要假定我已经读懂或掌握。`;
  $('prompt').value=[$('prompt').value.trim(),request].filter(Boolean).join('\n');saveConversation({draft:$('prompt').value});
  showView('study');$('prompt').focus();toast('目标、模式与目标资料已用于当前对话；学习要求已准备，可编辑后发送');
}
async function launchGoalCheck(goal,kind='standard'){
  const project=state.project?.id;if(project!==goal.project_id||goalUI.busy.has(goal.id))return;
  if(!state.conversation)await createConversation();
  if(project!==state.project?.id||!state.conversation)return;
  await flushConversation();const request=captureStudyRequest(),chat=request.conversation_id;
  goalUI.busy.add(goal.id);renderLearningGoals();
  try{
    const result=await api(`/api/projects/${project}/learning-goals/${goal.id}/check`,jsonOptions('POST',{
      version:goal.version,conversation_id:chat,provider:request.provider,model:request.model,reasoning_effort:request.reasoning_effort,
      explanation_style:request.explanation_style,output_language:request.output_language,kind}));
    if(project===state.project?.id&&chat===state.conversation){await selectConversation(chat,{refresh:true});await refreshLearningGoals();}
    trackJob(result.job_id).catch(error);toast(result.reused?'打开已启动的理解检查任务':kind==='new_context'?'正在生成换个情境的三道题：保持参考难度，解析与情境说明在提交后开放':'正在生成用三道题检查理解：只出题，无答案，不同步生成讲解');
  }finally{goalUI.busy.delete(goal.id);if(project===state.project?.id)renderLearningGoals();}
}
async function importKnowledgeGoals(ids){
  const row=knowledgeState.row,project=state.project?.id;
  if(!row?.structure)return toast('先整理带来源的知识结构，再加入路线');
  const result=await api(`/api/projects/${project}/learning-goals/import`,jsonOptions('POST',{map_id:row.id,concept_ids:ids||row.structure.concepts.map(n=>n.id)}));
  if(project!==state.project?.id)return;
  toast(`新增${result.created}个路线目标，默认广泛了解；可选择其中一部分精学`);
  if($('knowledgeDialog').open)$('knowledgeDialog').close();showView('goals');
}
document.addEventListener('input',event=>{if(event.target.id==='goalSearch')renderLearningGoals();});
document.addEventListener('change',event=>{
  if(['goalIntentFilter','goalDomainFilter'].includes(event.target.id))renderLearningGoals();
  if(event.target.id==='goalIntent'){const previous=event.target.dataset.previous;if($('goalCriterion').value===goalCriteria[previous])$('goalCriterion').value=goalCriteria[event.target.value];event.target.dataset.previous=event.target.value;}
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='learningGoalForm')return;event.preventDefault();
  (async()=>{
    const edit=goalUI.editing;if(!edit||edit.project!==state.project?.id)return;
    $('saveLearningGoal').disabled=true;
    try{
      const payload={name:$('goalName').value.trim(),domain:$('goalDomain').value.trim(),intent:$('goalIntent').value,criterion:$('goalCriterion').value.trim(),paused:$('goalPaused').checked,
        source_ids:[...$('goalSourceChoices').querySelectorAll('input:checked')].map(x=>x.value),prerequisite_ids:[...$('goalPrerequisiteChoices').querySelectorAll('input:checked')].map(x=>x.value),version:edit.version};
      await api(`/api/projects/${edit.project}/learning-goals${edit.id?'/'+edit.id:''}`,jsonOptions(edit.id?'PUT':'POST',payload));
      if(edit.project!==state.project?.id||goalUI.editing?.token!==edit.token)return;$('learningGoalDialog').close();goalUI.editing=null;await refreshLearningGoals();toast('学习目标已保存，不会自动出题或认定掌握');
    }catch(failure){if(goalUI.editing?.token===edit.token)$('goalEditorStatus').textContent=failure.message;}
    finally{if(!goalUI.editing||goalUI.editing.token===edit.token)$('saveLearningGoal').disabled=false;}
  })().catch(error);
});
document.addEventListener('click',event=>{
  const button=event.target.closest('#openLearningGoals,#newLearningGoal,#refreshLearningGoals,#goalFromKnowledge,#closeLearningGoal,#cancelLearningGoal,#clearLearningGoal,#addKnowledgeGoals,[data-goal-concept],[data-study-goal],[data-check-goal],[data-context-check-goal],[data-edit-goal],[data-pause-goal],[data-remove-goal],[data-find-goal],[data-goal-set],[data-review-goal],[data-goal-task]');
  if(!button)return;
  (async()=>{
    if(button.id==='openLearningGoals'){showView('goals');return;}
    if(button.id==='refreshLearningGoals'){await refreshLearningGoals();return;}
    if(button.id==='newLearningGoal'){await refreshLearningGoals();await openLearningGoalEditor();return;}
    if(button.id==='goalFromKnowledge'){await openKnowledge();return;}
    if(['closeLearningGoal','cancelLearningGoal'].includes(button.id)){goalUI.editing=null;$('learningGoalDialog').close();return;}
    if(button.id==='clearLearningGoal'){const project=state.project?.id,chat=state.conversation;await api(`/api/conversations/${chat}/learning-goal?project_id=${project}`,jsonOptions('PUT',{goal_id:null}));if(project===state.project?.id&&chat===state.conversation)applyLearningGoalFocus(null);return;}
    if(button.id==='addKnowledgeGoals'||button.dataset.goalConcept){await importKnowledgeGoals(button.dataset.goalConcept?[button.dataset.goalConcept]:null);return;}
    if(button.dataset.findGoal){$('goalSearch').value='';$('goalDomainFilter').value='';$('goalIntentFilter').value='all';renderLearningGoals();const card=document.querySelector(`[data-goal-card="${button.dataset.findGoal}"]`);card?.scrollIntoView({block:'center',behavior:document.documentElement.dataset.motion==='reduced'?'instant':'smooth'});card?.classList.add('highlight');setTimeout(()=>card?.classList.remove('highlight'),1800);return;}
    if(button.dataset.goalSet){showView('exercises');await refreshExercises();await openSet(button.dataset.goalSet);return;}
    if(button.dataset.goalTask){button.disabled=true;try{await changeTask(button.dataset.goalTask,button.dataset.taskAction);await refreshLearningGoals();}finally{button.disabled=false;}return;}
    const ident=button.dataset.studyGoal||button.dataset.checkGoal||button.dataset.contextCheckGoal||button.dataset.editGoal||button.dataset.pauseGoal||button.dataset.removeGoal||button.dataset.reviewGoal,goal=goalUI.items.find(g=>g.id===ident);
    if(!goal)return;
    if(button.dataset.studyGoal){await studyLearningGoal(goal);return;}
    if(button.dataset.checkGoal){await launchGoalCheck(goal);return;}
    if(button.dataset.contextCheckGoal){await launchGoalCheck(goal,'new_context');return;}
    if(button.dataset.editGoal){await openLearningGoalEditor(goal);return;}
    if(button.dataset.pauseGoal){await api(`/api/projects/${goal.project_id}/learning-goals/${goal.id}`,jsonOptions('PATCH',{paused:!goal.paused,version:goal.version}));await refreshLearningGoals();return;}
    if(button.dataset.reviewGoal){await api(`/api/projects/${goal.project_id}/learning-goals/${goal.id}/review?interval_days=3`,{method:'POST'});toast('已加入3天后复习，可在练习与作业中调整；提前练习会记录实际间隔');return;}
    if(button.dataset.removeGoal){
      if(!goalUI.deleteArms.has(goal.id)){const deadline=Date.now()+5000;goalUI.deleteArms.set(goal.id,deadline);renderLearningGoals();setTimeout(()=>{if(goalUI.deleteArms.get(goal.id)===deadline){goalUI.deleteArms.delete(goal.id);renderLearningGoals();}},5000);return;}
      await api(`/api/projects/${goal.project_id}/learning-goals/${goal.id}?version=${goal.version}`,{method:'DELETE'});goalUI.deleteArms.delete(goal.id);await refreshLearningGoals();toast('已移除计划；原资料、题单、成绩和成果保留');
    }
  })().catch(error);
});
