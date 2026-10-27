/* Optional scaffolds and review queues never trigger AI requests by themselves. */
const practiceState={drafts:new Map(),selected:new Set(),offset:0,limit:50,total:0,token:0,starting:false};
const practiceLabels={terminology:'不懂术语',prerequisites:'缺少相关基础知识',motivation:'不懂为什么想到这一步',method_selection:'不知道何时用方法',argumentation:'自己还不能完整证明',implementation:'计算或实现出错',unknown:'还不确定卡点'};
const exerciseStatusLabels={assigned:'待作答',grading_review_required:'评分还需确认 · 未定分',passed:'达到本次通过线',passed_with_support:'使用提示或笔记后通过',feynman_required:'用自己的话讲解',feynman_retry:'自己的讲解还没讲清',retry_ready:'可进入进阶',repair_required:'先找出问题再补学',repair_retry:'还需要重新讲解',repair_ready:'已讲清楚 · 可以选择继续练习'};

function capturePracticeDrafts(){
  for(const box of document.querySelectorAll('.exercise-body[data-practice-project]')){
    practiceState.drafts.set(box.dataset.practiceProject+':'+box.id,{
      answers:[...box.querySelectorAll('[data-answer]')].map(x=>x.value),
      notes:box.querySelector('[data-used-notes]')?.value,
      mode:box.querySelector('[data-recovery-mode]')?.value,
      feynman:box.querySelector('#feynmanText')?.value
    });
  }
}

function restorePracticeDraft(box,s){
  box.dataset.practiceProject=s.project_id;
  const draft=practiceState.drafts.get(s.project_id+':'+box.id);
  if(!draft)return;
  if(s.status==='assigned')box.querySelectorAll('[data-answer]').forEach((x,i)=>x.value=draft.answers[i]||'');
  if(box.querySelector('[data-used-notes]')&&draft.notes)box.querySelector('[data-used-notes]').value=draft.notes;
  if(box.querySelector('[data-recovery-mode]')&&draft.mode)box.querySelector('[data-recovery-mode]').value=draft.mode;
  if(box.querySelector('#feynmanText')&&draft.feynman)box.querySelector('#feynmanText').value=draft.feynman;
}

function hintControls(s,q){
  const usage=s.practice?.hint_usage||[];
  const current=usage.filter(x=>x.question_index===q.index).sort((a,b)=>b.level-a.level)[0];
  const kind=current?.kind||'unknown',level=Math.min(3,(current?.level||0)+1);
  return `<details class="practice-hint" data-hint-controls="${q.index}" data-set-id="${s.id}" data-usage="${escapeHtml(JSON.stringify(usage.filter(x=>x.question_index===q.index)))}"><summary>需要思考提示？${current?' · 已记录使用':''}</summary><div><select data-hint-kind aria-label="第${q.index+1}题卡点">${Object.entries(practiceLabels).map(([id,label])=>`<option value="${id}"${id===kind?' selected':''}>${label}</option>`).join('')}</select><button type="button" class="secondary" data-get-hint data-level="${level}">第${level}层提示</button></div><p class="small-note">每点一层，就多给一点思考方向，不会提前给答案。用过哪些提示会保存；完整提交后才能看解析。</p><p data-hint-text hidden></p></details>`;
}

function attemptControls(s){
  return `<details class="practice-attempt-options"><summary>作答条件与低分处理</summary><div><label>是否看过笔记或解析<select data-used-notes><option value="unknown">尚未说明</option><option value="false">我未看笔记或解析</option><option value="true">我参考过笔记或解析</option></select></label><label>低于80分后<select data-recovery-mode><option value="adaptive"${s.practice?.is_review||s.practice?.recovery_mode!=='strict'?' selected':''}>先诊断，自己选择补学方式</option><option value="strict"${!s.practice?.is_review&&s.practice?.recovery_mode==='strict'?' selected':''}>原有用自己的话讲解，再做进阶题</option></select></label></div><p class="small-note">这里只选择低分后的学习方式，不改变判分。选择自己安排补学时，不会自动布置更难的题；请如实说明是否看过笔记。</p></details>`;
}

function attemptPayload(box){
  const value=box.querySelector('[data-used-notes]')?.value;
  return {recovery_mode:box.querySelector('[data-recovery-mode]')?.value||'strict',used_notes:value==='true'?true:value==='false'?false:null};
}

function repairLearningNote(s){
  const version=s.practice?.version_notice?'<aside class="small-note practice-repair-reference">'+escapeHtml(s.practice.version_notice)+'</aside>':'';
  const reference=s.repair;if(!reference)return version;
  const targets=reference.targets.map(t=>'原第'+(t.index+1)+'题 · '+t.topic).join('；');
  return version+'<aside class="small-note practice-repair-reference" data-repair-reference><strong>针对这次错题再练</strong><p>'+escapeHtml(targets)+'</p><p>'+escapeHtml(reference.notice)+'</p></aside>';
}
function homeworkRepairAction(item){
  return item.repair_available?'<button type="button" data-repair-set="'+item.exercise_set_id+'">按本次错因同难度再练</button>':'';
}
function practiceAfterSubmission(s,latest){
  const grade=latest.grade||{},diagnostics=Array.isArray(grade.diagnostics)?grade.diagnostics:[];
  const recheck=grade.regrade_basis?.same_answers?'<p class="small-note">本次是复核原作答的评分，不是新增作答；沿用已保存的原条件，缺失条件仍未知。</p>':'';
  if(grade.grading_verification_required)return `<section class="practice-followup"><h4>评分还需确认</h4><p>这次判分还有需要确认的地方，暂不定最终分数，也不会要求补考或把它记为你的能力弱项。请先查看批改记录。</p>${s.homework?'<button type="button" class="secondary" data-homework-history>查看批改记录与复核入口</button>':`<button type="button" class="secondary" id="regradeAnswers">重新检查原作答</button>`}</section>`;
  const low=s.questions.filter((q,i)=>(grade.scores?.[i]??100)<100);
  const diagnosticsHtml=diagnostics.filter(x=>(grade.scores?.[x.index]??100)<100).map(x=>`<section class="practice-diagnosis" data-practice-diagnosis="${x.index}"><strong>第${x.index+1}题 · ${escapeHtml(x.label)} · ${escapeHtml(x.status)}</strong><div class="practice-diagnosis-text" data-diagnosis-field="reason"></div>${x.quote?`<small>批改引用的作答片段</small><blockquote>${escapeHtml(x.quote)}</blockquote>`:''}<div class="practice-diagnosis-next"><small>下一步</small><div class="small-note" data-diagnosis-field="next_step"></div></div></section>`).join('');
  const tutorAction=s.homework?.id?`<button type="button" class="secondary" data-homework-read="${escapeHtml(s.homework.id)}">按题回看，再向导师追问</button>`:`<button type="button" class="secondary" data-practice-tutor="${s.id}">带回导师定位卡点</button>`;
  const strict=['feynman_required','feynman_retry'].includes(s.status);
  const ready=low.length&&!strict&&(!s.homework||s.homework.repair_available);
  const readiness=ready?'':!low.length?'本次没有已确认的失分的题目，无需按错因生成薄弱点练习；可按自己的目标继续学习。':
    strict?'这份题单采用用自己的话重新讲解的流程，请先用自己的话讲清楚，再选择后续练习。':
    '先完成本次批改与错因补讲，再根据已完成的定位再练；失败或取消后可在作业记录继续。';
  const repairAction=ready?`<button type="button" class="secondary" data-repair-set="${s.id}">请求同难度薄弱点练习</button>`:
    low.length&&!strict&&s.homework&&!s.homework.repair_available?'<button type="button" class="secondary" data-homework-history>查看批改状态与恢复入口</button>':'';
  const context=grade.practice_context||{};
  const timing=(context.timing||[]).map(x=>`第${x.question_index+1}题距上次作答已过 ${x.delay_hours} 小时${x.due_reached?' · 已到计划时间':' · 提前练习'}`).join('；');
  return `<section class="practice-followup"><h4>下一步按你的需要</h4>${recheck}${diagnosticsHtml}<p class="small-note">${context.recording_status==='not_recorded'?'原始作答条件未保存，无法核实；':''}${context.hint_levels&&Object.keys(context.hint_levels).length?'使用过软件提示；':''}${context.used_notes===true?'自报参考过笔记或解析；':context.used_notes===false?'自报未看笔记或解析；':'笔记使用未说明；'}${escapeHtml(timing)} 成绩不等于稳定掌握。</p>${readiness?`<p class="small-note" data-repair-readiness>${escapeHtml(readiness)}</p>`:''}<div class="practice-next-actions">${tutorAction}${repairAction}</div><details class="review-scheduling"><summary>可选：过几天再复习</summary><div class="review-question-selection">${s.questions.map(q=>`<label><input type="checkbox" data-review-question value="${q.index}"${(!low.length||low.some(x=>x.index===q.index))?' checked':''}>第${q.index+1}题 · ${escapeHtml(q.topic)}</label>`).join('')}</div><div class="review-toolbar"><label>几天后复习 <input type="number" data-review-interval min="1" max="90" value="1" list="reviewIntervals"></label><button type="button" class="secondary" data-schedule-review="${s.id}">加入待复习列表</button></div><p class="small-note">可以选 1、3、7、14 天后再做，也能提前复习或移除。这是提醒安排，不代表软件能准确预测你何时忘记。</p></details></section>`;
}

function renderPracticeDiagnostics(host,grade){
  const rows=Array.isArray(grade.diagnostics)?grade.diagnostics:[];
  for(const panel of host.querySelectorAll('[data-practice-diagnosis]')){
    const row=rows.find(item=>String(item.index)===panel.dataset.practiceDiagnosis);
    for(const field of panel.querySelectorAll('[data-diagnosis-field]'))
      renderLessonText(field,String(row?.[field.dataset.diagnosisField]??''));
  }
}

async function refreshReviews(){
  const token=++practiceState.token;
  const params=new URLSearchParams({offset:practiceState.offset,limit:practiceState.limit,due_only:$('reviewDueOnly').checked});
  const requestedSelection=[...practiceState.selected];
  requestedSelection.forEach(id=>params.append('selected_ids',id));
  const result=await api('/api/reviews?'+params);
  if(token!==practiceState.token)return;
  if(Array.isArray(result.selected_ids)){
    const eligible=new Set(result.selected_ids);
    requestedSelection.forEach(id=>{if(!eligible.has(id))practiceState.selected.delete(id);});
  }
  if(practiceState.offset>=result.total&&practiceState.offset>0){practiceState.offset=Math.max(0,Math.floor((result.total-1)/practiceState.limit)*practiceState.limit);return refreshReviews();}
  practiceState.total=result.total;
  $('reviewQueueCount').textContent=`${result.due_count} 项到期 · ${result.total} 项当前筛选`;
  $('reviewQueueItems').innerHTML=result.items.map(item=>`<article class="review-queue-item"><label><input type="checkbox" data-review-select="${item.id}"${practiceState.selected.has(item.id)?' checked':''}${item.active_set_id?' disabled':''}><span><strong>${escapeHtml(item.topic)}</strong><small>${escapeHtml(item.project_name)} · 第${item.question_index+1}题 · ${escapeHtml(new Date(item.due_at).toLocaleString())} · ${item.active_set_id?'正在作答':item.due?'已到期':'尚未到期'}</small>${item.version_notice?`<small class="review-version-note">${escapeHtml(item.version_notice)}</small>`:''}</span></label><div>${item.active_set_id?`<button type="button" class="secondary" data-open-review="${item.active_set_id}">继续作答</button>`:''}<button type="button" class="secondary" data-remove-review="${item.id}">移出复习</button></div></article>`).join('')||'<p class="small-note">尚无符合筛选的复习题。来源项目或复习所在项目移入回收站后会暂时隐藏，恢复项目即可继续。完成习题后可自行选择加入；只读讲解不会自动安排复习。</p>';
  $('reviewSelectedCount').textContent=`已选 ${practiceState.selected.size}/6 题，可跨项目`;
  $('reviewPrevious').disabled=practiceState.offset===0;$('reviewNext').disabled=practiceState.offset+practiceState.limit>=result.total;
  $('reviewPage').textContent=result.total?`${Math.floor(practiceState.offset/practiceState.limit)+1}/${Math.ceil(result.total/practiceState.limit)} 页`:'0 条';
}

async function openReviewSet(id){
  const s=await api('/api/exercises/'+id);
  if(state.project?.id!==s.project_id){const projects=await api('/api/projects');await selectProject(projects.find(x=>x.id===s.project_id));}
  showView('exercises');await refreshExercises();await openSet(id);
}

document.addEventListener('change',event=>{
  if(event.target.matches('[data-hint-kind]')){
    const panel=event.target.closest('[data-hint-controls]'),usage=JSON.parse(panel.dataset.usage);
    const last=usage.find(x=>x.kind===event.target.value)?.level||0,button=panel.querySelector('[data-get-hint]');
    button.dataset.level=Math.min(3,last+1);button.textContent=`第${button.dataset.level}层提示`;panel.querySelector('[data-hint-text]').hidden=true;return;
  }
  if(event.target.dataset.reviewSelect){const id=event.target.dataset.reviewSelect;
    if(event.target.checked&&practiceState.selected.size>=6){event.target.checked=false;toast('一次最多选择6题');return;}
    if(event.target.checked)practiceState.selected.add(id);else practiceState.selected.delete(id);
    $('reviewSelectedCount').textContent=`已选 ${practiceState.selected.size}/6 题，可跨项目`;return;
  }
  if(event.target.id==='reviewDueOnly'){practiceState.offset=0;refreshReviews().catch(error);}
});

document.addEventListener('click',event=>{
  const target=event.target.closest('[data-get-hint],[data-schedule-review],[data-repair-set],[data-practice-tutor],[data-open-review],[data-remove-review],#startMixedReview,#clearReviewSelection,#reviewPrevious,#reviewNext');
  if(!target)return;
  (async()=>{
    if(target.hasAttribute('data-get-hint')){
      const panel=target.closest('[data-hint-controls]'),kind=panel.querySelector('[data-hint-kind]').value;
      target.disabled=true;
      try{const result=await api('/api/exercises/'+panel.dataset.setId+'/hint',jsonOptions('POST',{question_index:Number(panel.dataset.hintControls),kind,level:Number(target.dataset.level)}));
        const text=panel.querySelector('[data-hint-text]');text.hidden=false;text.textContent=`第${result.level}层：${result.hint}`;
        const usage=JSON.parse(panel.dataset.usage).filter(x=>x.kind!==kind);usage.push({kind,level:result.level});panel.dataset.usage=JSON.stringify(usage);
        target.dataset.level=Math.min(3,result.level+1);target.textContent=result.level===3?'再看第3层':`第${target.dataset.level}层提示`;
      }finally{target.disabled=false;}return;
    }
    if(target.dataset.scheduleReview){const box=target.closest('.exercise-body'),indices=[...box.querySelectorAll('[data-review-question]:checked')].map(x=>Number(x.value));
      if(!indices.length)return toast('请选择至少一道需要复习的题');target.disabled=true;
      try{await api('/api/exercises/'+target.dataset.scheduleReview+'/review',jsonOptions('POST',{question_indices:indices,interval_days:Number(box.querySelector('[data-review-interval]').value)}));await refreshReviews();$('reviewQueuePanel').open=true;toast('已加入复习；不会自动生成新题');}finally{target.disabled=false;}return;
    }
    if(target.dataset.repairSet){target.disabled=true;const label=target.textContent;target.textContent='正在请求同难度练习…';
      try{capturePracticeDrafts();await window.studyforgeRepairPicker.open(target.dataset.repairSet);}finally{target.disabled=false;target.textContent=label;}return;
    }
    if(target.dataset.practiceTutor){
      const project=state.project?.id,conversation=state.conversation,token=conversationUI.token;
      const stillHere=()=>state.project?.id===project&&state.conversation===conversation&&conversationUI.token===token&&!state.projectLoading&&!conversationUI.restoring;
      const s=await api('/api/exercises/'+target.dataset.practiceTutor);
      if(!stillHere())return;
      if(s.homework?.id){await window.studyforgeHomeworkReader.open(s.homework.id);return;}
      if(state.busy)return toast('请等待当前导师回复');
      const records=await api('/api/exercises/'+target.dataset.practiceTutor+'/submissions');
      if(!stillHere())return;
      const grade=records[0]?.grade||{};const request=`请帮我定位《${s.title}》这次练习的卡点，基于以下已提交题干、作答引句与反馈讲解，不要因低分加难度或自动另出题。诊断是暂定的，依据不足时先询问我具体卡在哪一步。\n`+s.questions.map((q,i)=>{const diagnosis=grade.diagnostics?.find(x=>x.index===i);return `第${i+1}题：${q.question}\n批改反馈：${grade.feedback?.[i]||'尚无具体依据，先帮助定位'}\n作答引句：${diagnosis?.quote||'未记录，不能补编'}\n暂定卡点：${diagnosis?.label||'待定位'}；${diagnosis?.reason||'需先询问学生'}`;}).join('\n');
      $('prompt').value=[$('prompt').value.trim(),request].filter(Boolean).join('\n');showView('study');$('prompt').focus();return;
    }
    if(target.dataset.openReview){await openReviewSet(target.dataset.openReview);return;}
    if(target.dataset.removeReview){await api('/api/reviews/'+target.dataset.removeReview,{method:'DELETE'});practiceState.selected.delete(target.dataset.removeReview);await refreshReviews();toast('已移出复习，原题和成绩保留');return;}
    if(target.id==='clearReviewSelection'){practiceState.selected.clear();await refreshReviews();return;}
    if(target.id==='reviewPrevious'||target.id==='reviewNext'){practiceState.offset+=target.id==='reviewNext'?practiceState.limit:-practiceState.limit;await refreshReviews();return;}
    if(target.id==='startMixedReview'){
      if(practiceState.starting||!practiceState.selected.size)return toast('请先选择要复习的题');practiceState.starting=true;target.disabled=true;
      try{capturePracticeDrafts();const result=await api('/api/reviews/start',jsonOptions('POST',{project_id:state.project.id,item_ids:[...practiceState.selected]}));practiceState.selected.clear();await refreshExercises();await openSet(result.exercise_set.id);toast('请先尝试回忆再提交；完整作答后才显示本次解析');}
      finally{practiceState.starting=false;target.disabled=false;}
    }
  })().catch(error);
});
