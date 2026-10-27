'use strict';
(() => {
  const state={projectId:null,items:[],item:null,dialogue:null,view:0,refresh:0,busy:new Set()};
  const modes={overview:'概览',deep:'精学',research:'研究'};
  const styles={clear:'通俗清晰',balanced:'直观与专业并重',academic:'学术专业'};
  const languages={zh:'中文',bilingual:'中英双语',en:'英语'};
  function node(tag,text,className){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;}
  function key(kind,item){return 'sfMobileLesson:'+kind+':'+item.project_id+':'+item.id;}
  function matches(item,view){return mobile.authenticated&&mobile.project?.id===item.project_id&&state.item?.id===item.id&&state.view===view;}
  function outstanding(item){return item.ready&&(item.status==='pending'||item.status==='submitted'&&item.reply_status!=='completed');}
  function saveDraft(){
    if(!state.item||state.item.status!=='pending'||$('lessonFeedbackForm').hidden)return;
    safeWrite(key('draft',state.item),{difficulties:[...$('lessonFeedbackChoices').querySelectorAll('input:checked')].map(input=>input.value),other_text:$('lessonFeedbackOther').value,focus_section_id:$('lessonFeedbackFocus').value,
      focus_selection:state.passage?.value()||null});
  }
  function reset(){
    saveDraft();state.view++;state.refresh++;state.projectId=null;state.items=[];state.item=null;state.dialogue=null;
    $('lessonFeedbackNotice').hidden=true;if($('lessonFeedbackDialog').open)$('lessonFeedbackDialog').close();
  }
  function conversationChanged(){
    if(state.item&&state.item.conversation_id!==mobile.chat?.id){back();if($('lessonFeedbackDialog').open)$('lessonFeedbackDialog').close();}
    notice();
  }
  function statusText(item){
    if(!item.ready)return '原讲解已移除，不能自动恢复补讲';
    if(item.status==='pending')return '有一份可选理解问卷';
    if(item.status==='skipped')return '已跳过 · 可直接向导师追问';
    if(item.kind==='content_check')return {pending:'问题已保存 · 可请导师核对',running:'导师正在核对',completed:'核对已写入原对话',failed:'核对未完成 · 可重试'}[item.reply_status]||'核对问题已保存';
    return {pending:'反馈已保存 · 可请导师补讲',running:'导师正在补讲',completed:'补讲已写入原对话',failed:'补讲未完成 · 可重试'}[item.reply_status]||'反馈已保存';
  }
  function notice(){
    const items=state.items.filter(item=>outstanding(item)&&item.conversation_id===mobile.chat?.id);
    $('lessonFeedbackNotice').hidden=!items.length;
    if(items.length){
      const next=items.find(item=>item.status==='submitted')||items[0];
      $('lessonFeedbackNoticeText').textContent=next.reply_status==='running'?'导师正在针对你的理解反馈补讲':items.length+' 份讲解可反馈哪里没懂';
      $('lessonFeedbackNoticeOpen').textContent=next.status==='pending'?'理解反馈':'查看补讲';
      $('lessonFeedbackNoticeOpen').onclick=()=>open(next.id).catch(error=>toast(error.message));
    }
    $('lessonFeedbackFromOptions').textContent='讲解理解反馈'+(items.length?' · '+items.length+' 份待处理':'');
  }
  function list(){
    const host=$('lessonFeedbackList');return window.studyforgeRefresh.paint(host,[state.projectId,mobile.epoch,state.items,mobile.chat?.id,mobile.artifacts.map(row=>[row.id,row.origin])],()=>{host.replaceChildren();
    const rows=[...state.items].sort((a,b)=>Number(b.conversation_id===mobile.chat?.id)-Number(a.conversation_id===mobile.chat?.id));
    for(const item of rows){
      const card=node('article',undefined,'item'),title=node('strong',(item.kind==='content_check'?'核对讲解 · ':'')+item.title),description=node('p',statusText(item));
      const origin=mobile.artifacts.find(row=>row.id===item.artifact_id)?.origin;
      if(origin)description.append(document.createTextNode(' · '+origin.title));
      const actions=node('div',undefined,'item-actions'),button=node('button',item.status==='pending'?'填写理解问卷':'查看理解反馈');
      button.type='button';button.dataset.lessonFeedbackId=item.id;button.onclick=()=>open(item.id).catch(error=>toast(error.message));
      actions.append(button);card.append(title,description,actions);host.append(card);
    }
    if(!rows.length)host.append(node('p','生成讲解后可选择六类理解困难，也可指出讲解可能有误。无需填写问卷，也可以继续直接问导师。','helper'));
    });
  }
  function attachArtifact(row,actions){
    let button=actions.querySelector('[data-lesson-feedback-artifact="'+row.id+'"]');
    if(row.kind!=='explanation'||row.origin?.deleted){button?.remove();return;}
    const item=state.items.find(value=>value.artifact_id===row.id&&value.kind!=='content_check'),job=row.metadata?.generation_job_id;
    if(!item&&!job){button?.remove();return;}
    if(!button)button=node('button');
    const label=item?.reply_status==='completed'?'查看补讲':'哪里没懂 · 请导师补讲';
    if(button.textContent!==label)button.textContent=label;
    button.type='button';button.dataset.lessonFeedbackArtifact=row.id;
    button.onclick=()=>open(item?.id,job).catch(error=>toast(error.message));if(button.parentElement!==actions)actions.append(button);
  }
  async function refresh(){
    if(!mobile.authenticated||!mobile.project)return;
    const project=mobile.project.id,epoch=mobile.epoch,token=++state.refresh;
    const rows=await api('/api/projects/'+project+'/lesson-feedback');
    if(!mobile.authenticated||mobile.project?.id!==project||epoch!==mobile.epoch||token!==state.refresh)return;
    state.projectId=project;state.items=rows;notice();list();
    for(const artifact of mobile.artifacts){const actions=$('artifactList').querySelector('[data-artifact="'+artifact.id+'"] .item-actions');if(actions)attachArtifact(artifact,actions);}
    if(state.item){
      const updated=rows.find(item=>item.id===state.item.id);
      if(!updated){back();return;}
      state.item=updated;render();
    }
  }
  function back(){saveDraft();state.view++;state.item=null;state.dialogue=null;$('lessonFeedbackBrowse').hidden=false;$('lessonFeedbackDetail').hidden=true;list();}
  async function open(id,jobId){
    if(!mobile.project||!mobile.chat)return toast('请先打开一个学习对话。');
    if(!id&&!jobId){back();for(const name of ['optionsDialog','artifactsDialog'])if($(name).open)$(name).close();openSheet('lessonFeedbackDialog');await refresh();return;}
    saveDraft();const project=mobile.project.id,epoch=mobile.epoch,view=++state.view;state.item=null;state.dialogue=null;
    const record=id?{id}:await api('/api/lesson-feedback/by-job/'+jobId);
    const dialogue=await api('/api/lesson-feedback/'+record.id+'/dialogue'),item=dialogue.questionnaire;
    if(view!==state.view||mobile.project?.id!==project||epoch!==mobile.epoch)return;
    if(item.project_id!==project)throw new Error('这份讲解属于另一个项目，请先进入该项目。');
    if(mobile.chat?.id!==item.conversation_id){await selectChat(item.conversation_id);if(view!==state.view||mobile.project?.id!==project||mobile.chat?.id!==item.conversation_id)return;}
    state.item=item;state.dialogue=dialogue;state.formId=null;state.resultSignature=null;
    for(const name of ['optionsDialog','artifactsDialog'])if($(name).open)$(name).close();
    $('lessonFeedbackBrowse').hidden=true;$('lessonFeedbackDetail').hidden=false;render();openSheet('lessonFeedbackDialog');
  }
  function render(){
    const item=state.item;if(!item)return;
    $('lessonFeedbackTitle').textContent=(item.kind==='content_check'?'核对讲解 · ':'')+item.title;
    const dialogue=state.dialogue||{},sourceNames=item.source_ids.map(id=>mobile.sources.find(source=>source.id===id)?.name||'已移除的资料');
    const host=$('lessonFeedbackContext');host.replaceChildren();
    host.append(node('p','补讲回到原对话：'+(dialogue.conversation_title||$('conversationName').textContent)));
    host.append(node('p','资料范围：'+(sourceNames.join('；')||'原讲解与原对话')+'。不自动改成整本书。'));
    host.append(node('p','沿用原讲解：'+(modes[dialogue.learning_mode]||'精学')+' · '+(styles[dialogue.explanation_style]||'通俗清晰')+' · '+(languages[dialogue.output_language]||'中文')));
    host.append(node('p','导师使用原对话当前的 AI 服务与模型：'+(dialogue.provider||mobile.chat?.provider||'')+' / '+(dialogue.model||'服务默认模型')));
    const pending=item.status==='pending';$('lessonFeedbackForm').hidden=!pending;
    if(pending&&state.formId!==item.id){
      state.formId=item.id;const draft=safeRead(key('draft',item),{difficulties:[],other_text:''});
      $('lessonFeedbackChoices').replaceChildren();
      for(const choice of item.options){
        const label=node('label',undefined,'check-line lesson-difficulty'),input=node('input'),text=node('span',({terminology:'术语的意思不懂',prerequisites:'缺少基础知识，跟不上这一步',motivation:'计算能看懂，但不知道为什么要这样设式或构造',method_selection:'会照着做，但不知道什么时候该用这个方法',argumentation:'能重复讲解，但自己证明不出来',implementation:'思路没问题，计算或代码出错'})[choice.id]||choice.label);
        input.type='checkbox';input.value=choice.id;input.checked=item.kind==='content_check'||Array.isArray(draft.difficulties)&&draft.difficulties.includes(choice.id);input.disabled=item.kind==='content_check';input.onchange=saveDraft;
        label.append(input,text);$('lessonFeedbackChoices').append(label);
      }
      $('lessonFeedbackOther').value=typeof draft.other_text==='string'?draft.other_text:item.other_text||'';
      const sections=dialogue.sections||{items:[],omitted:0},select=$('lessonFeedbackFocus');
      select.replaceChildren();const empty=node('option','不指定章节，按我的补充定位');empty.value='';select.append(empty);
      for(const section of sections.items){const option=node('option',section.path.join(' → '));option.value=section.id;select.append(option);}
      select.value=sections.items.some(section=>section.id===draft.focus_section_id)?draft.focus_section_id:'';
      state.passage=window.studyforgeLessonPassage.create($('lessonFeedbackPassage'),{getId:()=>state.item?.id,getSection:()=>select.value,api,
        isActive:()=>Boolean(state.item&&state.item.conversation_id===mobile.chat?.id),onChange:saveDraft});
      state.passage.setSection(select.value,select.value===draft.focus_section_id?draft.focus_selection:null);
      paintFocus(draft.focus_section_id&&!select.value?'上次选择的位置已变化，请重新选择；其他填写内容仍保留。':null);
    }
    const running=mobile.runs.has(item.conversation_id)||mobile.sending?.has(item.conversation_id);
    $('lessonFeedbackSubmit').disabled=!item.ready||state.busy.has(item.id);
    $('lessonFeedbackSave').disabled=!item.ready||state.busy.has(item.id);$('lessonFeedbackSkip').disabled=state.busy.has(item.id);
    $('lessonFeedbackDraftStatus').textContent=!item.ready?'原讲解尚未交付或已移除；你填写的草稿仍保留。':running?'此对话正在回复。可先保存反馈，回复完成后再补讲。':'草稿仅保存在这台手机；提交后同步到电脑。仅质疑讲解不记为知识薄弱项；自报困难不直接扣分。';
    $('lessonFeedbackResult').hidden=pending;
    const signature=JSON.stringify([item.status,item.reply_status,item.error,item.difficulties,item.other_text]);
    if(!pending&&state.resultSignature!==signature){
      state.resultSignature=signature;const result=$('lessonFeedbackResult');result.replaceChildren();
      result.append(node('p',statusText(item),'lesson-feedback-status'));
      if(item.status==='submitted'){
        const labels=item.options.filter(option=>item.difficulties.includes(option.id)).map(option=>option.label);
        if(labels.length)result.append(node('p','你的反馈：'+labels.join('；')));
        if(item.content_check)result.append(node('p','已请求先核对讲解；内容质疑不记成知识薄弱项，未据此评分。','helper'));
        if(item.other_text)result.append(node('blockquote',item.other_text,'lesson-student-feedback'));
        if(item.focus)result.append(node('p','这次要检查或补讲的位置：'+item.focus.path.join(' → ')+'。只关注你选中的这一处，不代表整份资料都没学会。','helper'));
        if(item.focus?.selection)result.append(node('p',`已选定本节第 ${item.focus.selection.start+1}–${item.focus.selection.end} 字符；原句不是你的作答记录。`,'helper'));
        if(item.error)result.append(node('p',item.error,'helper'));
      }else result.append(node('p','跳过不会调用导师，也不代表已经验证掌握。之后可以直接在原对话中提问。','helper'));
    }
    $('lessonFeedbackRetry').hidden=item.status!=='submitted'||!['pending','failed'].includes(item.reply_status)||!item.ready;
    $('lessonFeedbackRetry').disabled=state.busy.has(item.id)||Boolean(running);
    $('lessonFeedbackRetry').textContent=item.reply_status==='failed'?'重试回应 · 反馈已保留':item.content_check?'请导师核对':'请导师补讲';
    $('lessonFeedbackConversation').hidden=item.status==='pending';
    const check=item.understanding_check;
    $('lessonFeedbackCheck').hidden=$('lessonFeedbackCheckNotice').hidden=item.reply_status!=='completed'||item.kind==='content_check';
    $('lessonFeedbackContinue').hidden=item.status==='pending'||!item.ready;
    $('lessonFeedbackContinue').disabled=state.busy.has(item.id);
    $('lessonFeedbackCheck').disabled=state.busy.has(item.id);
    $('lessonFeedbackCheck').textContent=check?.status==='completed'&&check.exercise_set_id?'查看这道检查题':
      check&&['queued','running','pausing','paused'].includes(check.status)?'检查题生成中 · 查看任务':check?.status==='failed'?'重试 1 题理解检查':'用 1 道题检查是否听懂';
  }
  function paintFocus(note){
    const sections=state.dialogue?.sections||{items:[],omitted:0};
    const active=sections.items.find(section=>section.id===$('lessonFeedbackFocus').value);
    $('lessonFeedbackFocusInfo').textContent=note|| (active?active.preview+(active.chars>7000?'\n本节较长，可查看后续原句并选中具体卡住的一步。':''):
      sections.omitted?'仅列出前300个标题；其他位置可以在下方粘贴片段。':sections.items.length?'直接选择这份讲解的实际章节，不重新上传或解析。':'没有可用正文，请在下方填写具体片段。');
  }
  $('lessonFeedbackFocus').addEventListener('change',()=>{state.passage?.setSection($('lessonFeedbackFocus').value);paintFocus();saveDraft();});
  function remember(item){
    state.refresh++;const index=state.items.findIndex(row=>row.id===item.id);if(index<0)state.items.push(item);else state.items[index]=item;
    notice();list();renderArtifacts();
  }
  async function startFollowup(item){
    if(mobile.runs.has(item.conversation_id)||mobile.sending?.has(item.conversation_id))throw new Error('原对话正在回复；反馈已保存，请等回复完成后再点击补讲。');
    const pendingSave=mobile.save;
    const storage=key('outbox',item),saved=safeRead(storage,null);
    const payload=saved||{request_id:crypto.randomUUID().replaceAll('-',''),project_id:item.project_id,conversation_id:item.conversation_id};
    safeWrite(storage,payload);await pendingSave;
    let result=await api('/api/mobile/lesson-feedback/'+item.id+'/followup',json('POST',payload));
    if(result.reused&&['failed','cancelled'].includes(result.status)){
      const retry={...payload,request_id:crypto.randomUUID().replaceAll('-','')};safeWrite(storage,retry);
      result=await api('/api/mobile/lesson-feedback/'+item.id+'/followup',json('POST',retry));
    }
    safeWrite(storage,null);
    if(['queued','running'].includes(result.status))mobile.runs.set(item.conversation_id,{id:result.run_id,status:result.status,project_id:item.project_id,conversation_id:item.conversation_id,content:'',state:{kind:'lesson_feedback',questionnaire_id:item.id,label:'导师正在补讲'}});
    if(mobile.project?.id===item.project_id&&mobile.chat?.id===item.conversation_id){
      if($('lessonFeedbackDialog').open)$('lessonFeedbackDialog').close();refreshRunUI();
    }
    toast(result.reused?'已恢复这次补讲，不会重复请求导师。':'导师已开始补讲；刷新或离开手机页面后，电脑继续执行。');
    await pollRuns();
  }
  async function submit(action){
    const item=state.item;if(!item||state.busy.has(item.id))return;
    const view=state.view;saveDraft();
    const answers=action==='skip'?{skip:true}:{difficulties:[...$('lessonFeedbackChoices').querySelectorAll('input:checked')].map(input=>input.value),other_text:$('lessonFeedbackOther').value,focus_section_id:$('lessonFeedbackFocus').value||null,
      focus_selection:state.passage?.value()||null};
    if(action!=='skip'&&!answers.difficulties.length&&!answers.other_text.trim())return toast('请选择理解困难、讲解核对或填写其他补充；也可以暂时跳过。');
    if(action!=='skip'&&item.kind==='content_check'&&!answers.other_text.trim()&&!answers.focus_section_id)return toast('请写下需要核对的问题，或选择章节／原句，再请导师核对。');
    state.busy.add(item.id);render();
    try{
      const updated=await api('/api/lesson-feedback/'+item.id+'/submit',json('POST',answers));
      safeWrite(key('draft',item),null);
      if(mobile.project?.id===item.project_id){remember(updated);if(matches(item,view)){state.item=updated;render();}}
      if(action==='followup')await startFollowup(updated);
      else toast(action==='skip'?'已跳过，没有请求导师。':'理解反馈已保存；需要时可再请导师补讲。');
    }catch(error){toast(error.message);}
    finally{state.busy.delete(item.id);if(matches(item,view))render();if(mobile.project?.id===item.project_id)refresh().catch(error=>toast(error.message));}
  }
  async function retry(){
    const item=state.item;if(!item||state.busy.has(item.id))return;const view=state.view;
    state.busy.add(item.id);render();
    try{await startFollowup(item);}catch(error){toast(error.message);}
    finally{state.busy.delete(item.id);if(matches(item,view))render();if(mobile.project?.id===item.project_id)refresh().catch(error=>toast(error.message));}
  }
  const entry=node('button','讲解理解反馈','wide lesson-feedback-options-entry');entry.id='lessonFeedbackFromOptions';entry.type='button';
  $('optionsDialog').querySelector('.sheet-body').prepend(entry);
  const continueButton=node('button','对讲解还有新疑问','wide lesson-feedback-secondary');
  continueButton.id='lessonFeedbackContinue';continueButton.type='button';continueButton.hidden=true;
  $('lessonFeedbackConversation').before(continueButton);
  continueButton.onclick=async()=>{
    const item=state.item;if(!item||state.busy.has(item.id))return;const view=state.view;
    state.busy.add(item.id);render();
    try{
      const created=await api('/api/lesson-feedback/'+item.id+'/content-check',json('POST',{project_id:item.project_id,conversation_id:item.conversation_id}));
      if(matches(item,view)){remember(created);await open(created.id);}
    }catch(error){toast(error.message);}finally{state.busy.delete(item.id);if(matches(item,view))render();}
  };
  $('lessonFeedbackForm').onsubmit=event=>{event.preventDefault();submit('followup');};
  $('lessonFeedbackSave').onclick=()=>submit('save');$('lessonFeedbackSkip').onclick=()=>submit('skip');
  $('lessonFeedbackRetry').onclick=retry;$('lessonFeedbackBack').onclick=back;
  $('lessonFeedbackCheck').onclick=async()=>{
    const item=state.item;if(!item||state.busy.has(item.id)||item.conversation_id!==mobile.chat?.id)return;
    const check=item.understanding_check;
    if(check?.status==='completed'&&check.exercise_set_id){$('lessonFeedbackDialog').close();await studyforgeMobileHomework.openSet(check.exercise_set_id);return;}
    if(check&&['queued','running','pausing','paused'].includes(check.status)){$('lessonFeedbackDialog').close();openSheet('artifactsDialog');return;}
    const view=state.view;state.busy.add(item.id);render();
    try{await mobile.save;await api('/api/lesson-feedback/'+item.id+'/check',json('POST',{project_id:item.project_id,conversation_id:item.conversation_id}));
      toast('已在电脑安排1题检查，可以继续聊天；完成后在作业中作答。');if(matches(item,view))await refresh();
    }catch(error){toast(error.message);}finally{state.busy.delete(item.id);if(matches(item,view))render();}
  };
  $('lessonFeedbackOther').oninput=saveDraft;
  $('lessonFeedbackFromOptions').onclick=()=>open().catch(error=>toast(error.message));
  $('lessonFeedbackConversation').onclick=async()=>{
    const item=state.item;if(!item)return;
    try{if(mobile.project?.id!==item.project_id)return;if(mobile.chat?.id!==item.conversation_id)await selectChat(item.conversation_id);$('lessonFeedbackDialog').close();$('prompt').focus();scrollBottom();}catch(error){toast(error.message);}
  };
  $('lessonFeedbackDialog').addEventListener('close',saveDraft);window.addEventListener('pagehide',saveDraft);
  window.studyforgeMobileLessonFeedback={refresh,reset,open,attachArtifact,conversationChanged};
})();
