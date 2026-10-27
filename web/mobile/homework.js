'use strict';
(() => {
  const state = {projectId:null, sets:[], worksheet:null, attempt:null, view:0,
    refresh:0, busy:new Set(), causeTimers:new Map(), causeChains:new Map(), causePayloads:new Map()};
  const labels = {assigned:'尚未提交',accepted:'作答已保存，正在批改',grading:'正在批改',awaiting_causes:'等待错因反馈',
    clarified:'正在准备补讲',completed:'批改已完成',awaiting_grade_review:'评分还需确认',
    grading_review_required:'评分还需确认',failed:'需要重试',cancelled:'已取消',source_changed:'原题已变更 · 仅可回看',source_unavailable:'无法确认当时的原题',
    feynman_required:'需要费曼讲解',feynman_retry:'费曼讲解尚需改进',
    repair_required:'可以开始薄弱点练习',repair_retry:'继续修复理解',repair_ready:'可以开始薄弱点练习',
    retry_ready:'可以开始进阶练习',mastered:'本次测验已通过',graded:'已批改',
    passed:'本次测验已通过',passed_with_support:'本次在辅助下完成'};
  const languages = {python:['Python','.py'],javascript:['JavaScript','.js'],
    typescript:['TypeScript','.ts'],cpp:['C++','.cpp'],matlab:['MATLAB','.m'],wolfram:['Wolfram Language','.wl']};
  function node(tag, text, className) {
    const value=document.createElement(tag);if(text!==undefined)value.textContent=text;
    if(className)value.className=className;return value;
  }
  function isCoding(worksheet) {return Boolean(worksheet?.questions?.[0]?.language);}
  function draftKey(kind, project, id) {return 'sfMobileHomework:'+kind+':'+project+':'+id;}
  function version(worksheet) {return JSON.stringify(worksheet.questions);}
  function matches(project, id, view) {
    return mobile.authenticated && mobile.project?.id===project &&
      state.worksheet?.id===id && state.view===view;
  }
  function assessment() {
    const snapshot=requestSnapshot();
    return {provider:snapshot.provider,model:snapshot.model,reasoning_effort:snapshot.reasoning_effort,
      conversation_id:snapshot.conversation_id,background:true,detailed_feedback:true};
  }
  function saveAnswers() {
    if(!state.worksheet || !$('homeworkAnswerForm') || $('homeworkAnswerForm').hidden)return;
    const answers=[...$('homeworkQuestions').querySelectorAll('[data-homework-answer]')].map(input=>input.value);
    safeWrite(draftKey('answers',state.projectId,state.worksheet.id),
      {version:version(state.worksheet),answers,used_notes:$('homeworkUsedNotes').value,recovery_mode:$('homeworkRecoveryMode').value});
  }
  function reset() {
    saveAnswers();state.view++;state.refresh++;state.projectId=null;state.sets=[];
    state.worksheet=null;state.attempt=null;state.causeSignature=null;
    if($('homeworkDialog')?.open)$('homeworkDialog').close();
    if($('homeworkNotice'))$('homeworkNotice').hidden=true;
    if($('homeworkCount'))$('homeworkCount').textContent='0';
    if($('homeworkList'))$('homeworkList').replaceChildren();
    if($('homeworkDetail'))$('homeworkDetail').hidden=true;
    if($('homeworkBrowse'))$('homeworkBrowse').hidden=false;
  }
  function notice() {
    const pending=state.sets.map(row=>row.homework).filter(row=>
      row?.waiting_for_causes && row.conversation_id===mobile.chat?.id);
    $('homeworkNotice').hidden=!pending.length;
    if(pending.length) {
      const count=pending.reduce((total,row)=>total+row.questions.length,0);
      $('homeworkNoticeText').textContent='批改文档已暂停：'+count+' 题错因待确认';
      $('homeworkNoticeOpen').onclick=()=>openAttempt(pending[0].id).catch(error=>toast(error.message));
    }
  }
  function renderList() {
    const list=$('homeworkList');return window.studyforgeRefresh.paint(list,[state.projectId,mobile.epoch,state.sets],()=>{list.replaceChildren();
    for(const worksheet of state.sets) {
      const attempt=worksheet.homework,card=node('article',undefined,'item homework-item');
      const title=node('strong',worksheet.title),status=labels[attempt?.status||worksheet.status]||worksheet.status;
      const language=languages[worksheet.questions[0]?.language]?.[0];
      const meta=node('p',worksheet.questions.length+' 题 · '+(language||'知识练习')+' · '+status);
      const actions=node('div',undefined,'item-actions'),button=node('button',
        attempt?.waiting_for_causes?'填写错因问卷':attempt?'查看解析与批改':'开始作答');
      button.type='button';button.dataset.homeworkSet=worksheet.id;
      button.onclick=()=>openSet(worksheet.id).catch(error=>toast(error.message));actions.append(button);
      if(attempt?.conversation_title)card.append(node('small','提交于：'+attempt.conversation_title,'helper'));
      card.prepend(title,meta);card.append(actions);list.append(card);
    }
    if(!state.sets.length)list.append(node('p','本项目还没有题单。可以请导师出题，或选择“只生成习题”。','helper'));
    });
  }
  async function refresh() {
    if(!mobile.authenticated || !mobile.project)return;
    const project=mobile.project.id,epoch=mobile.epoch,token=++state.refresh;
    const sets=await api('/api/projects/'+project+'/exercises');
    if(!mobile.authenticated || mobile.project?.id!==project || mobile.epoch!==epoch || token!==state.refresh)return;
    state.projectId=project;state.sets=sets;$('homeworkCount').textContent=sets.length;
    renderList();notice();
    if(state.worksheet) {
      const current=sets.find(row=>row.id===state.worksheet.id);
      if(!current){back();return;}
      if(version(current)!==version(state.worksheet)) {
        saveAnswers();state.worksheet=current;renderQuestions();
        toast('题目已更新，请重新核对作答。');
      }else state.worksheet=current;
      if(current.homework)renderAttempt(current.homework);
      renderFeynman();
    }
  }
  async function open() {
    if(!mobile.project || !mobile.chat)return toast('请先打开一个学习对话。');
    for(const id of ['optionsDialog','tasksDialog'])if($(id).open)$(id).close();
    openSheet('homeworkDialog');$('homeworkContext').textContent=mobile.project.name+' / '+$('conversationName').textContent;
    if(state.projectId!==mobile.project.id)back();
    await refresh();
  }
  function back() {
    saveAnswers();state.view++;state.worksheet=null;state.attempt=null;state.causeSignature=null;
    $('homeworkBrowse').hidden=false;$('homeworkDetail').hidden=true;$('homeworkHeading').textContent='作业与补讲';
  }
  async function openSet(id) {
    if(!mobile.project)return;
    saveAnswers();const project=mobile.project.id,view=++state.view;
    const worksheet=await api('/api/exercises/'+id);
    if(!mobile.authenticated || mobile.project?.id!==project || view!==state.view)return;
    if(worksheet.project_id!==project)throw new Error('这份题单不属于当前项目。');
    state.projectId=project;state.worksheet=worksheet;state.attempt=null;state.causeSignature=null;
    state.feynmanSignature=null;$('homeworkFeynmanFeedback').replaceChildren();
    $('homeworkBrowse').hidden=true;$('homeworkDetail').hidden=false;$('homeworkHeading').textContent='作答与反馈';
    $('homeworkTitle').textContent=worksheet.title;
    $('homeworkContext').textContent=mobile.project.name+' / '+$('conversationName').textContent;
    $('homeworkComplete').checked=false;$('homeworkResult').replaceChildren();$('homeworkCauses').hidden=true;
    $('homeworkFile').value='';$('homeworkFileStatus').textContent='选择文件不会自动读取。点击后才识别，识别结果需逐题核对。';
    renderQuestions();if(worksheet.homework)renderAttempt(worksheet.homework);renderFeynman();
    openSheet('homeworkDialog');
  }
  async function openAttempt(id) {
    if(!mobile.project)return;
    const project=mobile.project.id,epoch=mobile.epoch;
    const attempt=await api('/api/homework/'+id+'?project_id='+project);
    if(mobile.project?.id!==project || mobile.epoch!==epoch)return;
    for(const name of ['optionsDialog','tasksDialog'])if($(name).open)$(name).close();
    await openSet(attempt.exercise_set_id);
  }
  function renderQuestions() {
    const worksheet=state.worksheet,coding=isCoding(worksheet),box=$('homeworkQuestions');
    const saved=safeRead(draftKey('answers',state.projectId,worksheet.id),null);
    const draft=saved?.version===version(worksheet)?saved:null;
    box.replaceChildren();
    if(worksheet.homework?.current_version_matches===false){
      $('homeworkDescription').textContent='旧作答按提交时原题回看，详情见下方版本说明。';
      $('homeworkAnswerForm').hidden=true;return;
    }
    if(worksheet.practice?.version_notice)box.append(node('aside',worksheet.practice.version_notice,'helper practice-repair-reference'));
    if(worksheet.repair){
      const note=node('aside',undefined,'helper practice-repair-reference');note.dataset.repairReference='';
      note.append(node('strong','本次定向再练'),node('p',worksheet.repair.targets.map(t=>'原第'+(t.index+1)+'题 · '+t.topic).join('；')),
        node('p',worksheet.repair.notice));box.append(note);
    }
    worksheet.questions.forEach((question,index)=>{
      const card=node('section',undefined,'homework-question');
      card.append(node('h4','第 '+(index+1)+' 题 · '+question.topic));
      const statement=node('div',undefined,'markdown homework-statement');markdown(statement,question.question);card.append(statement);
      if(question.starter_code)card.append(node('pre',question.starter_code,'homework-code'));
      if(question.source_url) {
        try{const url=new URL(question.source_url);if(['http:','https:'].includes(url.protocol)){
          const link=node('a','题目出处');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';card.append(link);
        }}catch{/* A malformed source link must not stop answering. */}
      }
      const label=node('label',coding?'我的代码':'我的作答与思路'),input=node('textarea');
      input.rows=coding?10:5;input.maxLength=coding?2*1024*1024:100000;
      input.required=true;input.dataset.homeworkAnswer=index;
      input.placeholder=coding?'按题单语言填写代码。':'写出你的结论和推理步骤；不会的题请注明卡点。';
      input.value=draft?.answers?.[index]??'';if(coding){input.className='homework-code';input.spellcheck=false;}
      input.oninput=saveAnswers;label.append(input);card.append(label);box.append(card);
      if(!coding){const view=state.view,project=state.projectId;window.studyforgePracticeHints.append(card,worksheet,question,
        {api,active:()=>matches(project,worksheet.id,view)&&$('homeworkDialog').open});}
    });
    const language=languages[worksheet.questions[0]?.language];
    $('homeworkDescription').textContent=worksheet.questions.length+' 题 · '+
      (language?language[0]+' 作业；使用 '+language[1]+' 文件。':'逐题作答；完整提交后才解锁参考解析。');
    $('homeworkFile').accept=language?.[1]||'.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff';
    $('homeworkExtract').textContent=coding?'读取代码到答题框 · 不提交':'识别到答题框 · 不提交';
    $('homeworkAttemptOptions').hidden=coding;
    $('homeworkUsedNotes').value=draft?.used_notes||'';
    const savedMode=draft?.recovery_mode;
    $('homeworkRecoveryMode').value=['adaptive','strict'].includes(savedMode)?savedMode:
      worksheet.practice?.recovery_mode==='strict'?'strict':'adaptive';
    $('homeworkAnswerForm').hidden=Boolean(worksheet.homework)||worksheet.status!=='assigned';
    $('homeworkSubmit').disabled=state.busy.has('submit:'+worksheet.id);
    $('homeworkExtract').disabled=false;
    if(!worksheet.homework && worksheet.status!=='assigned') {
      $('homeworkResult').replaceChildren(node('p','这份题单已经在其他入口提交。请在项目成果中查看解析与反馈。','helper'));
    }
  }
  function download(artifact, label) {
    const link=node('a',label,'download-link');link.href='/api/artifacts/'+artifact.id+'/download';
    link.download=artifact.download_filename||artifact.title+'.'+artifact.format;return link;
  }
  function renderAttempt(attempt) {
    state.attempt=attempt;$('homeworkAnswerForm').hidden=true;
    const host=$('homeworkResult');host.replaceChildren();
    const status=node('p',labels[attempt.status]||attempt.status,'homework-status');
    host.append(status);
    if(attempt.version_notice)host.append(node('p',attempt.version_notice,'helper homework-version-notice'));
    if(attempt.conversation_title)host.append(node('p','来源对话：'+attempt.conversation_title,'helper'));
    if(attempt.score!==null && attempt.score!==undefined)host.append(node('strong',
      (attempt.provisional||attempt.grading_verification_required?'待核实参考分：':'本次评分：')+attempt.score+' / 100','homework-score'));
    const policy={adaptive:'本次低分处理：先找出问题，再选择怎么补学；不会自动加难。',strict:'本次低分处理：原有用自己的话讲解，再做进阶题流程。'}[attempt.recovery_mode];
    if(policy)host.append(node('p',policy,'helper'));
    if(attempt.is_regrade)host.append(node('p','本次是重新检查原作答的分数，不是新增作答；沿用已保存的原条件。','helper'));
    if(attempt.provisional && !attempt.grading_verification_required && attempt.score==null)
      host.append(node('p','运行验证尚未完成，本次提供静态代码反馈，没有最终分数。','helper'));
    const files=node('div',undefined,'item-actions');
    if(attempt.solution_artifact)files.append(download(attempt.solution_artifact,'① 原题和参考解析 · DOCX'));
    if(attempt.feedback_artifact)files.append(download(attempt.feedback_artifact,'② 批改与错题讲解 · DOCX'));
    if(attempt.solution_artifact||attempt.feedback_artifact){const read=node('button','按题回看');read.type='button';read.dataset.homeworkRead=attempt.id;files.append(read);}
    if(files.children.length)host.append(files);
    if(attempt.current_version_matches!==false && !attempt.feedback_artifact && !['failed','cancelled'].includes(attempt.status))host.append(node('p',
      attempt.waiting_for_causes?'错因尚未确认，批改文档暂不交付。下方反馈提交后自动继续。':
        '参考解析与导师批改是两份独立文档。电脑正在处理批改，可以关闭这个窗口继续学习。','helper'));
    if(attempt.error)host.append(node('p',attempt.error,'message-error'));
    if(attempt.can_retry) {
      const retry=node('button',attempt.status==='awaiting_grade_review'?'复核原评分':attempt.status==='cancelled'?'继续原批改':'重试原批改');retry.type='button';
      retry.onclick=async()=>{
        retry.disabled=true;const project=attempt.project_id,view=state.view;
        try {
          const result=await api('/api/homework/'+attempt.id+'/retry?project_id='+project,{method:'POST'});
          if(matches(project,attempt.exercise_set_id,view))renderAttempt(result);
          if(mobile.project?.id===project)await refreshProject();
        }catch(error){toast(error.message);}finally{retry.disabled=false;}
      };host.append(retry);
    }
    renderCauses(attempt);
    if(attempt.current_version_matches!==false && state.worksheet?.id===attempt.exercise_set_id && (attempt.repair_available||
      (state.worksheet.status==='retry_ready'&&attempt.status==='completed'))) {
      const action=state.worksheet.status==='retry_ready'?'advance':'repair';
      const button=node('button',action==='repair'?'按本次错因同难度再练':'继续生成进阶练习');button.type='button';
      button.disabled=attempt.waiting_for_causes||mobile.jobs.some(row=>row.kind===action&&row.set_id===attempt.exercise_set_id&&
        ['queued','running','paused','pausing'].includes(row.status));
      button.onclick=async()=>{
        if(action==='repair')return window.studyforgeRepairPicker.open(attempt.exercise_set_id);
        const payload=assessment();button.disabled=true;
        try{await api('/api/exercises/'+attempt.exercise_set_id+'/'+action,json('POST',payload));
          toast('练习生成已交给电脑后台；完成后出现在本项目题单中。');await refreshProject();
        }catch(error){toast(error.message);button.disabled=false;}
      };host.append(button);
    }
  }
  function collectCauses(attempt) {
    return [...$('homeworkCauseQuestions').querySelectorAll('[data-cause-index]')].map(card=>({
      index:Number(card.dataset.causeIndex),
      kinds:[...card.querySelectorAll('input:checked')].map(input=>input.value),
      text:card.querySelector('textarea').value
    }));
  }
  function queueCauseDraft(attempt, responses) {
    const payload={project:attempt.project_id,responses};
    state.causePayloads.set(attempt.id,payload);
    safeWrite(draftKey('causes',attempt.project_id,attempt.id),responses);
    clearTimeout(state.causeTimers.get(attempt.id));
    $('homeworkCauseSave').textContent='问卷草稿已保存在手机，正在同步到电脑…';
    state.causeTimers.set(attempt.id,setTimeout(()=>flushCauseDraft(attempt.id),350));
  }
  function flushCauseDraft(id) {
    clearTimeout(state.causeTimers.get(id));state.causeTimers.delete(id);
    const payload=state.causePayloads.get(id);if(!payload)return Promise.resolve();
    state.causePayloads.delete(id);
    const chain=(state.causeChains.get(id)||Promise.resolve()).catch(()=>{}).then(()=>
      api('/api/homework/'+id+'/draft?project_id='+payload.project,json('PUT',{responses:payload.responses})));
    state.causeChains.set(id,chain);
    chain.then(()=>{
      if(state.attempt?.id===id)$('homeworkCauseSave').textContent='问卷草稿已同步到电脑。';
    },()=>{
      if(state.attempt?.id===id)$('homeworkCauseSave').textContent='草稿已保存在手机；暂未同步到电脑。';
    });
    return chain.catch(()=>{});
  }
  function renderCauses(attempt) {
    $('homeworkCauses').hidden=!attempt.waiting_for_causes;
    if(!attempt.waiting_for_causes){state.causeSignature=null;return;}
    const signature=JSON.stringify([attempt.id,attempt.questions]);
    if(signature===state.causeSignature)return;
    state.causeSignature=signature;const host=$('homeworkCauseQuestions');host.replaceChildren();
    const local=safeRead(draftKey('causes',attempt.project_id,attempt.id),[]);
    const saved=new Map([...(attempt.cause_draft||[]),...(Array.isArray(local)?local:[])].map(row=>[row.index,row]));
    for(const question of attempt.questions) {
      const card=node('section',undefined,'homework-cause-question');card.dataset.causeIndex=question.index;
      card.append(node('h4','第 '+(question.index+1)+' 题 · '+question.topic));
      const statement=node('div',undefined,'markdown homework-statement');markdown(statement,question.question);card.append(statement);
      const answer=node('blockquote',question.student_answer,'homework-student-answer');card.append(node('small','你提交的作答：','helper'),answer);
      const clarification=node('div',undefined,'homework-clarification');markdown(clarification,question.prompt);card.append(clarification);
      const draft=saved.get(question.index);
      for(const choice of attempt.options) {
        const label=node('label',undefined,'check-line cause-choice'),input=node('input');input.type='checkbox';
        input.value=choice.id;input.checked=Boolean(draft?.kinds?.includes(choice.id));
        label.append(input,node('span',choice.label));card.append(label);
      }
      const label=node('label','其他补充：当时是怎么想的？'),text=node('textarea');
      text.rows=3;text.maxLength=3000;text.value=draft?.text||'';label.append(text);card.append(label);host.append(card);
    }
    $('homeworkCauseSubmit').disabled=false;$('homeworkCauseSave').textContent='可多选；不确定时可以如实说明，不必猜测原因。';
  }
  async function extractFile() {
    const worksheet=state.worksheet;if(!worksheet || worksheet.homework)return;
    const file=$('homeworkFile').files[0];if(!file)return toast('请先选择已完成的作答文件。');
    const coding=isCoding(worksheet),limit=(coding?2:100)*1024*1024;
    if(file.size>limit)return toast(coding?'代码文件最大 2 MB。':'作答识别文件最大 100 MB。');
    const project=state.projectId,id=worksheet.id,view=state.view,snapshot=assessment();
    const inputs=[...$('homeworkQuestions').querySelectorAll('[data-homework-answer]')],before=inputs.map(input=>input.value);
    const form=new FormData();form.append('file',file);
    for(const key of ['provider','model','reasoning_effort'])if(snapshot[key])form.append(key,snapshot[key]);
    const button=$('homeworkExtract');button.disabled=true;
    $('homeworkFileStatus').textContent=coding?'正在读取代码，不运行、不提交…':'正在识别作答，不补全、不评分、不提交…';
    try {
      const result=await api('/api/'+(coding?'coding/':'exercises/')+id+'/'+(coding?'preview':'extract-answers'),{method:'POST',body:form});
      if(!matches(project,id,view) || state.worksheet.homework)return;
      const answers=coding?[result.code]:result.answers;
      if(!Array.isArray(answers)||answers.length!==inputs.length||answers.some(answer=>typeof answer!=='string'))
        throw new Error('识别结果无法对应到全部题目，请手动填写。');
      const apply=()=>{inputs.forEach((input,index)=>input.value=answers[index]);$('homeworkComplete').checked=false;saveAnswers();};
      if(inputs.some((input,index)=>input.value!==before[index])) {
        const note=$('homeworkFileStatus');note.replaceChildren(node('span','识别完成，但你已修改作答。原输入已保留。'));
        const review=node('details'),summary=node('summary','查看识别结果');review.append(summary,node('pre',answers.map((answer,index)=>'第 '+(index+1)+' 题\n'+answer).join('\n\n'),'homework-code'));
        const use=node('button','用识别结果替换答题框');use.type='button';use.onclick=()=>{apply();note.textContent='已替换，请逐题核对后再提交。';};
        note.append(review,use);
      }else {
        apply();$('homeworkFileStatus').textContent=coding?'代码已读取（'+result.encoding+'），尚未提交。':
          '已识别到答题框，尚未提交。'+(result.uncertainties?.length?'需核对：'+result.uncertainties.join('；'):'请逐题核对识别结果。');
      }
    }catch(error){if(matches(project,id,view))$('homeworkFileStatus').textContent=error.message;toast(error.message);}
    finally{if(matches(project,id,view))button.disabled=false;}
  }
  async function submitAnswers(event) {
    event.preventDefault();const worksheet=state.worksheet;
    if(!worksheet || worksheet.homework || state.busy.has('submit:'+worksheet.id))return;
    if(!mobile.chat)return toast('请先打开一个学习对话。');
    const answers=[...$('homeworkQuestions').querySelectorAll('[data-homework-answer]')].map(input=>input.value);
    if(answers.some(answer=>!answer.trim()) || !$('homeworkComplete').checked)return toast('请逐题完成作答并确认提交。');
    const project=state.projectId,id=worksheet.id,view=state.view,snapshot=assessment(),coding=isCoding(worksheet);
    const usedNotes=$('homeworkUsedNotes').value,recoveryMode=$('homeworkRecoveryMode').value;saveAnswers();state.busy.add('submit:'+id);$('homeworkSubmit').disabled=true;
    $('homeworkResult').replaceChildren(node('p','正在保存作答并导出原题与参考解析…','helper'));
    const pendingSave=mobile.save;
    try {
      await pendingSave;let result;
      if(coding) {
        const extension=languages[worksheet.questions[0].language]?.[1];
        if(!extension)throw new Error('此语言暂未接入判题器，请在电脑端处理。');
        const form=new FormData();form.append('file',new Blob([answers[0]],{type:'text/plain;charset=utf-8'}),'my-answer'+extension);
        for(const [key,value] of Object.entries(snapshot))if(value!==null&&value!==undefined)form.append(key,String(value));
        result=await api('/api/coding/'+id+'/submit',{method:'POST',body:form});
      }else {
        const payload={...snapshot,answers,recovery_mode:recoveryMode};
        if(usedNotes!=='')payload.used_notes=usedNotes==='true';
        result=await api('/api/exercises/'+id+'/submit',json('POST',payload));
      }
      if(matches(project,id,view)) {state.worksheet.homework=result;renderAttempt(result);}
      toast(result.reused?'已恢复这份作业的原提交，不会重复批改。':'完整作答已保存，参考解析已提供；导师另行批改。');
      if(mobile.project?.id===project)await refreshProject();
    }catch(error){
      toast(error.message);
      if(matches(project,id,view))$('homeworkResult').replaceChildren(node('p',error.message+' 作答草稿已保留。','message-error'));
    }finally{state.busy.delete('submit:'+id);if(matches(project,id,view))$('homeworkSubmit').disabled=Boolean(state.worksheet.homework);}
  }
  async function submitCauses(event) {
    event.preventDefault();const attempt=state.attempt;
    if(!attempt?.waiting_for_causes || state.busy.has('causes:'+attempt.id))return;
    const responses=collectCauses(attempt);
    if(responses.some(row=>!row.kinds.length&&!row.text.trim()))return toast('请逐题选择错因或补充思路；不确定时可选择“仍不确定”。');
    const view=state.view;queueCauseDraft(attempt,responses);state.busy.add('causes:'+attempt.id);$('homeworkCauseSubmit').disabled=true;
    try {
      await flushCauseDraft(attempt.id);
      const result=await api('/api/homework/'+attempt.id+'/causes?project_id='+attempt.project_id,json('POST',{responses}));
      safeWrite(draftKey('causes',attempt.project_id,attempt.id),null);
      if(matches(attempt.project_id,attempt.exercise_set_id,view))renderAttempt(result);
      toast('错因反馈已保存，电脑继续原批改任务。');
      if(mobile.project?.id===attempt.project_id)await refreshProject();
    }catch(error){toast(error.message);}
    finally{state.busy.delete('causes:'+attempt.id);if(matches(attempt.project_id,attempt.exercise_set_id,view))$('homeworkCauseSubmit').disabled=false;}
  }
  function renderFeynman() {
    const worksheet=state.worksheet;if(!worksheet)return;
    const optional=['repair_required','repair_retry'].includes(worksheet.status);
    const active=['feynman_required','feynman_retry','repair_required','repair_retry'].includes(worksheet.status)&&
      (!worksheet.homework||worksheet.homework.status==='completed')&&worksheet.homework?.current_version_matches!==false;
    $('homeworkFeynman').hidden=!active;
    $('homeworkFeynmanHeading').textContent=optional?'可选：用自己的话巩固理解':'用自己的话重新讲清楚';
    $('homeworkFeynmanDescription').textContent=optional?'可先阅读错因补讲，按需同难度再练，也可自愿提交自己的讲解。不会自动要求做更难的题。':
      '按本次选择的原有流程，先讲清概念、条件、理由和适用边界；通过后可继续进阶练习。';
    const panel=$('homeworkFeynmanPanel'),panelKey=worksheet.id+':'+optional;
    if(panel.dataset.choice!==panelKey){panel.dataset.choice=panelKey;panel.open=!optional;}
    $('homeworkFeynmanToggle').hidden=!optional;
    const key=draftKey('feynman',state.projectId,worksheet.id);
    if($('homeworkFeynmanText').dataset.draftKey!==key) {
      $('homeworkFeynmanText').dataset.draftKey=key;$('homeworkFeynmanText').value=safeRead(key,'');
    }
    const occupied=mobile.jobs.some(row=>row.kind==='feynman'&&row.set_id===worksheet.id&&
      ['queued','running','paused','pausing'].includes(row.status));
    $('homeworkFeynmanSubmit').disabled=occupied||state.busy.has('feynman:'+worksheet.id);
    $('homeworkFeynmanSubmit').textContent=occupied?'讲解正在后台核查':'提交我的讲解';
    const signature=JSON.stringify([worksheet.id,state.view,worksheet.status,mobile.jobs
      .filter(row=>row.kind==='feynman'&&row.set_id===worksheet.id).map(row=>[row.id,row.status])]);
    if(active && signature!==state.feynmanSignature) {
      state.feynmanSignature=signature;
      const project=state.projectId,id=worksheet.id,view=state.view;
      api('/api/exercises/'+id+'/submissions').then(rows=>{
        if(!matches(project,id,view))return;
        const feedback=rows.find(row=>row.feynman?.feedback)?.feynman;
        if(feedback) {
          const content='**上次费曼讲解：'+feedback.score+'/100 · '+(feedback.passed?'已通过':'尚需改进')+'**\n\n'+feedback.feedback+
            (feedback.gaps?.length?'\n\n需要补齐：\n'+feedback.gaps.map(gap=>'- '+gap).join('\n'):'');
          markdown($('homeworkFeynmanFeedback'),content);
        }else $('homeworkFeynmanFeedback').replaceChildren();
      }).catch(()=>{
        if(matches(project,id,view)){state.feynmanSignature=null;$('homeworkFeynmanFeedback').textContent='上次讲解反馈暂未读取，联网后会重试。';}
      });
    }
  }
  async function submitFeynman(event) {
    event.preventDefault();const worksheet=state.worksheet,text=$('homeworkFeynmanText').value.trim();
    if(!worksheet || !text || state.busy.has('feynman:'+worksheet.id))return;
    const project=state.projectId,id=worksheet.id,view=state.view;
    const payload={...assessment(),explanation:text};state.busy.add('feynman:'+id);$('homeworkFeynmanSubmit').disabled=true;
    try {
      await api('/api/exercises/'+id+'/feynman',json('POST',payload));
      toast('费曼讲解已提交，在电脑后台核查。');
      if(mobile.project?.id===project)await refreshProject();
    }catch(error){toast(error.message);}
    finally{state.busy.delete('feynman:'+id);if(matches(project,id,view))renderFeynman();}
  }
  $('openHomework').onclick=()=>open().catch(error=>toast(error.message));
  $('homeworkBack').onclick=back;$('homeworkAnswerForm').onsubmit=submitAnswers;
  $('homeworkExtract').onclick=()=>extractFile().catch(error=>toast(error.message));
  $('homeworkUsedNotes').onchange=saveAnswers;
  $('homeworkRecoveryMode').onchange=saveAnswers;
  $('homeworkCausesForm').onsubmit=submitCauses;
  $('homeworkCauseQuestions').oninput=()=>{
    if(state.attempt?.waiting_for_causes)queueCauseDraft(state.attempt,collectCauses(state.attempt));
  };
  $('homeworkFeynmanForm').onsubmit=submitFeynman;
  $('homeworkFeynmanText').oninput=()=>{
    if(state.worksheet)safeWrite(draftKey('feynman',state.projectId,state.worksheet.id),$('homeworkFeynmanText').value);
  };
  const entry=node('button','提交作业 / 查看错因补讲');entry.type='button';entry.className='wide homework-options-entry';
  entry.id='homeworkFromOptions';entry.onclick=()=>open().catch(error=>toast(error.message));
  $('generateFromOptions').parentElement.before(entry);
  window.addEventListener('pagehide',()=>{saveAnswers();for(const id of state.causePayloads.keys())flushCauseDraft(id);});
  window.studyforgeRepairPicker?.configure({api,project:()=>mobile.project?.id,
    scope:()=>`${mobile.project?.id}:${mobile.chat?.id}:${mobile.epoch}`,selection:assessment,
    async launch(id,payload){await api('/api/exercises/'+id+'/repair',json('POST',payload));
      toast('所选卡点的练习已交给电脑后台，完成后出现在本项目题单中。');await refreshProject();}
  });
  window.studyforgeHomeworkReader?.configure({api,render:markdown,
    project:()=>mobile.project?.id,scope:()=>`${mobile.project?.id}:${mobile.chat?.id}:${mobile.epoch}`,
    async go(id,project){
      if(!mobile.authenticated||mobile.project?.id!==project)return false;
      if($('homeworkDialog').open)$('homeworkDialog').close();
      if(mobile.chat?.id!==id)await selectChat(id);
      return mobile.authenticated&&mobile.project?.id===project&&mobile.chat?.id===id;
    },
    draft(prefix){const input=$('prompt');if(!input.value.includes(prefix))input.value=prefix+'\n'+input.value;
      fitPrompt();saveDraft();input.focus();}
  });
  window.studyforgeMobileHomework={refresh,reset,open,openSet,openAttempt};
})();
