'use strict';
const $=id=>document.getElementById(id);
const mobile={authenticated:false,config:null,projects:[],project:null,chat:null,sources:[],categories:[],artifacts:[],jobs:[],selected:new Set(),runs:new Map(),historyAnchors:new Map(),historyScrolls:new Map(),epoch:0,save:Promise.resolve(),polling:false,catalog:[],uploading:0};
const mobileTaskActions=new Set(),mobileApprovals={revision:0,busy:new Set(),scope:null,loading:null,rows:[]};
const formatNames={docx:'Word · DOCX',pdf:'PDF',pptx:'PowerPoint · PPTX',mm:'思维导图',apkg:'Anki 卡组',py:'Python 文件',ipynb:'Jupyter Notebook',js:'JavaScript',ts:'TypeScript',cpp:'C++',m:'MATLAB',wl:'Mathematica',zip:'代码包 ZIP',md:'Markdown'};
const jobNames={export:'另存讲解格式',generate:'成果生成',import:'资料解析',import_url:'网址解析',read:'资料通读',homework_grade:'批改与错因补讲',coding_generate:'编程作业',coding_grade:'编程判题',quiz_grade:'习题批改',feynman:'费曼讲解核查',repair:'薄弱点练习',advance:'进阶练习'};
const phaseNames={queued:'排队中',running:'执行中',pausing:'正在暂停',paused:'已暂停',completed:'已完成',failed:'失败',cancelled:'已取消'};
let toastTimer,pairTimer,refreshTimer,catalogEpoch=0;
const mobileToast=$('toast');
function placeMobileToast(){const focused=document.activeElement?.closest('dialog:modal'),parent=focused||[...document.querySelectorAll('dialog:modal')].at(-1)||document.body;if(mobileToast.parentElement!==parent){if(mobileToast.hidePopover&&mobileToast.matches(':popover-open'))mobileToast.hidePopover();parent.append(mobileToast);}}
document.addEventListener('close',event=>{if(event.target.tagName==='DIALOG'&&event.target.contains(mobileToast))placeMobileToast();},true);
function json(method,value){return {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(value)};}
function toast(text){const node=mobileToast;placeMobileToast();node.textContent=text;window.studyforgeOperationErrors?.decorateToast(node,text);node.hidden=false;if(node.showPopover){if(node.matches(':popover-open'))node.hidePopover();node.showPopover();}clearTimeout(toastTimer);toastTimer=setTimeout(()=>{if(node.hidePopover&&node.matches(':popover-open'))node.hidePopover();node.hidden=true;},node.querySelector('.operation-error-action')?12000:5000);}
function safeRead(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}}
function safeWrite(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{/* Private browsers may disable storage. */}}
function showPair(message){mobile.authenticated=false;resetMobileApprovals();window.studyforgeMobileHomework?.reset();window.studyforgeMobileLessonFeedback?.reset();window.studyforgeMobileGoalChecks?.reset();$('pairScreen').hidden=false;$('learningApp').hidden=true;if(message)$('pairStatus').textContent=message;for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();}
async function api(path,options={}){
  let response;try{response=await fetch(path,{credentials:'same-origin',...options});}catch(err){if(err?.name==='AbortError')throw err;throw window.studyforgeOperationErrors?.capture(new Error('无法连接电脑；请检查网络、电脑是否开机，以及软件是否仍在后台运行'),{path,transport:'local',mobile:true})||err;}
  const data=await response.json().catch(()=>({}));
  if(response.status===401){const expired=Boolean(response.headers.get('x-studyforge-mobile-session'))||path==='/mobile/session'||/请先与电脑配对|手机连接.*(?:失效|撤销|重新配对)/.test(String(data.detail||''));if(expired)showPair(data.detail);const failure=new Error(data.detail||(expired?'这台手机的连接已失效。请在电脑上打开“连接手机”，重新配对。':'AI 服务没有接受当前的登录状态或 API 密钥。'));throw window.studyforgeOperationErrors?.capture(failure,{status:response.status,path,mobile:true,mobileSession:expired})||failure;}
  if(!response.ok){const failure=new Error(typeof data.detail==='string'?data.detail:data.detail?JSON.stringify(data.detail):'操作没有完成。请回电脑查看任务提示，或确认填写的内容后重试。');throw window.studyforgeOperationErrors?.capture(failure,{status:response.status,path,mobile:true})||failure;}
  return data;
}
function openSheet(id){const dialog=$(id);if(!dialog.open)dialog.showModal();}
function selectedHint(){const count=mobile.selected.size;const label=!$('useMaterials').checked?'这次不使用项目资料':count?`本次使用的资料 · 已选 ${count} 份`:'本次未选资料';const button=$('selectedSources');button.textContent=label;button.title=label;button.setAttribute('aria-label','选择项目资料，'+label);$('materialCount').textContent=count;}
function theme(value){const resolved=value==='auto'?(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'):value;document.documentElement.dataset.theme=resolved;document.querySelector('meta[name="theme-color"]').content=resolved==='dark'?'#17211f':'#f5f4ee';safeWrite('sfMobileTheme',value);}
function focus(value){document.body.classList.toggle('focus',value);safeWrite('sfMobileFocus',value);requestAnimationFrame(scrollBottom);}
function viewport(){if(window.visualViewport)document.documentElement.style.setProperty('--height',Math.round(visualViewport.height)+'px');}
function fitPrompt(){const input=$('prompt');input.style.height='auto';input.style.height=Math.min(input.scrollHeight,170)+'px';}
function nearBottom(){const box=$('messages');return box.scrollHeight-box.scrollTop-box.clientHeight<110;}
function scrollBottom(){const box=$('messages');box.scrollTop=box.scrollHeight;}
function markdown(target,content){renderLessonText(target,String(content||''));}
function message(role,text,id,reply_reference){const article=document.createElement('article');article.className='message '+(role==='user'?'user':'assistant');if(id)article.dataset.message=id;const label=document.createElement('div');label.className='role';label.textContent=role==='user'?'你':'AI 导师';const body=document.createElement('div');body.className=role==='user'?'plain-text':'markdown';if(role==='user')body.textContent=text;else markdown(body,text);article.append(label,body);if(id&&mobile.project&&mobile.chat){article.dataset.exportMessage=id;article.exportMessage={id,role,content:text,projectId:mobile.project.id,conversationId:mobile.chat.id,reply_reference};window.studyforgeDocumentExports?.attachMessage(article);window.studyforgeMessageFocus?.attach(article);}return article;}
function paintMessages(messages){const box=$('messages'),scope=mobile.chat?.id||'',history=window.studyforgeMessageHistory,active=mobile.runs.get(scope),preserve=[];
  for(const node of box.querySelectorAll('[data-live-reply]')){if(active&&['queued','running'].includes(active.status)&&node.dataset.liveReply===active.id)preserve.push(node);else node.remove();}
  if(history.matches(box,messages,scope)){installMobileHistoryPager();return;}const keep=nearBottom(),old=box.scrollTop;history.sync(box,messages,row=>message(row.role,row.content,row.id,row.reply_reference),{scope,preserve});if(!messages?.length){const empty=document.createElement('div');empty.className='empty-state';empty.innerHTML='<span>∑</span><h2>今天想弄懂什么？</h2><p>上传资料，选择要阅读的范围，再从一个具体问题开始。</p>';box.append(empty);}installMobileHistoryPager();if(keep)scrollBottom();else box.scrollTop=old;}
function installMobileHistoryPager(){window.studyforgeHistoryPages.install($('messages'),()=>loadOlderMobileHistory().catch(error=>toast(error.message)));}
function mobileChatURL(id,project){const view=window.studyforgeHistoryPages.state($('messages')),anchor=view?.id===id?view.oldest:null;return `/api/conversations/${id}?project_id=${project}&history_limit=60${anchor?'&history_start='+encodeURIComponent(anchor):''}`;}
async function loadOlderMobileHistory(){const host=$('messages'),pager=window.studyforgeHistoryPages,id=mobile.chat?.id,project=mobile.project?.id,epoch=mobile.epoch,ticket=pager.request(host,{older:true});if(!ticket)return;const result=await api(`/api/conversations/${id}/messages?project_id=${project}&${ticket.query}`);if(epoch!==mobile.epoch||id!==mobile.chat?.id)return;const oldHeight=host.scrollHeight,oldScroll=host.scrollTop,rows=pager.apply(host,result,ticket);if(!rows)return;paintMessages(rows);host.scrollTop=oldScroll+host.scrollHeight-oldHeight;}
async function refreshMobileMessages({force=false}={}){const id=mobile.chat?.id,project=mobile.project?.id,epoch=mobile.epoch;if(!id)return;const request=mobile.historyRequest=(mobile.historyRequest||0)+1,pager=window.studyforgeHistoryPages,ticket=pager.request($('messages'),{force});const result=await api(`/api/conversations/${id}/messages?project_id=${project}${ticket?'&'+ticket.query:''}`);if(request!==mobile.historyRequest||epoch!==mobile.epoch||id!==mobile.chat?.id)return;const rows=ticket?pager.apply($('messages'),result,ticket):result.messages;if(rows)paintMessages(rows);}
function selectedReasoning(){return ['codex','deepseek'].includes($('provider').value)?$('effort').value||null:null;}
function requestSnapshot(){return {project_id:mobile.project.id,conversation_id:mobile.chat.id,source_ids:[...mobile.selected],provider:$('provider').value,model:$('model').value.trim()||null,reasoning_effort:selectedReasoning(),learning_mode:$('learningMode').value,explanation_style:$('explanationStyle').value,output_language:$('outputLanguage').value};}
function saveChanges(changes){if(!mobile.chat)return Promise.resolve();const id=mobile.chat.id,project=mobile.project.id;mobile.save=mobile.save.catch(()=>{}).then(()=>api('/api/conversations/'+id+'?include_history=false',json('PUT',{project_id:project,...changes})));return mobile.save;}
function setSelected(id,checked){if(checked)mobile.selected.add(id);else mobile.selected.delete(id);selectedHint();renderSources();return saveChanges({source_ids:[...mobile.selected]});}
function option(select,value,text){const item=document.createElement('option');item.value=value;item.textContent=text;select.append(item);}
async function loadCatalog(){const token=++catalogEpoch,provider=$('provider').value;$('effortField').hidden=!['codex','deepseek'].includes(provider);mobile.catalog=[];if(provider==='deepseek')renderEfforts();$('modelNotice').textContent='正在获取可选模型。不指定时，使用这个 AI 服务的默认模型。';let catalog;
  try{catalog=await api(provider==='codex'?'/api/codex/models':provider==='deepseek'?'/api/deepseek/models':`/api/providers/${provider}/models`);}catch(error){if(token===catalogEpoch)$('modelNotice').textContent=error.message;return;}
  if(token!==catalogEpoch)return;mobile.catalog=catalog.models||[];$('mobileModels').replaceChildren();for(const row of mobile.catalog)option($('mobileModels'),row.id,row.name||row.id);$('modelNotice').textContent=catalog.warning||'这里显示电脑当前可以使用的模型和思考强度。';renderEfforts();
}
function renderEfforts(){const value=mobile.effortChoice??$('effort').value,provider=$('provider').value,model=$('model').value.trim()||mobile.config.services.find(item=>item.id===provider)?.default_model,row=mobile.catalog.find(item=>item.id===model)||(!model?mobile.catalog.find(item=>item.is_default):null),choices=provider==='deepseek'?['none','low','high','max']:row?.efforts||[],names={none:'关闭推理',low:'低 · 更快',medium:'中',high:'高',max:'最高',ultra:'超高'};$('effort').replaceChildren();option($('effort'),'',provider==='deepseek'?'自动 · 服务默认（高）':'模型默认');for(const effort of choices){const id=typeof effort==='string'?effort:effort.reasoningEffort||effort.id;option($('effort'),id,names[id]||id);}$('effort').disabled=!choices.length;if([...$('effort').options].some(item=>item.value===value))$('effort').value=value;mobile.effortChoice=$('effort').value;}
async function selectProject(id){if(!id)return;saveDraft();resetMobileApprovals();window.studyforgeMobileHomework?.reset();window.studyforgeMobileLessonFeedback?.reset();window.studyforgeMobileGoalChecks?.reset();const token=++mobile.epoch;mobile.project=mobile.projects.find(item=>item.id===id);mobile.chat=null;mobile.selected.clear();$('projectSelect').value=id;$('projectName').textContent=mobile.project.name;safeWrite('sfMobileProject',id);const result=await api(`/api/projects/${id}/conversations`);if(token!==mobile.epoch)return;renderConversations(result.conversations||[]);const saved=safeRead('sfMobileChat:'+id,null),chat=(result.conversations||[]).find(item=>item.id===saved)||(result.conversations||[]).find(item=>item.id===result.active_conversation_id)||(result.conversations||[])[0];if(chat)await selectChat(chat.id);else{$('conversationName').textContent='新建一个学习对话';paintMessages([]);await refreshProject();}}
function renderConversations(rows){const list=$('conversationList');list.replaceChildren();for(const row of rows){const button=document.createElement('button');button.className='item conversation-item'+(row.id===mobile.chat?.id?' active':'');const title=document.createElement('strong'),description=document.createElement('p');title.textContent=row.title||'新对话';description.textContent=row.last_message||row.preview||'点击继续这个独立对话';button.append(title,description);button.onclick=()=>selectChat(row.id).then(()=>$('workspaceDialog').close()).catch(error=>toast(error.message));list.append(button);}}
async function selectChat(id){saveDraft();resetMobileApprovals();const token=++mobile.epoch,project=mobile.project.id,anchor=mobile.historyAnchors.get(id);const chat=await api(`/api/conversations/${id}?project_id=${project}&history_limit=60${anchor?'&history_start='+encodeURIComponent(anchor):''}`);if(token!==mobile.epoch)return;resetMobileApprovals();mobile.chat=chat;window.studyforgeHistoryPages.begin($('messages'),id,chat);mobile.selected=new Set(chat.source_ids||[]);safeWrite('sfMobileChat:'+project,id);$('conversationName').textContent=chat.title||'新对话';$('provider').value=chat.provider;$('model').value=chat.model_choice||chat.resolved_model||chat.model||'';mobile.effortChoice=chat.reasoning_effort||'';$('effort').value=mobile.effortChoice;for(const [id,value] of [['learningMode',chat.learning_mode||'deep'],['explanationStyle',chat.explanation_style||'clear'],['outputLanguage',chat.output_language||'zh'],['reviewMode',chat.review_mode||'express']])$(id).value=value;
  window.studyforgeMobileLessonFeedback?.conversationChanged();window.studyforgeMobileGoalChecks?.reset();window.libraryConversationChanged?.(chat.id,project);$('prompt').value=safeRead('sfMobileDraft:'+id,'');fitPrompt();paintMessages(chat.messages);selectedHint();loadCatalog().catch(error=>toast(error.message));refreshRunUI();$('messages').scrollTop=mobile.historyScrolls.has(id)?mobile.historyScrolls.get(id):$('messages').scrollHeight;$('retryBox').hidden=!safeRead('sfMobileOutbox:'+id,null);await refreshProject();}
function saveDraft(){if(mobile.chat){const id=mobile.chat.id,view=window.studyforgeHistoryPages.state($('messages'));safeWrite('sfMobileDraft:'+id,$('prompt').value);if(view?.id===id){if(view.oldest)mobile.historyAnchors.set(id,view.oldest);mobile.historyScrolls.set(id,$('messages').scrollTop);}}}
const projectRefresh=window.studyforgeRefresh.coalesce(loadProjectRefresh);
function refreshProject({poll=false}={}){if(!mobile.authenticated||!mobile.project)return Promise.resolve();const scope={project:mobile.project.id,epoch:mobile.epoch,sort:$('artifactSort').value};return projectRefresh(JSON.stringify(scope),scope,{fresh:!poll});}
async function loadProjectRefresh({project,epoch,sort}){const [sources,categories,artifacts,jobs]=await Promise.all([api(`/api/projects/${project}/sources`),api(`/api/projects/${project}/categories`),api(`/api/projects/${project}/artifacts?sort=${sort}`),api(`/api/projects/${project}/jobs`)]);if(!mobile.authenticated||project!==mobile.project?.id||epoch!==mobile.epoch||sort!==$('artifactSort').value)return;
  mobile.sources=sources;mobile.categories=categories;mobile.artifacts=artifacts;mobile.jobs=jobs;const valid=new Set(sources.filter(item=>['ready','stored'].includes(item.status)).map(item=>item.id));mobile.selected=new Set([...mobile.selected].filter(id=>valid.has(id)));selectedHint();$('artifactCount').textContent=artifacts.length;$('taskCount').textContent=jobs.filter(item=>['queued','running','pausing','paused'].includes(item.status)).length;renderSources();renderArtifacts();renderTasks();
  await Promise.all([window.studyforgeMobileHomework?.refresh(),window.studyforgeMobileLessonFeedback?.refresh()]);
}
function renderSources(){const list=$('sourceList'),query=$('sourceSearch').value.trim().toLowerCase();return window.studyforgeRefresh.paint(list,[mobile.project?.id,mobile.epoch,mobile.sources,mobile.categories,[...mobile.selected],query],()=>{list.replaceChildren();const groups=[{id:'',name:'未分类'},...mobile.categories,{id:'__artifacts__',name:'本项目成果'}];
  for(const group of groups){const rows=mobile.sources.filter(item=>(group.id==='__artifacts__'?Boolean(item.artifact_id):!item.artifact_id&&(item.category_id||'')===group.id)&&(!query||item.name.toLowerCase().includes(query)));if(!rows.length)continue;const heading=document.createElement('div');heading.className='category-heading';const title=document.createElement('span'),all=document.createElement('button');title.textContent=group.name;all.textContent='选用整类';all.onclick=async()=>{for(const row of rows.filter(item=>['ready','stored'].includes(item.status)))mobile.selected.add(row.id);selectedHint();renderSources();await saveChanges({source_ids:[...mobile.selected]});};heading.append(title,all);list.append(heading);
    for(const row of rows){const card=document.createElement('div');card.className='item';const label=document.createElement('label');label.className='source-item';label.style.margin='0';const box=document.createElement('input');box.type='checkbox';box.checked=mobile.selected.has(row.id);box.disabled=!['ready','stored'].includes(row.status);box.onchange=()=>setSelected(row.id,box.checked).catch(error=>toast(error.message));const info=document.createElement('span'),name=document.createElement('strong'),description=document.createElement('p');name.textContent=row.name;description.textContent=row.status==='stored'?(row.partial_parse_supported===false?'已入库 · 待点击解析'+(row.parse_type==='url'?'网址':'图片'):'已入库 · 等你选择解析范围'):row.status==='ready'?'可引用':row.status==='pending'?'正在解析':row.error||'解析失败';info.append(name,description);label.append(box,info);card.append(label);
      if(row.status!=='pending'&&!row.artifact_id){const button=document.createElement('button'),action=window.studyforgeSourceScope.action(row);button.textContent=action.label;button.title=action.title;button.disabled=action.disabled;button.onclick=async()=>{button.disabled=true;try{await openSourceScope(row);}finally{button.disabled=action.disabled;}};const actions=document.createElement('div');actions.className='item-actions';actions.append(button);card.append(actions);}list.append(card);
    }
  }
  if(!list.children.length){const note=document.createElement('p');note.className='helper';note.textContent=query?'没有匹配的资料。':'先上传文件或添加网址，再点击对应解析入口。';list.append(note);}
  });
}
function openSourceScope(row){
  const projectId=mobile.project?.id,chatId=mobile.chat?.id;
  return window.studyforgeSourceScope.open(row,{onParsed:async result=>{
    if(mobile.project?.id!==projectId||mobile.chat?.id!==chatId)return;
    mobile.selected.delete(row.id);
    if(result.job_id){toast(row.partial_parse_supported===false?'已开始解析，可处理其他资料。':'已按你的选择开始解析；可处理其他资料。');pollParsed(result.source_id,result.job_id,chatId);}
    else{mobile.selected.add(result.source_id);await saveChanges({source_ids:[...mobile.selected]});toast(result.scope==='full'?'资料已解析，可以直接引用。':'已解析所选范围，原文件仍保留。');}
    await refreshProject();
  }}).catch(error=>toast(error.message));
}
async function pollParsed(sourceId,jobId,conversationId){const project=mobile.project.id;for(let i=0;i<1200&&mobile.authenticated;i++){await new Promise(resolve=>setTimeout(resolve,2000));let job;try{job=await window.studyforgeRefresh.pollTask(api,jobId,{detailOnFinish:false});}catch{return;}if(['completed','failed','cancelled'].includes(job.status)){if(job.status==='completed'&&mobile.chat?.id===conversationId){mobile.selected.add(sourceId);await refreshProject();await saveChanges({source_ids:[...mobile.selected]});toast('资料已解析，可以引用。');}else if(job.status==='failed'){await refreshProject();toast(job.error||'解析未完成');}return;}if(mobile.project?.id!==project)return;}}
function renderArtifacts(){
  const list=$('artifactList');return window.studyforgeRefresh.paint(list,[mobile.project?.id,mobile.epoch,mobile.artifacts,mobile.sources.filter(row=>row.artifact_id).map(row=>[row.artifact_id,row.id,mobile.selected.has(row.id)])],()=>{list.replaceChildren();
  for(const row of mobile.artifacts){
    const card=document.createElement('article');card.className='item';card.dataset.artifact=row.id;
    const title=document.createElement('strong'),info=document.createElement('p'),actions=document.createElement('div'),link=document.createElement('a');
    title.textContent=row.title;info.textContent=row.format.toUpperCase()+' · '+(row.origin?.title||row.conversation_title||'本项目成果')+(row.metadata?.reexport?' · 本机另存 · 0 次新增模型请求':'');
    actions.className='item-actions';link.className='download-link';link.href='/api/artifacts/'+row.id+'/download';
    link.download=row.download_filename||row.title+'.'+row.format;link.textContent='下载文件';actions.append(link);
    const source=mobile.sources.find(item=>item.artifact_id===row.id);
    if(source){
      const use=document.createElement('button');use.textContent=mobile.selected.has(source.id)?'已引用':'引用并提问';
      use.onclick=async()=>{await setSelected(source.id,true);$('artifactsDialog').close();$('prompt').focus();};actions.append(use);
    }
    window.studyforgeMobileLessonFeedback?.attachArtifact(row,actions);
    window.studyforgeDocumentExports?.attachArtifact(row,actions,mobile.project.id);card.append(title,info);
    const evidence=window.studyforgeSourceEvidence?.create(row.metadata,row.id);
    if(evidence)card.append(evidence);
    const teachingReview=window.studyforgeTeachingReview?.create(row.metadata,row.id,row.kind);
    if(teachingReview)card.append(teachingReview);
    card.append(actions);list.append(card);
  }
  if(!list.children.length)list.innerHTML='<p class="helper">此项目还没有成果。生成完成后会自动出现在这里。</p>';
  });
}
function renderTasks(){
  const list=$('taskList');window.studyforgeRefresh.reconcile(list,mobile.jobs,{key:row=>row.id,
    stamp:row=>[mobile.project?.id,mobile.epoch,row,mobileTaskActions.has(row.id)],create:row=>{
    const item=document.createElement('article');item.className='item';item.dataset.taskId=row.id;
    const title=document.createElement('strong'),description=document.createElement('p'),progress=document.createElement('progress');
    title.textContent=jobNames[row.kind]||row.kind;
    description.textContent=row.status==='failed'?'未完成，请查看处理办法':(phaseNames[row.status]||row.status)+' · '+row.progress+'%'+(row.stage?' · '+row.stage:'');
    progress.max=100;progress.value=row.progress;item.append(title,description,progress);
    const retryText=window.studyforgeTaskRetry?.summary(row);
    if(retryText){const status=document.createElement('p');status.className='task-retry-status';status.setAttribute('role','status');status.textContent=retryText;item.append(status);}
    if(row.error){const error=document.createElement('p');error.textContent=window.studyforgeOperationErrors?.summary(row.error)||row.error;item.append(error);window.studyforgeOperationErrors?.attach(item,row.error);}
    const actions=document.createElement('div');actions.className='item-actions';
    if(row.status==='failed'&&row.recovery?.available){const button=document.createElement('button');button.type='button';button.textContent='重试未完成步骤';button.disabled=mobileTaskActions.has(row.id);button.onclick=async()=>{if(mobileTaskActions.has(row.id))return;mobileTaskActions.add(row.id);button.disabled=true;try{await window.studyforgeTaskRetry.manual(api,row,mobile.project.id);toast('已接着原任务重试，沿用原资料、模型和要求。');await refreshProject();}catch(error){toast(error.message);}finally{mobileTaskActions.delete(row.id);renderTasks();}};actions.append(button);}
    if(row.status==='failed'&&row.recovery){const note=document.createElement('p');note.className='helper';note.textContent=row.recovery.reason;item.append(note);}
    if(row.waiting_for_causes&&row.homework_attempt_id){
      const button=document.createElement('button');button.textContent='填写错因问卷';
      button.onclick=()=>window.studyforgeMobileHomework?.openAttempt(row.homework_attempt_id).catch(error=>toast(error.message));
      actions.append(button);
    }else if(row.can_pause&&['queued','running','paused','pausing'].includes(row.status)){
      const button=document.createElement('button');button.textContent=row.status==='paused'?'继续':row.status==='pausing'?'正在暂停':'暂停';
      button.disabled=row.status==='pausing'||mobileTaskActions.has(row.id);
      button.onclick=async()=>{if(mobileTaskActions.has(row.id))return;mobileTaskActions.add(row.id);button.disabled=true;try{await api('/api/jobs/'+row.id+'/'+(row.status==='paused'?'resume':'pause'),{method:'POST'});await refreshProject();}catch(error){toast(error.message);}finally{mobileTaskActions.delete(row.id);renderTasks();}};
      actions.append(button);
    }
    window.studyforgeDocumentExports?.attachJob(row,actions,mobile.project.id);
    window.studyforgeTaskTiming?.attachJob(row,actions);
    if(actions.children.length)item.append(actions);
    return item;
  },empty:()=>{const note=document.createElement('p');note.className='helper';note.textContent='还没有后台任务。文件入库不会自动启动解析。';return note;}});
}
function refreshRunUI(){window.studyforgeMessageFocus?.changed();const run=mobile.runs.get(mobile.chat?.id),active=run&&['queued','running'].includes(run.status);$('sendMessage').hidden=Boolean(active);$('stopReply').hidden=!active;$('replyStatus').hidden=!active;if(active)$('replyStatus').textContent=run.state?.label||'导师正在回复';}
async function send(outbox=null){
  if(!mobile.chat)return toast('请先新建或打开一个学习对话。');
  const text=$('prompt').value.trim();if(!outbox&&!text)return;
  const snapshot=requestSnapshot(),payload=outbox||{request_id:crypto.randomUUID().replaceAll('-',''),request:{...snapshot,text,include_materials:$('useMaterials').checked}};
  if(!outbox)payload.request.reply_reference=window.studyforgeMessageFocus?.capture(snapshot.project_id,snapshot.conversation_id)||null;
  if(!payload.request.include_materials)payload.request.source_ids=[];
  const chatId=payload.request.conversation_id;
  mobile.sending??=new Set();if(mobile.runs.has(chatId)||mobile.sending.has(chatId))return;
  mobile.sending.add(chatId);const pendingSave=mobile.save;
  if(mobile.chat?.id===chatId)$('sendMessage').disabled=true;
  safeWrite('sfMobileOutbox:'+chatId,payload);
  try{
    await pendingSave;
    await window.libraryFlush?.(chatId);
    const result=await api('/api/mobile/chat',json('POST',payload));
    window.studyforgeMessageFocus?.sent(payload.request);
    safeWrite('sfMobileOutbox:'+chatId,null);safeWrite('sfMobileDraft:'+chatId,'');
    mobile.runs.set(chatId,{id:result.run_id,status:result.status,content:'',state:{label:'导师正在回复'}});
    if(mobile.chat?.id===chatId){
      $('prompt').value='';fitPrompt();$('retryBox').hidden=true;
      await refreshMobileMessages({force:true});
      if(mobile.chat?.id===chatId)refreshRunUI();
    }
    await pollRuns();
  }catch(error){toast(error.message);if(mobile.chat?.id===chatId)$('retryBox').hidden=false;}
  finally{mobile.sending.delete(chatId);if(mobile.chat?.id===chatId)$('sendMessage').disabled=false;}
}
async function pollRuns(){for(const [chatId,current] of [...mobile.runs]){let row;try{row=await api('/api/mobile/chat/'+current.id);}catch(error){if(mobile.authenticated)$('replyStatus').textContent=error.message;continue;}mobile.runs.set(chatId,row);if(mobile.chat?.id===chatId){const keep=nearBottom();let node=$('messages').querySelector('[data-live-reply]');if(!node&&row.content){node=message('assistant','');node.dataset.liveReply=row.id;$('messages').append(node);}if(node&&node.dataset.revision!==String(row.revision)){renderLessonStream(node.querySelector('.markdown'),row.content);node.dataset.revision=row.revision;}refreshRunUI();if(keep)scrollBottom();}
    if(!['queued','running'].includes(row.status)){mobile.runs.delete(chatId);if(mobile.chat?.id===chatId){const epoch=mobile.epoch,chat=await api(mobileChatURL(chatId,row.project_id));if(mobile.chat?.id===chatId&&epoch===mobile.epoch){window.studyforgeHistoryPages.begin($('messages'),chatId,chat);paintMessages(chat.messages);if(row.error){const error=document.createElement('p');error.className='message-error';error.textContent=window.studyforgeOperationErrors?.summary(row.error)||row.error;$('messages').append(error);window.studyforgeOperationErrors?.attach(error,row.error);}refreshRunUI();$('conversationName').textContent=chat.title||'学习对话';await window.libraryRefreshMatches?.({chat:chatId,project:row.project_id});}}await refreshProject();}
  }}
function resetMobileApprovals(){mobileApprovals.revision++;mobileApprovals.scope=null;mobileApprovals.rows=[];if($('approvalDialog')?.open)$('approvalDialog').close();$('approvalList')?.replaceChildren();}
function approvalOwner(snapshot,epoch){return mobile.authenticated&&mobile.project?.id===snapshot.project_id&&mobile.chat?.id===snapshot.conversation_id&&mobile.epoch===epoch;}
function renderMobileApprovals(snapshot,epoch,key){
  if(!approvalOwner(snapshot,epoch)||mobileApprovals.scope!==key)return;
  const list=$('approvalList');window.studyforgeRefresh.reconcile(list,mobileApprovals.rows,{key:row=>row.id,
    stamp:row=>[key,row,mobileApprovals.busy.has(row.id)],create:row=>{
      const item=document.createElement('article');item.className='item';item.dataset.approvalId=row.id;
      const heading=document.createElement('strong'),paths=document.createElement('pre'),preview=document.createElement('div'),controls=document.createElement('div');
      heading.textContent=row.tool+' · 仅允许本次操作';paths.className='approval-path';paths.textContent=(row.details.paths||[]).map(path=>path.operation+'：'+path.path).join('\n');preview.className='approval-preview';preview.textContent=row.details.preview||'';controls.className='item-actions';
      for(const [text,approved] of [['允许一次',true],['拒绝',false]]){
        const button=document.createElement('button');button.textContent=text;button.disabled=mobileApprovals.busy.has(row.id);
        button.onclick=async()=>{
          if(mobileApprovals.busy.has(row.id)||!approvalOwner(snapshot,epoch))return;
          mobileApprovals.busy.add(row.id);mobileApprovals.revision++;for(const control of controls.children)control.disabled=true;
          try{await api('/api/agent/approvals/'+row.id,json('POST',{project_id:snapshot.project_id,conversation_id:snapshot.conversation_id,approved}));
            mobileApprovals.revision++;if(approvalOwner(snapshot,epoch))mobileApprovals.rows=mobileApprovals.rows.filter(item=>item.id!==row.id);
          }catch(error){toast(error.message);}finally{mobileApprovals.busy.delete(row.id);renderMobileApprovals(snapshot,epoch,key);}
        };controls.append(button);
      }
      item.append(heading,paths,preview,controls);return item;
    }});
  if(list.children.length)openSheet('approvalDialog');else if($('approvalDialog').open)$('approvalDialog').close();
}
function approvals(){
  if(!mobile.chat)return Promise.resolve();
  const snapshot=requestSnapshot(),epoch=mobile.epoch,key=JSON.stringify([snapshot.project_id,snapshot.conversation_id,epoch]);
  const active=mobile.runs.has(mobile.chat.id)||mobile.jobs.some(row=>row.conversation_id===mobile.chat.id&&['running','queued'].includes(row.status));
  if(!active&&!(mobileApprovals.scope===key&&$('approvalDialog').open))return Promise.resolve();
  if(mobileApprovals.loading?.key===key)return mobileApprovals.loading.promise;
  const revision=mobileApprovals.revision,entry={key,promise:null};mobileApprovals.scope=key;
  entry.promise=api(`/api/agent/approvals?project_id=${snapshot.project_id}&conversation_id=${snapshot.conversation_id}`).then(result=>{
    if(!approvalOwner(snapshot,epoch)||revision!==mobileApprovals.revision)return;
    mobileApprovals.rows=result.requests||[];renderMobileApprovals(snapshot,epoch,key);
  }).finally(()=>{if(mobileApprovals.loading===entry)mobileApprovals.loading=null;});
  mobileApprovals.loading=entry;return entry.promise;
}
async function upload(files){if(!mobile.project)return toast('请先选择项目。');const project=mobile.project.id,chatId=mobile.chat?.id;for(const file of [...files]){if(file.size>mobile.config.upload_limit){toast(file.name+' 超过 512 MB，请在电脑上传。');continue;}mobile.uploading++;const progress=$('uploadProgress');progress.hidden=false;progress.replaceChildren(document.createTextNode('正在入库：'+file.name));const bar=document.createElement('progress');bar.max=100;bar.value=0;progress.append(bar);
  try{const result=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest(),form=new FormData();form.append('project_id',project);form.append('file',file);xhr.open('POST','/api/import/file');xhr.upload.onprogress=event=>{if(event.lengthComputable)bar.value=Math.round(100*event.loaded/event.total);};xhr.onload=()=>{let body;try{body=JSON.parse(xhr.responseText);}catch{return reject(new Error('电脑未返回有效上传结果'));}if(xhr.status<200||xhr.status>=300)return reject(new Error(body.detail||'上传失败'));resolve(body);};xhr.onerror=()=>reject(new Error('上传连接中断，请重新选择文件上传'));xhr.send(form);});
    if(mobile.project?.id===project){await refreshProject();if(mobile.chat?.id===chatId){mobile.selected.add(result.source_id);selectedHint();renderSources();await saveChanges({source_ids:[...mobile.selected]});}}toast(file.name+(result.parse_type==='image'?' 已入库，点击“解析图片”后识别整张图片。':' 已入库，尚未解析。可选择页码、原文选段，或在对话中说明要读取哪一页。'));
  }catch(error){toast(error.message);}finally{mobile.uploading--;if(!mobile.uploading)progress.hidden=true;}}
}
async function boot(){try{await api('/mobile/session');mobile.config=await api('/api/mobile/config');mobile.authenticated=true;$('pairScreen').hidden=true;$('learningApp').hidden=false;$('provider').replaceChildren();for(const service of mobile.config.services)option($('provider'),service.id,service.name);$('provider').value=mobile.config.provider;$('outputFormat').replaceChildren();for(const format of mobile.config.formats)option($('outputFormat'),format,formatNames[format]||format.toUpperCase());$('outputFormat').value=mobile.config.defaults.default_output_format||'docx';mobile.projects=await api('/api/projects');$('projectSelect').replaceChildren();for(const project of mobile.projects)option($('projectSelect'),project.id,project.name);const saved=safeRead('sfMobileProject',null),project=mobile.projects.find(item=>item.id===saved)||mobile.projects.find(item=>item.id===mobile.config.desktop_workspace?.project_id)||mobile.projects[0];if(project)await selectProject(project.id);else openSheet('workspaceDialog');const active=await api('/api/mobile/chats');for(const row of active.runs)mobile.runs.set(row.conversation_id,row);await pollRuns();refreshRunUI();$('connectionStatus').hidden=true;}
  catch(error){if(!mobile.authenticated){showPair(error.message);}else{$('connectionStatus').hidden=false;$('connectionStatus').textContent=error.message;}}
}
async function refresh(){if(!mobile.authenticated||mobile.polling)return;mobile.polling=true;try{await pollRuns();await approvals();if(!document.hidden){if(Date.now()-(mobile.lastProjectRefresh||0)>5000){await refreshProject({poll:true});mobile.lastProjectRefresh=Date.now();}await refreshMobileMessages();}$('connectionStatus').hidden=true;}catch(error){if(mobile.authenticated){$('connectionStatus').hidden=false;$('connectionStatus').textContent=error.message;}}finally{mobile.polling=false;}}
$('pairForm').onsubmit=async event=>{event.preventDefault();clearInterval(pairTimer);$('pairSubmit').disabled=true;try{const value=await api('/mobile/pair',json('POST',{code:$('pairCode').value.trim(),name:$('deviceName').value.trim()}));$('pairStatus').textContent=value.message;pairTimer=setInterval(async()=>{try{const result=await api('/mobile/pair/'+value.device_id,{headers:{'X-Mobile-Pair-Ticket':value.ticket}});if(result.status==='active'){clearInterval(pairTimer);$('pairSubmit').disabled=false;await boot();}else if(['denied','expired','revoked'].includes(result.status)){clearInterval(pairTimer);$('pairStatus').textContent='电脑未允许这次连接，请重新配对。';$('pairSubmit').disabled=false;}}catch(error){clearInterval(pairTimer);$('pairStatus').textContent=error.message;$('pairSubmit').disabled=false;}},1200);}catch(error){$('pairStatus').textContent=error.message;$('pairSubmit').disabled=false;}};
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>button.closest('dialog').close();
for(const [button,dialog] of [['openWorkspace','workspaceDialog'],['openMaterials','materialsDialog'],['selectedSources','materialsDialog'],['openArtifacts','artifactsDialog'],['openTasks','tasksDialog'],['openOptions','optionsDialog'],['composerMore','optionsDialog'],['openGenerate','generateDialog']])$(button).onclick=()=>{openSheet(dialog);if(dialog==='workspaceDialog'&&mobile.project)api(`/api/projects/${mobile.project.id}/conversations`).then(value=>renderConversations(value.conversations)).catch(error=>toast(error.message));};
$('focusMode').onclick=()=>focus(true);$('focusExit').onclick=()=>focus(false);$('phoneTheme').value=safeRead('sfMobileTheme','auto');theme($('phoneTheme').value);$('phoneTheme').onchange=()=>theme($('phoneTheme').value);focus(safeRead('sfMobileFocus',false));
$('uploadFiles').onclick=$('uploadFromLibrary').onclick=()=>$('fileInput').click();$('cameraFile').onclick=()=>$('cameraInput').click();for(const id of ['fileInput','cameraInput'])$(id).onchange=event=>{upload(event.target.files).catch(error=>toast(error.message));event.target.value='';};
$('sourceSearch').oninput=renderSources;$('clearMaterials').onclick=async()=>{mobile.selected.clear();selectedHint();renderSources();await saveChanges({source_ids:[]});};$('useMaterials').onchange=selectedHint;
$('composer').onsubmit=event=>{event.preventDefault();send().catch(error=>toast(error.message));};$('retrySend').onclick=()=>send(safeRead('sfMobileOutbox:'+mobile.chat.id,null)).catch(error=>toast(error.message));$('prompt').oninput=()=>{fitPrompt();saveDraft();};$('prompt').onkeydown=event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.isComposing){event.preventDefault();send().catch(error=>toast(error.message));}};
$('stopReply').onclick=async()=>{const run=mobile.runs.get(mobile.chat?.id);if(run){await api('/api/mobile/chat/'+run.id+'/stop',{method:'POST'});await pollRuns();}};
$('provider').onchange=async()=>{const provider=$('provider').value;$('model').value=mobile.config.services.find(item=>item.id===provider)?.default_model||'';mobile.effortChoice='';$('effort').value='';await saveChanges({provider,model:$('model').value||null,model_choice:$('model').value,reasoning_effort:null});loadCatalog().catch(error=>toast(error.message));};
for(const [id,key] of [['model','model'],['effort','reasoning_effort'],['learningMode','learning_mode'],['explanationStyle','explanation_style'],['outputLanguage','output_language'],['reviewMode','review_mode']])$(id).onchange=()=>{const value=$(id).value,changes={[key]:value||null};if(id==='effort')mobile.effortChoice=value;if(id==='model'){changes.model_choice=value;renderEfforts();changes.reasoning_effort=$('effort').value||null;}saveChanges(changes).catch(error=>toast(error.message));};
$('projectSelect').onchange=()=>selectProject($('projectSelect').value).catch(error=>toast(error.message));$('newProject').onclick=()=>{$('projectForm').hidden=!$('projectForm').hidden;if(!$('projectForm').hidden)$('newProjectName').focus();};$('projectForm').onsubmit=async event=>{event.preventDefault();try{const project=await api('/api/projects',json('POST',{name:$('newProjectName').value.trim()}));mobile.projects.push(project);option($('projectSelect'),project.id,project.name);$('projectForm').hidden=true;await selectProject(project.id);}catch(error){toast(error.message);}};
$('newConversation').onclick=async()=>{if(!mobile.project)return toast('先新建一个学习项目。');try{const provider=mobile.chat?$('provider').value:mobile.config.provider,model=mobile.chat?$('model').value||null:null;const chat=await api(`/api/projects/${mobile.project.id}/conversations`,json('POST',{provider,model,model_choice:model||'',reasoning_effort:mobile.chat?selectedReasoning():null}));await selectChat(chat.id);$('workspaceDialog').close();}catch(error){toast(error.message);}};
$('urlForm').onsubmit=async event=>{event.preventDefault();if(!mobile.project)return;try{const projectId=mobile.project.id,chatId=mobile.chat?.id;const result=await api('/api/import/url',json('POST',{project_id:projectId,url:$('sourceUrl').value.trim()}));if(mobile.project?.id===projectId&&mobile.chat?.id===chatId){$('sourceUrl').value='';await refreshProject();await setSelected(result.source_id,true);}toast('网址已入库；点击“解析网址”后再读取。');}catch(error){toast(error.message);}};
$('artifactSort').onchange=$('refreshArtifacts').onclick=()=>refreshProject().catch(error=>toast(error.message));$('generateFromOptions').onclick=()=>{$('optionsDialog').close();openSheet('generateDialog');};$('summaryLevel').oninput=()=>{$('summaryLabel').textContent=['主干精炼','重点精要','均衡详略','详细解释','充分展开'][Number($('summaryLevel').value)-1];};
$('generateForm').onsubmit=async event=>{event.preventDefault();if(!mobile.chat)return toast('请先打开一个对话。');const stored=mobile.sources.find(item=>mobile.selected.has(item.id)&&item.status==='stored');if(stored){$('generateDialog').close();openSourceScope(stored);return toast(stored.partial_parse_supported===false?'正在解析网址或图片，完成后再生成。':'先选择这份资料要解析的范围，再生成。');}const snapshot=requestSnapshot();if(!snapshot.source_ids.length&&!window.libraryHasPrimary?.()&&$('generationContent').value!=='exercises')return toast('请选择需要讲解的资料或选段。');const generationRequest={...snapshot,format:$('outputFormat').value,summary_level:Number($('summaryLevel').value),only_exercises:$('generationContent').value==='exercises',exercises:$('withExercises').checked,exercise_format:'docx',review_mode:$('reviewMode').value,instructions:$('generationInstructions').value,mentor_provider:snapshot.provider,mentor_model:snapshot.model,mentor_reasoning_effort:snapshot.reasoning_effort};$('startGeneration').disabled=true;try{await mobile.save;await window.libraryFlush?.(snapshot.conversation_id);await api('/api/generate',json('POST',generationRequest));if(mobile.chat?.id===snapshot.conversation_id)$('generateDialog').close();toast('已在电脑后台开始生成，完成后到成果中下载。');await refreshProject();}catch(error){toast(error.message);}finally{$('startGeneration').disabled=false;}};
$('logout').onclick=async()=>{await api('/mobile/logout',{method:'POST'});mobile.runs.clear();showPair('这台手机的连接已撤销。');};
window.addEventListener('online',()=>{if(mobile.authenticated)refresh();else boot();});window.addEventListener('offline',()=>{$('connectionStatus').hidden=false;$('connectionStatus').textContent='手机网络已断开；电脑后台任务继续执行，联网后恢复。';});document.addEventListener('visibilitychange',()=>{if(!document.hidden){viewport();refresh();}});window.addEventListener('pagehide',saveDraft);window.visualViewport?.addEventListener('resize',viewport);window.addEventListener('resize',viewport);viewport();
// Keep installation help out of the focused reading area.
(()=>{
  let installPrompt=null;
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;});
  const entry=document.createElement('button');entry.id='mobileHomeShortcut';entry.type='button';entry.textContent='添加手机主屏幕入口';
  $('optionsDialog').querySelector('.row-actions').prepend(entry);
  const sheet=document.createElement('dialog');sheet.id='mobileShortcutDialog';sheet.className='sheet';
  sheet.innerHTML='<header><div><span class="eyebrow">ALWAYS WITH YOU</span><h2>下次直接打开</h2></div><button class="icon-button" type="button" aria-label="关闭">✕</button></header><div class="sheet-body"><p class="helper">固定私人地址配合已配对的同一浏览器，换网络也无需重复扫码。两端 Tailscale 保持连接，电脑软件在后台运行。</p><label>当前入口<input id="mobileShortcutURL" readonly></label><button id="mobileShortcutInstall" class="primary" type="button">添加到主屏幕</button><p id="mobileShortcutHelp" class="helper"></p><p class="helper">清除浏览器数据、撤销设备、更换浏览器或长期未使用导致凭据过期时，需要重新配对一次。仅关闭窗口不会撤销手机。</p></div>';
  document.body.append(sheet);sheet.querySelector('header button').onclick=()=>sheet.close();
  entry.onclick=()=>{
    $('optionsDialog').close();$('mobileShortcutURL').value=location.origin+'/';
    const standalone=matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
    $('mobileShortcutInstall').hidden=standalone;
    $('mobileShortcutHelp').textContent=standalone?'已从主屏幕进入；以后继续点击同一图标即可。':'安卓 Chrome：打开浏览器 ⋮ 菜单，选择“添加到主屏幕”或“安装应用”。建议先使用电脑面板提供的 Tailscale 固定地址完成配对。';
    sheet.showModal();
  };
  $('mobileShortcutInstall').onclick=async()=>{
    if(!installPrompt){$('mobileShortcutHelp').textContent='请使用浏览器 ⋮ 菜单 → 添加到主屏幕（或安装应用）。当前浏览器未提供自动安装提示。';return;}
    try{await installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;}
    catch{$('mobileShortcutHelp').textContent='请改用浏览器 ⋮ 菜单 → 添加到主屏幕。';}
  };
})();
function receivePairCode(){
  const code=new URLSearchParams(location.hash.slice(1)).get('pair');
  if(!code||!/^\d{8}$/.test(code))return;
  // Scanning again may reuse an already open tab and change only its fragment.
  // Receive that code too; do not log out an already authenticated device.
  if(!mobile.authenticated)$('pairCode').value=code;
  history.replaceState(null,'',location.pathname+location.search);
}
window.addEventListener('hashchange',receivePairCode);receivePairCode();
if('serviceWorker'in navigator&&window.isSecureContext)navigator.serviceWorker.register('/sw.js').catch(()=>{});
boot();refreshTimer=setInterval(refresh,1800);
