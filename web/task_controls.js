/* Shared controls for durable tasks; selections remain fixed at task creation. */
const taskUI={watching:new Set(),jobs:new Map()};
const pendingTaskStatuses=['queued','running','pausing','paused'];
function rememberTask(job){
  // Full detail can contain a lesson and private dialogue. This cache is for controls only.
  const fields=['id','project_id','kind','status','progress','error','created_at','updated_at','can_pause',
    'recovery','retry','stage','request_status','set_id','conversation_id','provider','model','reasoning_effort','reading_id','only_exercises','waiting_for_causes','homework_attempt_id'];
  const compact=Object.fromEntries(fields.filter(key=>job[key]!==undefined).map(key=>[key,job[key]]));
  compact.payload=Object.fromEntries(['conversation_id','reading_id','set_id','only_exercises','provider','model','reasoning_effort'].filter(key=>job.payload?.[key]!==undefined).map(key=>[key,job.payload[key]]));
  compact.result=Object.fromEntries(['stage','request_status','reading_id','waiting_for_causes','homework_attempt_id'].filter(key=>job.result?.[key]!==undefined).map(key=>[key,job.result[key]]));
  taskUI.jobs.delete(job.id);taskUI.jobs.set(job.id,compact);
  const historical=[...taskUI.jobs.values()].filter(row=>!pendingTaskStatuses.includes(row.status)&&row.id!==state.reading?.job_id&&row.id!==knowledgeState.jobId);
  for(const row of historical.slice(0,Math.max(0,historical.length-128)))taskUI.jobs.delete(row.id);
  return compact;
}
function taskMatchesConversation(job){
  return state.project?.id===job.project_id&&Boolean(state.conversation)&&
    (job.conversation_id||job.payload?.conversation_id)===state.conversation;
}
function restoreReadingTask(row){
  const job=row.reading_task;
  if(!job||!taskMatchesConversation(job)||state.reading?.job_id!==job.id)return;
  rememberTask(job);renderReadingStatus();
  if(['queued','running','pausing'].includes(job.status))watchOutcomeTask(job.id).catch(error);
}
function readingTaskMatchesCurrent(job){
  if(job.kind!=='read'||!state.project||!job.payload?.source_ids)return false;
  const current=captureStudyRequest(),saved=job.payload;
  return job.project_id===current.project_id&&saved.conversation_id===current.conversation_id&&
    saved.provider===current.provider&&(saved.model||'')===(current.model||'')&&
    (saved.reasoning_effort||'')===(current.reasoning_effort||'')&&
    JSON.stringify([...saved.source_ids].sort())===JSON.stringify([...current.source_ids].sort())&&
    (!state.reading?.job_id||state.reading.job_id===job.id);
}

function taskControlMarkup(job){
  if(job.status==='failed'&&job.recovery?.available)return `<button type="button" class="secondary" data-task-control="${escapeHtml(job.id)}" data-action="retry" title="${escapeHtml(job.recovery.reason)}">重试未完成步骤</button>`;
  if(job.status==='paused'&&(job.waiting_for_causes||job.result?.waiting_for_causes))return `<button type="button" data-homework-open="${escapeHtml(job.homework_attempt_id||job.result.homework_attempt_id)}">填写错因问卷</button>`;
  if(!job.can_pause||!pendingTaskStatuses.includes(job.status))return '';
  const resume=['pausing','paused'].includes(job.status);
  return `<button type="button" class="secondary" data-task-control="${escapeHtml(job.id)}" data-action="${resume?'resume':'pause'}">${resume?'继续任务':'暂停任务'}</button>`;
}

function syncTaskWidgets(jobs){
  for(const job of jobs)rememberTask(job);
  let panel=$('exerciseJobs');
  if(!panel){panel=document.createElement('div');panel.id='exerciseJobs';panel.className='inline-task-list';$('exercises').before(panel);}
  const rows=jobs.filter(job=>job.kind==='coding_generate'||job.set_id);
  panel.innerHTML=rows.filter(job=>pendingTaskStatuses.includes(job.status)||job.status==='failed').map(job=>
    `<section class="inline-task" data-inline-task="${escapeHtml(job.id)}"><div><strong>${escapeHtml(taskLabel(job))}</strong><small>${job.status==='paused'?'已暂停，进度保留':job.status==='pausing'?'正在暂停，等待当前步骤保存':job.status==='failed'?escapeHtml(window.studyforgeOperationErrors?.summary(job.error)||job.error):`${Number(job.progress)||0}%`}</small>${window.studyforgeTaskRetry?.summary(job)?`<small class="task-retry-status" role="status">${escapeHtml(window.studyforgeTaskRetry.summary(job))}</small>`:''}</div>${taskControlMarkup(job)}</section>`).join('');
  for(const job of rows)if(job.status==='failed')window.studyforgeOperationErrors?.attach(panel.querySelector(`[data-inline-task="${job.id}"]`),job.error||'任务失败');
  const reading=state.reading;
  const readButton=$('readingTaskControl');
  if(readButton){
    const job=reading?.job_id?taskUI.jobs.get(reading.job_id)||reading:null;
    readButton.hidden=!job||(!pendingTaskStatuses.includes(job.status)&&!job.recovery?.available);
    if(!readButton.hidden){readButton.dataset.taskControl=reading.job_id;readButton.dataset.action=job.status==='failed'?'retry':['pausing','paused'].includes(job.status)?'resume':'pause';readButton.textContent=job.status==='failed'?'重试未完成的通读':readButton.dataset.action==='resume'?'继续通读':'暂停通读';}
  }
  const knowledgeButton=$('knowledgeTaskControl'),structure=taskUI.jobs.get(knowledgeState.jobId);
  if(knowledgeButton){knowledgeButton.hidden=!structure||(!pendingTaskStatuses.includes(structure.status)&&!structure.recovery?.available);
    if(!knowledgeButton.hidden){knowledgeButton.dataset.taskControl=structure.id;knowledgeButton.dataset.action=structure.status==='failed'?'retry':['pausing','paused'].includes(structure.status)?'resume':'pause';knowledgeButton.textContent=structure.status==='failed'?'重试未完成的整理':knowledgeButton.dataset.action==='resume'?'继续整理':'暂停整理';}}
  if(typeof renderKnowledgeActions==='function')renderKnowledgeActions();
}

async function changeTask(jobId,action){
  const row=taskUI.jobs.get(jobId)||{id:jobId},projectId=row.project_id||state.project?.id;
  const result=action==='retry'?await window.studyforgeTaskRetry.manual(api,row,projectId):await api(`/api/jobs/${jobId}/${action}`,{method:'POST'});
  toast(action==='pause'?'已请求暂停。当前步骤保存后会停下，之后可点“继续”。':action==='retry'?'已接着原任务重试，资料、模型和要求沿用原选择。':'接着上次保存的进度继续');
  const job=await window.studyforgeRefresh.pollTask(api,jobId);rememberTask(job);
  if(state.reading?.job_id===jobId){state.reading={...state.reading,status:job.status,...job.result};renderReadingStatus();}
  await refreshArtifacts();
  if(action==='resume'||action==='retry'){
    watchOutcomeTask(jobId).catch(error);
  }
  return result;
}

async function launchOutcomeTask(url,body){
  const result=await api(url,body);
  if(!result.job_id)return result;
  toast('任务已启动。可在本页或“成果文档”暂停、继续；隐藏到托盘后仍会运行。');
  await refreshArtifacts();
  if(result.exercise_set_id){await refreshConversationMessages();await refreshExercises();}
  watchOutcomeTask(result.job_id).catch(error);
  return result;
}

async function watchOutcomeTask(jobId){
  if(taskUI.watching.has(jobId))return;
  taskUI.watching.add(jobId);
  try{
    for(;;){
      const job=await window.studyforgeRefresh.pollTask(api,jobId);rememberTask(job);
      if(state.project?.id===job.project_id){
        const rows=[...taskUI.jobs.values()].filter(x=>x.project_id===job.project_id);
        syncTaskWidgets(rows);
        if(job.kind==='read'&&state.reading?.job_id===jobId){state.reading={...state.reading,status:job.status,progress:job.progress,...job.result,error:job.error};renderReadingStatus();}
        if(job.kind==='knowledge'&&knowledgeState.jobId===jobId&&$('knowledgeDialog').open)$('knowledgeStatus').textContent=`${taskLabel(job)} · ${job.progress}%${job.status==='paused'?' · 已暂停':''}`;
      }
      if(['completed','failed','paused','cancelled'].includes(job.status)){
        if(state.project?.id===job.project_id){
          await Promise.all([refreshArtifacts(),refreshExercises(),refreshConversations()]);
          if(state.project?.id!==job.project_id)return job;
          if(job.kind==='homework_grade'&&taskMatchesConversation(job))await refreshConversationMessages();
          if(job.status==='completed'){
            await refreshSources();
            if(state.project?.id!==job.project_id)return job;
            if(job.kind==='generate'&&taskMatchesConversation(job))await refreshConversationMessages();
            if(readingTaskMatchesCurrent(job)){state.reading={job_id:jobId,status:job.status,progress:job.progress,...job.result};renderReadingStatus();saveConversation({reading_id:job.result.reading_id});}
            if(job.kind==='knowledge'&&knowledgeState.jobId===jobId&&knowledgeState.scope===materialScope()&&knowledgeState.readingId===job.payload.reading_id&&$('knowledgeDialog').open){
              const token=knowledgeState.token,scope=materialScope();
              const saved=await api(knowledgeMapPath(job.payload.reading_id,job.payload));
              if(token===knowledgeState.token&&scope===materialScope()&&$('knowledgeDialog').open)renderKnowledge(saved);
            }
            const output=job.result.output;
            const setId=output?.next_set?.id||output?.exercise_set?.id||(job.kind==='coding_generate'?output?.id:job.payload?.set_id);
            if(setId&&state.view==='exercises'&&taskMatchesConversation(job))await openSet(setId,true);
            if(taskMatchesConversation(job))toast(output?.score!=null?`批改已完成 · ${output.score} 分`:'任务已完成，结果已保存');
            else toast('本项目另一项任务已完成，可到“成果文档”查看来源对话和结果。');
          }else if(job.status==='failed'){
            if(taskMatchesConversation(job))error(new Error(job.error||'任务失败'));
            else toast('本项目另一项任务未完成，可到“成果文档”查看原因和来源对话。');
          }
        }
        return job;
      }
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
  }finally{taskUI.watching.delete(jobId);}
}

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-task-control]');if(!button)return;
  const jobId=button.dataset.taskControl,action=button.dataset.action;button.disabled=true;
  changeTask(jobId,action).catch(error).finally(()=>{if(button.isConnected)button.disabled=false;});
});
