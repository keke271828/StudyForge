/* Live work belongs to its captured chat, never to whichever tab is open. */
const liveChats = new Map(), generationLaunches = new Set(), readingStarts = new Map();
let schedulingSettingsSave = Promise.resolve(), schedulingSettingsRevision = 0;
let schedulingSettingsPending = 0;
const schedulingKeys=['task_parallel_enabled','model_concurrency','generation_parallel','task_auto_retry','task_retry_limit'];
let schedulingConfirmed={task_parallel_enabled:true,model_concurrency:2,generation_parallel:false,task_auto_retry:true,task_retry_limit:5};
const isChatBusy = (id = state.conversation) => liveChats.has(id);
const inCapturedChat = request => state.project?.id === request.project_id && state.conversation === request.conversation_id;
function captureStudyRequest() {
  return {project_id:state.project.id, conversation_id:state.conversation,
    source_ids:[...state.selected], provider:$('provider').value, ...generationSelection(),
    learning_mode:currentLearningMode(), explanation_style:currentExplanationStyle(), output_language:$('outputLanguage').value};
}
function syncWorkControls() {
  if(typeof conversationUI !== 'undefined') setConversationLoading(conversationUI.restoring);
  const hint=$('conversationWorkStatus');
  const live=liveChats.get(state.conversation);
  if(hint)hint.textContent=live?.cancelRequested?'正在停止本次回复…':live?.waitingApproval?'等待你审批 · 批准后自动继续原指令':isChatBusy()?'导师正在回复 · 可停止、切换其他对话或发起生成':'';
}
function waitForChatStep(promise, live) {
  const signal=live.controller.signal;
  return new Promise((resolve,reject)=>{
    const abort=()=>reject(new DOMException('本次回复已停止','AbortError'));
    signal.addEventListener('abort',abort,{once:true});
    Promise.resolve(promise).then(resolve,reject).finally(()=>signal.removeEventListener('abort',abort));
    if(signal.aborted)abort();
  });
}
function attachLiveReply(row) {
  const live=liveChats.get(row.id);
  if(!live||live.finished)return;
  if(live.output?.isConnected)return;
  if(live.text && !row.messages.some(item=>item.role==='user'&&item.content===live.text))live.userNode=message('user',live.text).parentElement;
  live.output=message('assistant',live.answer||'');
  showReplyStatus(live.output,live.status||'等待导师回复…');
}
function paintLiveReply(live,force=false) {
  if(!inCapturedChat(live.request)||!live.output?.isConnected){clearTimeout(live.paintTimer);live.paintTimer=null;return;}
  const now=performance.now(),wait=120-(now-(live.paintedAt??-120));
  if(!force&&wait>0){
    if(!live.paintTimer)live.paintTimer=setTimeout(()=>{live.paintTimer=null;paintLiveReply(live,true);},wait);
    return;
  }
  clearTimeout(live.paintTimer);live.paintTimer=null;
  if(live.output.dataset.rawText===live.answer)return;
  const host=$('messages'),atEnd=host.scrollHeight-host.scrollTop-host.clientHeight<100;
  renderLessonStream(live.output,live.answer);
  live.paintedAt=performance.now();
  if(atEnd)host.scrollTop=host.scrollHeight;
}
async function consumeTutorResponse(response,live) {
  if(!response.ok){const payload=await response.json();const failure=new Error(payload.detail||response.statusText);throw window.studyforgeOperationErrors?.capture(failure,{status:response.status,path:'/api/chat/stream'})||failure;}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',done=false;
  try{
    while(!done){
      const packet=await reader.read();done=packet.done;buffer+=decoder.decode(packet.value||new Uint8Array(),{stream:!done});
      const lines=buffer.split('\n');buffer=lines.pop()||'';
      if(done&&buffer.trim()){lines.push(buffer);buffer='';}
      for(const line of lines){
        if(!line)continue;const event=JSON.parse(line);
        if(event.type==='delta'||event.type==='replace'){
          live.answer=event.type==='replace'?event.value:live.answer+event.value;paintLiveReply(live,event.type==='replace');
        }else if(event.type==='library')window.libraryShowMatches?.(event.value,live.request);
        else if(event.type==='job')trackJob(event.value).catch(error);
        else if(event.type==='tool'){
          if(event.value.status==='completed'&&event.value.result?.library_history)
            window.libraryShowMatches?.({history:event.value.result.library_history},live.request);
          live.approvalOperations??=new Map();
          if(event.value.status==='waiting_approval'){
            live.approvalOperations.set(event.value.operation_id||event.value.id,event.value);
            live.waitingApproval=true;live.status='等待你审批 · 任务已暂停等待，批准后自动继续';
          }else if(live.approvalOperations.has(event.value.id)&&['running','completed','failed'].includes(event.value.status)){
            live.approvalOperations.delete(event.value.id);live.waitingApproval=live.approvalOperations.size>0;
            if(!live.waitingApproval)live.status=event.value.status==='failed'?'审批操作未执行，导师正在处理结果…':'审批已通过，正在继续原指令…';
          }
          if(inCapturedChat(live.request)&&live.output?.isConnected){
            // The provider's delayed synthetic progress cannot resolve a runtime approval.
            if(!live.waitingApproval||event.value.status==='waiting_approval')showToolActivity(live.output,event.value);
            showReplyStatus(live.output,live.status);syncWorkControls();
          }
        }
        else if(event.type==='status'){live.status=event.value;if(inCapturedChat(live.request)&&live.output?.isConnected)showReplyStatus(live.output,event.value);}
        else if(event.type==='done'){paintLiveReply(live,true);live.finished=true;live.status='';if(live.output?.isConnected)showReplyStatus(live.output,'');}
        else if(event.type==='error')throw new Error(event.value);
      }
    }
  }finally{clearTimeout(live.paintTimer);live.paintTimer=null;paintLiveReply(live,true);
    live.status='';live.waitingApproval=false;live.approvalOperations?.clear();
    if(live.output?.isConnected)showReplyStatus(live.output,'');reader.releaseLock();}
}
async function readDependency(request,force=false) {
  if(!request.source_ids.length)return {};
  const key=JSON.stringify([request.project_id,request.conversation_id,[...request.source_ids].sort(),request.provider,request.model,request.reasoning_effort]);
  if(!force&&readingStarts.has(key))return readingStarts.get(key);
  const promise=(async()=>{
    if(!force){const restored=await api('/api/read/restore',jsonOptions('POST',request));if(restored.reading)return {reading:restored.reading};}
    return api('/api/read',jsonOptions('POST',request));
  })();
  readingStarts.set(key,promise);
  promise.finally(()=>{if(readingStarts.get(key)===promise)readingStarts.delete(key);}).catch(()=>{});
  return promise;
}
function applySchedulingSettings(config,revision=schedulingSettingsRevision,force=false) {
  if(!force&&(schedulingSettingsPending||revision!==schedulingSettingsRevision)){
    if(state.settings)Object.assign(state.settings,schedulingConfirmed);
    return;
  }
  for(const key of schedulingKeys)schedulingConfirmed[key]=config[key]??schedulingConfirmed[key];
  if(state.settings)Object.assign(state.settings,schedulingConfirmed);
  $('taskParallelEnabled').checked=config.task_parallel_enabled!==false;
  $('modelConcurrency').value=config.model_concurrency??2;
  $('defaultGenerationParallel').checked=!!config.generation_parallel;
  if($('taskAutoRetry'))$('taskAutoRetry').checked=config.task_auto_retry!==false;
  if($('taskRetryLimit'))$('taskRetryLimit').value=config.task_retry_limit??5;
  if(!$('generationParallel').dataset.edited)$('generationParallel').checked=!!config.generation_parallel;
  renderParallelHint();
}
function renderParallelHint(){
  const on=$('generationParallel').checked,enabled=state.settings?.task_parallel_enabled!==false,limit=state.settings?.model_concurrency??2;
  $('generationParallelHint').textContent=!enabled?'已关闭同时处理：AI 请求会逐个执行。':on?
    limit===1?'目前最多同时处理 1 个 AI 请求。想同时生成多个部分，可在任务安排中提高上限。':`不同章节、配套题和部分检查可以同时做，最多 ${limit} 个 AI 请求。需要前一步结果的内容仍会等待。`:
    '这份文档按章依次写，写完再出题；其他无关任务仍可同时进行。';
}
async function saveSchedulingSettings(){
  const payload={task_parallel_enabled:$('taskParallelEnabled').checked,model_concurrency:Number($('modelConcurrency').value),generation_parallel:$('defaultGenerationParallel').checked,
    task_auto_retry:$('taskAutoRetry').checked,task_retry_limit:Number($('taskRetryLimit').value)};
  const revision=++schedulingSettingsRevision;schedulingSettingsPending++;$('schedulingSaveStatus').textContent='正在保存…';
  schedulingSettingsSave=schedulingSettingsSave.catch(()=>{}).then(async()=>{
    try{const config=await api('/api/settings',jsonOptions('PUT',payload));for(const key of schedulingKeys)schedulingConfirmed[key]=config[key];Object.assign(state.settings,schedulingConfirmed);
      if(revision===schedulingSettingsRevision){applySchedulingSettings(config,revision,true);$('schedulingSaveStatus').textContent='已保存。等待中的任务会使用新上限，正在进行的请求会正常完成。';}
    }catch(failure){if(revision===schedulingSettingsRevision){applySchedulingSettings(schedulingConfirmed,revision,true);$('schedulingSaveStatus').textContent='保存失败，已恢复上次设置';}error(failure);}
    finally{schedulingSettingsPending--;}
  });return schedulingSettingsSave;
}
let schedulingPoll = null;
function refreshSchedulingStatus(){
  if(schedulingPoll)return schedulingPoll;
  schedulingPoll=loadSchedulingStatus().finally(()=>{schedulingPoll=null;});return schedulingPoll;
}
async function loadSchedulingStatus(){
  if(!state.ready)return;
  const projectId=state.project?.id;
  const info=await api('/api/scheduling'+(projectId?'?project_id='+encodeURIComponent(projectId):''));
  const model=info.resources.model;
  $('schedulingStatus').textContent=`AI 正在处理 ${model.active}/${model.limit} · 等待 ${model.queued}`;
  if(projectId!==state.project?.id)return;
  $('schedulingResources').textContent=['network','media','source_prepare','image_prepare','image','container'].map((key,index)=>`${['网页读取','本地 OCR／语音与媒体处理','原文准备','视觉资料准备','图片生成','容器判题'][index]} ${info.resources[key].active}/${info.resources[key].limit}${info.resources[key].queued?' · '+info.resources[key].queued+' 项排队':''}`).join(' · ');
  const host=$('executionTimeline');
  const signature=JSON.stringify(info.spans.map(span=>[span.id,span.segment,span.status,span.started_at,span.ended_at]));
  if(host.dataset.signature===signature)return;host.dataset.signature=signature;
  const labels={queued:'排队',running:'运行',completed:'完成',failed:'失败',cancelled:'取消',interrupted:'中断',tool_wait:'执行工具，已释放模型名额'};
  host.innerHTML=info.spans.slice(0,40).map(span=>`<li><strong>${escapeHtml(executionLabel(span.label||span.resource))}</strong><span>${escapeHtml(labels[span.status]||span.status)}${span.provider?' · '+escapeHtml(span.provider):''}</span><small>开始 ${span.started_at?new Date(span.started_at).toLocaleTimeString():'等待中'} · 结束 ${span.ended_at?new Date(span.ended_at).toLocaleTimeString():'—'}${span.duration_ms?' · '+(span.duration_ms/1000).toFixed(2)+' 秒':''}</small></li>`).join('')||'<li>暂无运行记录。启动任务后显示实际模型请求时间，不包含对话内容。</li>';
}
function executionLabel(label){
  const chapter=label.match(/^chapter:(\d+)(:image)?$/);
  if(chapter)return `第 ${chapter[1]} 部分${chapter[2]?' · 检查图片':'讲解与核查'}`;
  return {writer:'讲解整理与全文总结','writer:image':'检查原文图片',exercise:'习题生成与核查',reading:'资料通读',knowledge:'知识结构整理',generate:'成果生成',read:'资料通读',model:'模型请求'}[label]||label;
}
function initializeParallel(){
  Object.defineProperty(state,'busy',{get:()=>isChatBusy(),configurable:true});
  const config=document.createElement('section');config.className='settings-card scheduling-card';
  config.innerHTML='<div class="settings-card-head"><span>任务安排</span><h3>哪些任务可以一起做？</h3><p>可以一边聊天，一边生成其他文档。不同对话和题单各用自己的资料，不会混在一起。</p></div><label class="setting-check"><input id="taskParallelEnabled" type="checkbox" checked>允许独立任务并行</label><label>最多同时使用几个 AI 请求<input id="modelConcurrency" type="number" min="1" max="8" value="2"></label><label class="setting-check"><input id="defaultGenerationParallel" type="checkbox">新任务默认允许多个部分同时生成</label><p class="small-note">关闭后，AI 请求会一个接一个执行。修改上限不会打断正在回复的 AI；同一对话的连续回复和同一套题的重复批改仍按顺序处理。</p><button id="saveScheduling" type="button" class="secondary">保存调度设置</button><p id="schedulingSaveStatus" class="small-note" role="status"></p><details><summary>查看各步骤用时</summary><p id="schedulingResources" class="small-note"></p><ol id="executionTimeline" class="execution-timeline"></ol></details>';
  $('settings-generation').append(config);
  const retries=document.createElement('div');retries.className='retry-settings';
  retries.innerHTML='<label class="setting-check"><input id="taskAutoRetry" type="checkbox" checked>任务失败自动重试</label><label>每项任务最多重试<input id="taskRetryLimit" type="number" min="5" max="20" value="5">次（不包括首次执行）</label><p class="small-note">网络中断、超时、服务暂时故障和无效模型响应默认重试 5 次，复用已完成步骤。等待重试不占模型名额；可以暂停或取消。账户配置、访问限制、原文件变更和实质内容错误需先处理原因。改动只影响新任务。</p>';
  $('saveScheduling').before(retries);
  const option=document.createElement('div');option.className='parallel-options';
  option.innerHTML='<label class="setting-check"><input id="generationParallel" type="checkbox">同时生成多个部分</label><small id="generationParallelHint"></small>';
  $('generate').closest('.generation-bar').after(option);
  const sourceChoice=document.createElement('label');sourceChoice.className='chat-source-choice';sourceChoice.innerHTML='<span>这条消息使用哪些资料？</span><select id="chatSourceMode"><option value="selected">引用已选资料</option><option value="none">暂不使用资料 · 可以聊其他问题</option></select>';
  $('prompt').before(sourceChoice);
  const work=document.createElement('small');work.id='conversationWorkStatus';work.className='small-note';work.setAttribute('role','status');$('conversationTitle').after(work);
  const pill=document.createElement('button');pill.id='schedulingStatus';pill.type='button';pill.className='scheduling-status';pill.textContent='模型请求 0/2';pill.title='查看正在处理的任务';
  pill.onclick=()=>{showView('settings');showSettingsSection('generation');config.scrollIntoView({block:'start'});};$('status').after(pill);
  $('generationParallel').onchange=()=>{$('generationParallel').dataset.edited='true';renderParallelHint();};
  $('saveScheduling').onclick=saveSchedulingSettings;
  setInterval(()=>refreshSchedulingStatus().catch(()=>{}),1500);
}
