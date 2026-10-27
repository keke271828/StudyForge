/* Load diagnostics only when requested; never add another polling loop. */
(() => {
  const labels={original_read:'读取原文件，检查是否有更新',audio_extract:'完整音轨提取',speech:'语音阶段整体（含以下分项）',
    speech_wait:'等待本机识别引擎',speech_load:'加载语音模型，检查可用设备',speech_decode:'完整音轨识别',
    frame_extract:'从视频中抽取关键画面',video_ocr:'识别画面中的文字',model:'模型请求',document_export:'成果排版',
    media:'电脑提取资料内容的总用时',image_prepare:'图片编码',image:'图片处理',network:'联网操作',container:'在隔离环境中运行代码测试',vision_wait:'使用已经读过的相同画面',
    source_prepare:'整理原文、图片和讲解分段'};
  let dialog,body,status,title,target,revision=0;
  const element=(tag,content,className)=>{const node=document.createElement(tag);if(content!=null)node.textContent=content;if(className)node.className=className;return node;};
  function duration(value){const seconds=Math.max(0,Number(value)||0)/1000;return seconds>=60?`${Math.floor(seconds/60)} 分 ${(seconds%60).toFixed(1)} 秒`:`${seconds.toFixed(1)} 秒`;}
  function setup(){
    if(dialog)return;
    dialog=element('dialog',null,'task-timing-dialog');dialog.setAttribute('aria-label','任务耗时详情');
    const header=element('header');title=element('h2','任务耗时详情');const close=element('button','关闭');close.type='button';close.onclick=()=>dialog.close();header.append(title,close);
    status=element('p','');status.setAttribute('role','status');body=element('div',null,'task-timing-body');
    const refresh=element('button','刷新耗时');refresh.type='button';refresh.onclick=()=>load();
    dialog.append(header,status,body,refresh);dialog.addEventListener('close',()=>{if(dialog.open)return;revision++;target=null;});document.body.append(dialog);
  }
  function render(data){
    body.replaceChildren();body.append(element('p',`从任务创建起经过 ${duration(data.wall_ms)}（包含暂停、审批和重试等待）`,'task-timing-total'));
    const reuse=data.vision_reuse;
    const asr=data.asr_execution;
    if(asr){
      const card=element('section',null,'task-timing-card');card.dataset.asrExecution='true';
      const devices={cpu:'CPU',cuda:'GPU',auto:'自动选择'};
      card.append(element('strong',data.asr_record_count>1?'最近一次完整音轨识别':'实际语音识别'),element('p',`模型 ${asr.actual_model||'未记录'} · 实际设备 ${devices[asr.actual_device]||'未记录'}`),
        element('small',`识别范围 ${asr.audio_seconds??'未记录'} 秒 · 识别参数 beam size ${asr.beam_size??'未记录'} · ${asr.compute_type||'精度未记录'}`));
      if(asr.fallback_reason)card.append(element('p',asr.fallback_reason,'task-timing-note'));
      body.append(card);
    }
    if(reuse){
      const card=element('section',null,'task-timing-card');card.dataset.visionReuse='true';
      const hits=(Number(reuse.memory_hits)||0)+(Number(reuse.disk_hits)||0);
      card.append(element('strong','图片与采样画面的复用'),element('p',`本次 ${reuse.total_images} 张 · 缓存复用 ${hits} 张 · 需新核对 ${reuse.new_images} 张`));
      if(reuse.inflight_hits)card.append(element('p',`复用其他进行中任务的同图核对 ${reuse.inflight_hits} 张；等待期间不占模型名额。`));
      if(reuse.vision_model)card.append(element('small','画面核对模型：'+reuse.vision_model));
      if(reuse.failed_images)card.append(element('p',`${reuse.failed_images} 张待核实，请对照原图。`));
      if(reuse.cache_read_failures||reuse.cache_save_failures)card.append(element('p','复用缓存暂不可用；本次返回的成功核对记录仍保留，下次可能重新核对。'));
      card.append(element('p','这里只统计本次处理的图片，不表示看过整本书或视频的每一帧，也不能证明讲解一定正确。','task-timing-note'));body.append(card);
    }
    if(!data.observed)body.append(element('p','这项任务还没有分步用时记录。旧任务可能未保存；任务运行后可以点“刷新耗时”。'));
    for(const row of data.resources||[]){
      const card=element('section',null,'task-timing-card');card.dataset.resource=row.resource;
      card.append(element('strong',row.phase?`模型 · ${row.phase}`:labels[row.resource]||row.resource),element('p',`处理用时 ${duration(row.elapsed_ms)} · 排队等待 ${duration(row.queue_ms)}`),
        element('small',`${row.calls} 段记录 · 运行 ${row.active} · 排队 ${row.queued}${row.failed?` · 失败 ${row.failed}`:''}${row.interrupted?` · 中断 ${row.interrupted}（时长可能含停机时间）`:''}`));
      body.append(card);
    }
    body.append(element('p',data.note,'task-timing-note'));
  }
  async function load(){
    if(!target)return;const selected=target,token=++revision;status.textContent='读取阶段记录…';
    try{const data=await api(`/api/jobs/${selected}/timing`);if(token!==revision||target!==selected||!dialog.open)return;render(data);status.textContent='记录时间：'+new Date(data.as_of).toLocaleTimeString();}
    catch(error){if(token===revision&&dialog.open)status.textContent=error.message;}
  }
  function open(id){setup();target=id;if(!dialog.open)dialog.showModal();body.replaceChildren();load();}
  function attachJob(row,actions){if(!actions||actions.querySelector('[data-task-timing]'))return;const button=element('button','耗时详情');button.type='button';button.dataset.taskTiming=row.id;button.onclick=event=>{event.stopPropagation();open(row.id);};actions.append(button);}
  window.studyforgeTaskTiming={attachJob,open};
})();
