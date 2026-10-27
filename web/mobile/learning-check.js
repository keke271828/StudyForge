/* Optional goal checks. Planning data loads only when this control opens. */
(()=>{
 const state={project:null,conversation:null,items:[],tasks:[],ticket:0,busy:false};
 const host=document.createElement('details');host.className='questionnaire-focus mobile-goal-check';host.id='mobileGoalCheck';
 const summary=document.createElement('summary');summary.textContent='自愿检查理解';host.append(summary);
 const label=document.createElement('label');label.textContent='本项目的学习目标';
 const select=document.createElement('select');select.id='mobileGoalCheckSelect';label.append(select);host.append(label);
 const info=document.createElement('p');info.className='helper';info.id='mobileGoalCheckInfo';host.append(info);
 const actions=document.createElement('div');actions.className='row-actions';
 const ordinary=document.createElement('button');ordinary.type='button';ordinary.id='mobileGoalCheckStandard';ordinary.textContent='三题理解检查';
 const transfer=document.createElement('button');transfer.type='button';transfer.id='mobileGoalCheckTransfer';transfer.textContent='换个情境再测';
 const reload=document.createElement('button');reload.type='button';reload.className='text-button';reload.textContent='刷新目标';reload.id='mobileGoalCheckReload';
 actions.append(ordinary,transfer);host.append(actions,reload);$('optionsDialog').querySelector('.sheet-body').prepend(host);
 function controls(){
  const item=state.items.find(g=>g.id===select.value),scope=state.project===mobile.project?.id&&state.conversation===mobile.chat?.id;
  const unavailable=!item||item.paused||!item.sources.length||item.sources.some(s=>!s.available);
  ordinary.disabled=state.busy||!scope||unavailable||state.tasks.some(t=>t.goal_id===item?.id&&(t.kind==='standard'||!t.kind));
  transfer.disabled=state.busy||!scope||unavailable||!item?.evidence.some(e=>e.latest&&!e.latest.pending)||state.tasks.some(t=>t.goal_id===item?.id&&t.kind==='new_context');
  select.disabled=state.busy;reload.disabled=state.busy;
  if(item)info.textContent=item.criterion+'\n'+item.recommendation.text+'\n换个情境再测保持参考难度，改变条件、表示或论证任务。解析和情境变化说明在完整提交后开放。';
 }
 async function load(){
  if(state.busy)return;
  if(!mobile.authenticated||!mobile.project||!mobile.chat)return;
  const project=mobile.project.id,chat=mobile.chat.id,epoch=mobile.epoch,ticket=++state.ticket,old=select.value;
  ordinary.disabled=transfer.disabled=true;info.textContent='正在读取当前项目的目标；这一步不调用 AI。';
  const data=await api('/api/projects/'+project+'/learning-goals?conversation_id='+chat);
  if(ticket!==state.ticket||epoch!==mobile.epoch||project!==mobile.project?.id||chat!==mobile.chat?.id)return;
  state.project=project;state.conversation=chat;state.items=data.items;state.tasks=data.tasks;
  select.replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent='选择一个目标（可在电脑的学习路线中建立）';select.append(empty);
  for(const item of data.items){const option=document.createElement('option');option.value=item.id;option.textContent=item.name+' · '+item.domain+(item.paused?' · 暂缓':'');select.append(option);}
  select.value=data.items.some(g=>g.id===old)?old:data.focused_goal_id||'';
  if(!select.value)info.textContent='先选择目标。检查是自愿的，不因阅读或生成讲解就自动出题。换个情境再测需要先完成当前范围的一份检查。';
  controls();
 }
 async function launch(kind){
  if(state.busy)return;const item=state.items.find(g=>g.id===select.value);if(!item)return;
  if(state.project!==mobile.project?.id||state.conversation!==mobile.chat?.id){await load();return toast('已切换项目或对话，请重新确认学习目标。');}
  const project=state.project,chat=state.conversation,epoch=mobile.epoch,ticket=++state.ticket;
  const payload={version:item.version,conversation_id:chat,provider:$('provider').value,model:$('model').value.trim()||null,
    reasoning_effort:$('effort').value||null,explanation_style:$('explanationStyle').value,output_language:$('outputLanguage').value,kind};
  state.busy=true;controls();
  try{
   await mobile.save;
   const result=await api('/api/projects/'+project+'/learning-goals/'+item.id+'/check',json('POST',payload));
   if(project!==mobile.project?.id||chat!==mobile.chat?.id||epoch!==mobile.epoch)return;
   state.tasks.push({goal_id:item.id,kind,status:'queued',job_id:result.job_id});
   toast(result.reused?'已找到正在进行的同类检查。':'检查已启动，电脑继续生成；在成果与作业中查看，提交前不显示答案。');
   if($('optionsDialog').open)$('optionsDialog').close();await refreshProject();
  }catch(error){if(epoch===mobile.epoch)toast(error.message);}
  finally{if(ticket===state.ticket){state.busy=false;controls();}}
 }
 select.onchange=controls;ordinary.onclick=()=>launch('standard');transfer.onclick=()=>launch('new_context');
 reload.onclick=()=>load().catch(error=>toast(error.message));
 host.addEventListener('toggle',()=>{if(host.open)load().catch(error=>toast(error.message));});
 $('optionsDialog').addEventListener('close',()=>{host.open=false;});
 window.studyforgeMobileGoalChecks={reset(){state.ticket++;state.project=null;state.conversation=null;state.items=[];state.tasks=[];state.busy=false;host.open=false;select.replaceChildren();controls();}};
 controls();
})();
