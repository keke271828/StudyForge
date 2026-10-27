const $ = id => document.getElementById(id);
const state = { project: null, sources: [], categories: [], selected: new Set(), importCategory: null,
  conversation: null, view: 'study', recording: null, busy: false, artifactSignature: null,
  settings: null, codexCatalog: null, deepseekCatalog: null, ready: false };
let readingTimer;
let exerciseRefreshToken=0;
let learningModeSave = Promise.resolve();
let modelPreferenceSave = Promise.resolve();
let modelRefreshToken = 0;
const apiNetworkSettings = {revision:0,pending:false,confirmed:'system'};
function applyApiNetworkSettings(config,revision=apiNetworkSettings.revision) {
  if(apiNetworkSettings.pending||revision!==apiNetworkSettings.revision){if(state.settings)state.settings.api_connection_mode=apiNetworkSettings.confirmed;return;}
  apiNetworkSettings.confirmed=config.api_connection_mode||'system';
  $('apiConnectionMode').value=apiNetworkSettings.confirmed;
}
$('apiConnectionMode').onchange=async()=>{
  const choice=$('apiConnectionMode').value,previous=apiNetworkSettings.confirmed;
  apiNetworkSettings.revision++;apiNetworkSettings.pending=true;$('apiConnectionMode').disabled=true;
  $('apiConnectionStatus').textContent='正在保存 API 连接方式…';
  try{
    const config=await api('/api/settings',jsonOptions('PUT',{api_connection_mode:choice}));
    apiNetworkSettings.confirmed=config.api_connection_mode;state.settings={...state.settings,api_connection_mode:config.api_connection_mode};
    $('apiConnectionStatus').textContent=choice==='direct'?'已保存：后续 API 连接直接访问服务地址，证书校验保持开启。':'已保存：后续 API 连接沿用环境网络配置。';
  }catch(failure){$('apiConnectionMode').value=previous;$('apiConnectionStatus').textContent=failure.message;error(failure);}
  finally{apiNetworkSettings.pending=false;$('apiConnectionMode').disabled=false;}
};
const learningModeDescriptions = {
  overview: ['概览', '先了解在讲什么、重点有哪些'],
  deep: ['精学', '弄懂为什么这样想、每一步为什么成立'],
  research: ['研究', '比较不同解释，追问条件和不确定之处']
};
function currentLearningMode() { return $('learningMode').value; }
const explanationStyleDescriptions = {
  clear: '先用易懂的话讲，再用具体例子说明；需要时补上基础知识，不硬套比喻。',
  balanced: '先讲清直观含义，再给出准确的定义、公式和推导。',
  academic: '使用专业语言，写清假设、符号和每一步的依据。'
};
function currentExplanationStyle() { return $('explanationStyle').value; }
function applyExplanationStyle(style, persist = true) {
  $('explanationStyle').value = Object.hasOwn(explanationStyleDescriptions, style) ? style : 'clear';
  $('explanationStyleHint').textContent = explanationStyleDescriptions[currentExplanationStyle()];
  if (persist) return saveConversation({explanation_style: currentExplanationStyle()});
}
$('explanationStyle').onchange = () => applyExplanationStyle(currentExplanationStyle());
const outputLanguageDescriptions = {zh:'正文使用中文，保留原文术语和引用。',bilingual:'按段落或小节先中文后英文，解释和限定相对应。',en:'解释正文使用英语，原文引用和代码保持原样。'};
const reviewModeDescriptions = {express:'由写讲解的 AI 自查，完成后不再单独检查，通常最快。',fast:'每部分额外检查 1 次。能确定的小错直接改，不能确定的地方会标出来。',balanced:'每部分额外检查 1 次；发现重要问题后重写相关内容，不再另查一遍。',strict:'分别检查内容覆盖、推理和表达；有问题先修订，再检查，通常更慢。'};
function applyOutputLanguage(language, persist = true) {
  $('outputLanguage').value = Object.hasOwn(outputLanguageDescriptions, language) ? language : 'zh';
  $('outputLanguageHint').textContent = outputLanguageDescriptions[$('outputLanguage').value];
  if (persist) return saveConversation({output_language: $('outputLanguage').value});
}
function applyReviewMode(mode, persist = true) {
  $('reviewMode').value = Object.hasOwn(reviewModeDescriptions, mode) ? mode : 'express';
  $('reviewModeHint').textContent = reviewModeDescriptions[$('reviewMode').value] + ' 这里只改变检查次数。AI 的思考强度另设，强度高时等待仍可能较久。';
  if (persist) return saveConversation({review_mode: $('reviewMode').value});
}
$('outputLanguage').onchange = () => applyOutputLanguage($('outputLanguage').value);
$('reviewMode').onchange = () => applyReviewMode($('reviewMode').value);
function applyLearningMode(mode, persist = true) {
  $('learningMode').value = Object.hasOwn(learningModeDescriptions, mode) ? mode : 'deep';
  $('learningModeHint').textContent = learningModeDescriptions[currentLearningMode()][1] + ' · 对话与讲解共用';
  if (persist) {
    const selected = currentLearningMode();
    // Desktop startup uses a new HTTP port. Persist outside origin-scoped
    // browser storage and serialize rapid changes so the last choice wins.
    learningModeSave = learningModeSave.then(() => api('/api/settings', jsonOptions('PUT', {learning_mode: selected})))
      .then(config => { if (state.settings) state.settings.learning_mode = config.learning_mode; }).catch(error);
    saveConversation({learning_mode: selected});
  }
  updateGenerationModelInfo();
  refreshModeGuideSelection();
}
$('learningMode').onchange = () => applyLearningMode(currentLearningMode());
function materialScope() { return `${state.project?.id || ''}:${state.conversation || ''}:${[...state.selected].sort().join(',')}:${$('provider').value}:${currentModel() || ''}:${currentEffort() || ''}`; }
function generationSelection() {
  return { generation_quality: 'custom', model: currentModel(), reasoning_effort: currentEffort() };
}
function assessmentSelection() {
  return { provider: $('provider').value, model: currentModel(), reasoning_effort: currentEffort() };
}
function backgroundAssessmentSelection(){
  return {...assessmentSelection(),background:true,detailed_feedback:true,conversation_id:state.conversation||null};
}
function assessmentUpload(file) {
  const body = new FormData(); body.append('file', file);
  Object.entries(assessmentSelection()).forEach(([key, value]) => { if (value) body.append(key, value); });
  return body;
}
function taskLabel(task) {
  const onlyExercises=task.kind==='generate'&&(task.only_exercises||task.payload?.only_exercises);
  const stage = task.stage || task.result?.stage || (onlyExercises ? '生成习题' : ({export:'另存讲解格式',generate:'生成讲解',read:'通读理解',knowledge:'整理知识结构',coding_generate:'生成编程作业',quiz_grade:'批改习题',coding_grade:'编程判题',feynman:'用自己的话讲解，再做进阶题',repair:'生成薄弱点练习',advance:'生成进阶练习',import:'解析文件',import_url:'读取网址'}[task.kind])) || '正在处理';
  const label=onlyExercises && stage!=='生成习题' ? `生成习题 · ${stage}` : stage;
  const request = task.request_status || task.result?.request_status;
  return request ? `${label} · ${request}` : label;
}
function renderReadingStatus() {
  const reading = state.reading;
  const stored = state.sources.filter(row => state.selected.has(row.id) && row.status === 'stored');
  $('readingBar').dataset.status = reading?.status || 'idle';
  $('readingStatus').textContent = !state.selected.size ? '可以直接提问。使用文件时，先提取要读的内容并勾选；不必先通读。'
    : reading?.status === 'completed' ? 'AI 已读完并记好笔记。可以提问、补充要求，或生成讲解文件。'
    : reading?.status === 'failed' ? `通读未完成：${reading.error || '请重试'}`
    : reading?.status === 'paused' ? `通读已暂停 · ${reading.progress||0}% · 可继续`
    : reading?.status === 'pausing' ? '正在暂停通读 · 等待当前步骤保存'
    : ['running','queued'].includes(reading?.status) ? `${reading.status==='queued'?'通读已排队':taskLabel(reading)} · ${reading.progress || 0}%`
    : stored.length
      ? stored.every(row=>row.partial_parse_supported===false) ? '资料已入库 · 点击“解析网址”或“解析图片”后即可引用'
        : stored.some(row=>row.partial_parse_supported===false) ? '资料已保存但还没读取。文档先选页码或文字；网址和图片点各自的解析按钮。'
          : '文件已保存。选择要读的页码或文字后，再开始解析。'
      : '资料可以使用了：直接提问，或先让 AI 通读并记笔记。';
  $('readMaterials').disabled = !state.ready || state.projectLoading || conversationUI.restoring || !state.selected.size || ['queued','running','pausing'].includes(reading?.status);
  $('readMaterials').textContent = reading?.status === 'completed' ? '重新通读' : reading?.status === 'paused' ? '继续通读' : '通读资料';
  $('showReadingNotes').hidden = reading?.status !== 'completed';
  $('showKnowledge').hidden = reading?.status !== 'completed';
  syncReadingNotes();
  if($('readingTaskControl'))syncTaskWidgets([...taskUI.jobs.values()].filter(x=>x.project_id===state.project?.id));
}
function scheduleReading() {
  const scope = materialScope();
  if (state.learningScope === scope) return;
  state.learningScope = scope; state.reading = null; state.readPromise = null;
  if ($('knowledgeDialog').open) $('knowledgeDialog').close();
  clearTimeout(readingTimer); renderReadingStatus();
  // Selection changes context only. Reading begins on an explicit action.
}
const readingFlows = new Map();
async function ensureReading(force = false, captured = null) {
  if(!captured){scheduleReading();clearTimeout(readingTimer);}
  const request = captured || captureStudyRequest();
  if (!request.source_ids.length) return null;
  const scope = `${request.project_id}:${request.conversation_id||''}:${[...request.source_ids].sort().join(',')}:${request.provider}:${request.model||''}:${request.reasoning_effort||''}`;
  const current = () => scope === materialScope();
  if (!force && readingFlows.has(scope)) return readingFlows.get(scope);
  if (current() && state.reading?.status === 'completed' && !force) return state.reading;
  if(current()){state.reading={status:'running',progress:0,stage:'准备通读完整原资料'};renderReadingStatus();}
  const promise = (async () => {
    try {
      await conversationSave;
      const started=await readDependency(request,force);
      if(started.reading){
        if(current()){state.reading=started.reading;renderReadingStatus();}
        saveConversation({reading_id:started.reading.reading_id},request.conversation_id,request.project_id);
        return started.reading;
      }
      for (let attempt = 0; attempt < 1800; attempt++) {
        const job = await window.studyforgeRefresh.pollTask(api,started.job_id);
        rememberTask(job);
        const reading = {job_id:job.id,status:job.status,progress:job.progress,stage:job.result?.stage,...job.result,error:job.error};
        if(current()){state.reading=reading;renderReadingStatus();}
        if(job.status==='completed'){saveConversation({reading_id:reading.reading_id},request.conversation_id,request.project_id);return reading;}
        if (job.status === 'failed') throw new Error(job.error || '通读失败，请重试');
        if(job.status==='paused'){const failure=new Error('通读已暂停，请点击“继续通读”后再生成');failure.taskPaused=true;throw failure;}
        if(job.status==='cancelled')throw new Error('通读任务已取消，可重新发起');
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      watchOutcomeTask(started.job_id).catch(error);
      const pending=new Error('通读仍在后台运行，可暂停；完成后会更新状态');pending.taskPending=true;throw pending;
    } catch (err) {
      if (current()&&!err.taskPaused&&!err.taskPending) { state.reading = { ...state.reading,status: 'failed', error: err.message }; renderReadingStatus(); }
      throw err;
    } finally {if(readingFlows.get(scope)===promise)readingFlows.delete(scope);if(current())state.readPromise=null;}
  })();
  readingFlows.set(scope,promise);if(current())state.readPromise=promise;
  return promise;
}
const levelNames = ['最简短', '较简短', '平衡', '细节较多', '最详细'];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));

const currentModel = () => $('studyModel').value || serviceModel($('provider').value) || null;
const currentEffort = () => ['codex','deepseek'].includes($('provider').value) ? ($('reasoningEffort').value || null) : null;
const modelStorageKey = () => `studyforge:model:${$('provider').value}`;
const modelPreferenceKey = () => `chat_model_${$('provider').value}`;
function storedModel() {
  if (state.conversationConfig?.provider === $('provider').value) {
    return state.conversationConfig.model_choice ?? state.conversationConfig.model ?? '';
  }
  return servicePreference($('provider').value) ?? localStorage.getItem(modelStorageKey()) ?? '';
}
function saveModelPreferences() {
  const key = modelPreferenceKey();
  const provider = $('provider').value;
  const values = provider.startsWith('svc_') ? {provider_model_preferences:{[provider]:$('studyModel').value}} : {[key]: $('studyModel').value};
  if (['codex','deepseek'].includes(provider)) values[`chat_effort_${provider}`] = $('reasoningEffort').value;
  const oldPreferences=state.settings?.provider_model_preferences||{};
  state.settings = {...state.settings, ...values};
  if(provider.startsWith('svc_'))state.settings.provider_model_preferences={...oldPreferences,[provider]:$('studyModel').value};
  localStorage.setItem(modelStorageKey(), $('studyModel').value);
  saveConversation({provider: $('provider').value, model: currentModel(), model_choice: $('studyModel').value,
    reasoning_effort: currentEffort()});
  scheduleReading();
  modelPreferenceSave = modelPreferenceSave.then(() => api('/api/settings', jsonOptions('PUT', values)))
    .catch(err => { error(new Error(`模型选择尚未保存：${err.message}；请重新选择`)); });
  return modelPreferenceSave;
}
function renderStudyModels() {
  const provider = $('provider').value;
  const catalog = serviceCatalog(provider);
  const models = [...(catalog?.models || serviceRow(provider)?.models?.map(id=>({id,name:id})) || [])];
  const configured = serviceModel(provider);
  const saved = storedModel();
  const unique = [...new Map(models.map(model => [model.id, model])).values()];
  if (configured && !unique.some(model => model.id === configured)) unique.push({id:configured, name:`${configured} · 当前设置`});
  if (saved && !unique.some(model => model.id === saved)) unique.push({ id: saved, name: `${saved} · 手动选择` });
  const defaultName = unique.find(model => model.id === configured)?.name
    || (provider === 'codex' ? unique.find(model => model.is_default)?.name : null) || '服务默认';
  $('studyModel').innerHTML = `<option value="">默认 · ${escapeHtml(defaultName)}</option>`
    + unique.map(model => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)}</option>`).join('');
  $('studyModel').value = saved;
  const effort = state.conversationConfig?.provider === provider
    ? state.conversationConfig.reasoning_effort || ''
    : state.settings?.[`chat_effort_${provider}`] ?? (provider === 'codex' ? localStorage.getItem('studyforge:reasoning') : '') ?? '';
  $('reasoningEffort').dataset.saved = effort;
  updateEffortOptions();
  updateGenerationModelInfo();
}
function updateEffortOptions() {
  const codex = $('provider').value === 'codex';
  const deepseek = $('provider').value === 'deepseek';
  const selected = currentModel() || state.settings?.codex_model || state.settings?.codex_local_default;
  const item = state.codexCatalog?.models?.find(model => model.id === selected)
    || (!selected ? state.codexCatalog?.models?.find(model => model.is_default) : null);
  const supported = new Set(deepseek ? ['none','low','high','max'] : (item?.efforts || []));
  const wanted = $('reasoningEffort').dataset.saved ?? $('reasoningEffort').value;
  const names = {none:'关闭推理',minimal:'最少',low:'低 · 更快',medium:'中',high:'高',xhigh:'极高',max:'最高',ultra:'超高'};
  $('reasoningEffort').innerHTML = `<option value="">${deepseek ? '自动 · 服务默认（高）' : '自动'}</option>`
    + [...supported].map(value => `<option value="${escapeHtml(value)}">${escapeHtml(names[value] || value)}</option>`).join('');
  $('reasoningEffort').disabled = !(codex || deepseek) || !supported.size;
  $('reasoningEffort').value = (codex || deepseek) && supported.has(wanted) ? wanted : '';
  if ((codex || deepseek) && supported.size) $('reasoningEffort').dataset.saved = $('reasoningEffort').value;
  updateModelStatus();
}
function updateModelStatus() {
  const codex = $('provider').value === 'codex';
  const provider = $('provider').value;
  const catalog = serviceCatalog(provider);
  const id = currentModel();
  const model = catalog?.models?.find(row => row.id === id);
  const source = {app_server:'Codex 实时目录',bundled:'Codex 本机备用目录',cached:'上次目录',api:serviceName(provider)+' 服务目录',documented:'DeepSeek 官方文档',manual:'手动模型列表'}[catalog?.source];
  let text = codex ? (source ? `${source} · ${catalog.models.length} 个型号` : '目录暂不可用，可在设置中指定模型')
    : `${source || serviceName(provider)} · 无需打开 Codex`;
  if(serviceRow(provider) && !serviceRow(provider).configured)text += serviceRow(provider).protocol==='gemini_cli'?' · 请先登录 Google 账号':' · 请先配置密钥';
  if (catalog?.warning) text += ` · ${catalog.warning}`;
  if (model?.note) text += ` · ${model.note}`;
  if (catalog && id && !model) text += ' · 当前型号未在目录中确认';
  if (!codex && catalog?.source === 'api' && model && !model.listed) text += ' · 手动型号未在本次服务目录中列出';
  if (codex && model && !(model.efforts || []).length) text += ' · 未返回推理档位，请使用自动';
  $('modelStatus').textContent = text;
  $('modelStatus').title = text;
}
async function loadCodexCatalog(force = false) {
  const result = await api(`/api/codex/models${force ? '?refresh=true' : ''}`);
  state.codexCatalog = result;
  updateGenerationModelInfo();
  $('codexModels').innerHTML = (result.models || []).map(model =>
    `<option value="${escapeHtml(model.id)}" label="${escapeHtml(model.name || model.id)}"></option>`).join('');
  return result;
}
async function loadDeepSeekCatalog(force = false) {
  const result = await api(`/api/deepseek/models${force ? '?refresh=true' : ''}`);
  state.deepseekCatalog = result;
  $('deepseekModels').innerHTML = (result.models || []).map(model =>
    `<option value="${escapeHtml(model.id)}" label="${escapeHtml(model.name || model.id)}"></option>`).join('');
  return result;
}
async function refreshStudyModels(force = false) {
  const token = ++modelRefreshToken;
  const provider = $('provider').value;
  renderStudyModels();
  $('reloadStudyModels').title = `刷新 ${serviceName(provider)} 模型目录（不生成内容）`;
  $('modelStatus').textContent = `正在读取 ${serviceName(provider)} 模型…`;
  try {
    await (provider === 'codex' ? loadCodexCatalog(force) : provider === 'deepseek' ? loadDeepSeekCatalog(force) : loadServiceCatalog(provider));
    if (token === modelRefreshToken && provider === $('provider').value) renderStudyModels();
  }
  catch (err) {
    if (token !== modelRefreshToken || provider !== $('provider').value) return;
    renderStudyModels();
    $('modelStatus').textContent = `目录暂不可用：${err.message}；可在设置中手动指定模型`;
  }
}

async function api(path, options = {}) {
  let response;
  try{response=await fetch(path, options);}catch(err){window.studyforgeOperationErrors?.capture(err,{path,transport:'local'});throw err;}
  if (!response.ok) {
    let detail = response.statusText;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch (_) {}
    throw window.studyforgeOperationErrors?.capture(new Error(detail),{status:response.status,path})||new Error(detail);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response;
}
const jsonOptions = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
function error(err) { const value=window.studyforgeOperationErrors?.capture(err)||err;toast(value?.message||String(value||'未知错误'),{duration:12000}); }

async function copyText(value) {
  if (window.studyforgeDesktop?.copyText) return window.studyforgeDesktop.copyText(value);
  try {
    if (navigator.clipboard?.writeText) return await navigator.clipboard.writeText(value);
  } catch (_) { /* Try the browser's selection-based copy below. */ }
  const input = document.createElement('textarea');
  input.value = value;
  input.style.position = 'fixed';
  input.style.opacity = '0';
  const focused = document.activeElement;
  (document.querySelector('dialog:modal') || document.body).appendChild(input);
  input.focus();
  input.select();
  try {
    if (!document.execCommand('copy')) throw new Error('浏览器未允许复制，请手动选中文本');
  } finally { input.remove(); if (focused?.isConnected) focused.focus({preventScroll:true}); }
}

function showView(view) {
  if (!document.getElementById(`view-${view}`)) return;
  if (view !== 'study') closeReadingNotes();
  state.view = view;
  conversationDisplayViewChanged(view);
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === `view-${view}`));
  document.querySelectorAll('[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  document.querySelectorAll('.studio-nav [data-view]').forEach(el => {
    if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
  });
  $('viewLabel').textContent={study:'学习工作台',goals:'学习路线',sources:'资料库',library:'全局书库',artifacts:'成果文档',exercises:'练习与作业',profile:'学习画像',settings:'设置与联动'}[view];
  learningGoalsViewChanged(view);
  window.libraryViewChanged?.(view);
  if (view === 'artifacts') {
    refreshArtifacts().catch(error);
    if (!artifactsPoller) artifactsPoller = setInterval(() => refreshArtifacts().catch(error), 1500);
  } else if (artifactsPoller) { clearInterval(artifactsPoller); artifactsPoller = null; }
  if (view === 'exercises') refreshExercises().catch(error);
  if (view === 'profile') {
    refreshProfile().catch(error);
    if (!profilePoller) profilePoller = setInterval(() => refreshProfile(false).catch(error), 10000);
  } else if (profilePoller) { clearInterval(profilePoller); profilePoller = null; }
  if (view === 'settings') refreshSettings().catch(error);
  if (view === 'study' && state.project) {
    refreshSources().catch(error); refreshConversations().catch(error); refreshConversationMessages().catch(error);
  }
}
document.querySelectorAll('[data-view]').forEach(el => el.addEventListener('click', () => showView(el.dataset.view)));
let artifactsPoller = null;
let profilePoller = null;

async function refreshProjects() {
  let result = await refreshNavigation();if(!result)return;
  let projects = result.projects;
  // Fresh installations get a first workspace; an intentionally empty library stays empty.
  if (!projects.length && !(await api('/api/recycle-bin/projects')).length) {
    const project=await api('/api/projects',jsonOptions('POST',{name:'我的学习'}));
    await api(`/api/projects/${project.id}/conversations`,jsonOptions('POST',{provider:$('provider').value}));
    navigationUI.expanded.add(project.id);
    result=await refreshNavigation();projects=result.projects;
  }
  setArtifactFolderProjects(projects);
  if (!state.project && projects.length) {
    const saved = await api('/api/workspace');
    const project=projects.find(row => row.id === saved.project_id) || projects[0];
    await selectProject(project,{expand:navigationUI.expanded.has(project.id)});
  }
  if(!projects.length){renderSourceUI();renderArtifactFolders();setConversationLoading(false);}
}
async function selectProject(project, {conversationId=null,expand=true}={}) {
  if(!project)return;
  if(project.id===state.project?.id){if(conversationId)await selectConversation(conversationId);return;}
  closeReadingNotes(true);
  if(state.conversation)conversationUI.scrolls.set(state.conversation,$('messages').scrollTop);
  const token = state.projectRequest = (state.projectRequest || 0) + 1;
  await flushConversation();
  if (token !== state.projectRequest) return;
  state.projectLoading = true; setConversationLoading(true);
  try {
  ++conversationUI.token; conversationUI.restoring = false;
  clearTimeout(readingTimer);
  state.project = project; state.conversation = null; state.conversationConfig = null;
  resetLearningGoals();
  renderArtifactFolders();
  state.importCategory = null; state.artifactSignature = null; state.sourceSignature = null; state.learningScope = null;
  state.reading = null; state.readPromise = null; state.selected = new Set(); state.sources = []; state.categories = [];
  conversationUI.items = []; renderConversations();
  for (const id of ['artifacts','jobs','exercises','quickSources','sources','messages']) $(id).replaceChildren();
  window.studyforgeMessageHistory.reset($('messages'));
  $('lessonFeedbackNotice').hidden = true; $('prompt').value = '';
  $('homeworkNotice').hidden=true;
  $('sourceSearch').value = '';
  $('projectTitle').textContent = project.name;
  $('messages').innerHTML = '<div class="empty-state"><div class="empty-symbol">✦</div><h3>从一个问题开始</h3><p>直接输入问题即可聊天。用自己的资料时，先上传、选范围解析，再勾选提问；不必先通读全文。</p></div>';
  if(expand)navigationUI.expanded.add(project.id);renderNavigation();saveNavigationPreferences();
  const library=refreshSources().catch(error);
  refreshArtifacts().catch(error);refreshExercises().catch(error);
  if (token !== state.projectRequest || project.id !== state.project?.id) return;
  const result = await refreshConversations();
  if (token !== state.projectRequest || !result) return;
  if (conversationId || result.active_conversation_id) await selectConversation(conversationId || result.active_conversation_id);
  else resetEmptyWorkspace();
  await library;
  } finally {
    if (token === state.projectRequest) { state.projectLoading = false; setConversationLoading(false); }
  }
}
$('newProject').onclick = () => { $('projectForm').hidden = false; $('projectName').focus(); };
$('cancelProject').onclick = () => { $('projectForm').hidden = true; $('projectName').value = ''; };
$('projectForm').addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();$('cancelProject').click();$('newProject').focus();}});
$('projectForm').onsubmit = async event => {
  event.preventDefault();
  const name = $('projectName').value.trim(); if (!name) return;
  try { const project = await api('/api/projects', jsonOptions('POST', { name })); await api(`/api/projects/${project.id}/conversations`,jsonOptions('POST',{provider:$('provider').value})); $('cancelProject').click(); await refreshProjects(); await selectProject(project); toast(`已创建项目：${name}`); }
  catch (e) { error(e); }
};

async function refreshSources() {
  if (!state.project) return;
  const projectId = state.project.id;
  const [sources, categories] = await Promise.all([
    api(`/api/projects/${projectId}/sources`), api(`/api/projects/${projectId}/categories`)]);
  if (state.project?.id !== projectId) return;
  const signature = projectId + ':' + JSON.stringify([sources, categories]);
  if (signature === state.sourceSignature) return;
  state.sourceSignature = signature;
  state.sources = sources; state.categories = categories;
  const ready = new Set(sources.filter(s => ['ready', 'stored'].includes(s.status)).map(s => s.id));
  state.selected = new Set([...state.selected].filter(id => ready.has(id)));
  // Refreshing a shared library is read-only. Saving an idle window's stale
  // selection here erases material choices made on the phone or another window.
  if (state.importCategory && !categories.some(c => c.id === state.importCategory)) state.importCategory = null;
  renderSourceUI();
}
function persistSelection() {
  return saveConversation({source_ids: [...state.selected]});
}
function setSourceSelected(sourceId, selected) {
  if(!state.conversation)return toast('请先在项目里新建对话，再选用资料');
  if (!state.ready || state.projectLoading || conversationUI.restoring) return;
  const source = state.sources.find(item => item.id === sourceId);
  if (!source || !['ready', 'stored'].includes(source.status)) return;
  if (selected) state.selected.add(sourceId); else state.selected.delete(sourceId);
  persistSelection(); renderSourceUI();
}
function toggleCategory(categoryId) {
  if(!state.conversation)return toast('请先在项目里新建对话，再选用资料');
  const available = state.sources.filter(s => ['ready', 'stored'].includes(s.status) && (categoryId === '__artifacts__' ? s.artifact_id : !s.artifact_id && (s.category_id || '') === categoryId));
  if (!available.length) return;
  available.forEach(s => state.selected.add(s.id));
  persistSelection(); renderSourceUI();
  toast(`已选用 ${available.length} 份资料，可直接对话或生成讲解`);
}
function categoryGroups() {
  return [{ id: '', name: '未分类' }, ...state.categories].map(category => ({
    ...category, sources: state.sources.filter(s => !s.artifact_id && (s.category_id || '') === category.id)
  })).concat([{id:'__artifacts__',name:'本项目成果',sources:state.sources.filter(s => s.artifact_id)}]);
}
function renderSourceUI() {
  const quickScroll=$('quickSources').scrollTop;
  const focused=document.activeElement?.dataset.quickSource;
  const previews=[...$('sources').querySelectorAll('[id^="preview-"]:not([hidden])')].map(node=>({id:node.id,html:node.innerHTML,scroll:node.scrollTop}));
  const readyCount = state.sources.filter(s => ['ready', 'stored'].includes(s.status)).length;
  $('sourceCount').textContent = `${readyCount} 份可用 / 共 ${state.sources.length} 份`;
  $('selectedCount').textContent = `${state.selected.size} 份已选`;
  const selected = state.sources.filter(s => state.selected.has(s.id));
  $('selectedSources').innerHTML = selected.length
    ? selected.map(s => `<button type="button" class="selected-chip" data-remove-source="${s.id}" title="移出当前对话">${escapeHtml(s.name)} <span aria-hidden="true">×</span></button>`).join('')
    : '<span class="small-note">选择下方资料，或一键选用整类。</span>';
  $('selectedSources').hidden = !selected.length;
  document.querySelector('.selected-label').hidden = !selected.length;
  const options = `<option value="">未分类</option>${state.categories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('')}`;
  for (const id of ['quickImportCategory', 'importCategory']) { $(id).innerHTML = options; $(id).value = state.importCategory || ''; }
  renderQuickSources(); renderLibrary(); renderCategoriesManager();
  $('quickSources').scrollTop=quickScroll;
  previews.forEach(saved=>{const node=$(saved.id);if(node){node.innerHTML=saved.html;node.hidden=false;node.scrollTop=saved.scroll;}});
  if(focused)[...$('quickSources').querySelectorAll('[data-quick-source]')].find(input=>input.dataset.quickSource===focused)?.focus({preventScroll:true});
  if (!state.ready || !state.conversation || state.projectLoading || conversationUI.restoring) document.querySelectorAll('[data-quick-source]').forEach(input => { input.disabled = true; });
  scheduleReading();
}
function renderQuickSources() {
  const query = $('sourceSearch').value.trim().toLocaleLowerCase();
  const groups = categoryGroups().map(group => ({
    ...group, visible: group.sources.filter(s => !query || group.name.toLocaleLowerCase().includes(query) || s.name.toLocaleLowerCase().includes(query))
  })).filter(group => group.visible.length || (!query && group.id));
  $('quickSources').innerHTML = groups.length ? groups.map(group => {
    const ready = group.sources.filter(s => ['ready', 'stored'].includes(s.status));
    return `<section class="quick-group ${group.id === '__artifacts__' ? 'artifact-quick-group' : ''}"><div class="quick-group-head"><strong>${escapeHtml(group.name)} <small>${ready.length}</small></strong><button type="button" data-toggle-category="${group.id}" ${ready.length ? '' : 'disabled'}>选用整类</button></div><div class="quick-group-items">${group.visible.map(s => `<label class="quick-source ${!['ready', 'stored'].includes(s.status) ? 'unavailable' : ''}"><input type="checkbox" data-quick-source="${s.id}" ${state.selected.has(s.id) ? 'checked' : ''} ${!['ready', 'stored'].includes(s.status) ? 'disabled' : ''}><span title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>${!['ready', 'stored'].includes(s.status) ? `<em>${s.status === 'pending' ? '解析中' : '失败'}</em>` : ''}</label>`).join('') || '<p class="small-note">此分类暂无资料</p>'}</div></section>`;
  }).join('') : '<div class="quick-empty">没有匹配的资料。可直接添加文件或网址。</div>';
}
function renderLibrary() {
  const groups = categoryGroups().filter(group => group.sources.length || group.id);
  $('sources').innerHTML = state.sources.length ? groups.map(group => {
    const ready = group.sources.filter(s => ['ready', 'stored'].includes(s.status));
    return `<section class="library-group"><div class="library-group-head"><div><h3>${escapeHtml(group.name)}</h3><span>${group.sources.length} 份资料</span></div><button type="button" data-library-category="${group.id}" ${ready.length ? '' : 'disabled'}>整类加入对话</button></div><div class="card-list">${group.sources.map(s => `<article class="card"><div class="card-title"><h3>${escapeHtml(s.name)}</h3><span class="badge ${s.status === 'error' ? 'error' : ''}">${{ready:'可用',stored:s.partial_parse_supported===false?'已入库 · 待解析'+(s.parse_type==='url'?'网址':'图片'):'已入库 · 待选择范围',pending:'解析中',error:'解析失败'}[s.status] || escapeHtml(s.status)}</span></div><p>${escapeHtml(s.kind)} ${s.error ? ' · ' + escapeHtml(s.error) : ''}</p><div class="card-actions"><button type="button" data-use-source="${s.id}" ${!['ready', 'stored'].includes(s.status) ? 'disabled' : ''}>${state.selected.has(s.id) ? '已加入对话 · 点击移出' : '加入当前对话'}</button><label class="move-label">移动到<select data-move-source="${s.id}"><option value="">未分类</option>${state.categories.map(c => `<option value="${c.id}" ${s.category_id === c.id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('')}</select></label><button type="button" data-preview="${s.id}">查看内容</button><button type="button" data-delete-source="${s.id}" ${s.status === 'pending' ? 'disabled' : ''}>删除</button></div><div class="exercise-body" id="preview-${s.id}" hidden></div></article>`).join('')}</div></section>`;
  }).join('') : '<div class="quick-empty">资料库还是空的。导入文件或网址后就能在学习对话中直接使用。</div>';
  for (const source of state.sources.filter(s => s.artifact_id)) {
    const card = $(`preview-${source.id}`)?.closest('.card');
    if (!card) continue;
    card.querySelector('.move-label')?.remove();
    const remove = card.querySelector('[data-delete-source]');
    if (remove) { remove.removeAttribute('data-delete-source'); remove.textContent = '管理成果'; remove.onclick = () => showView('artifacts'); }
  }
  for (const source of state.sources.filter(s => ['stored','error'].includes(s.status) && (s.origin_url || /^https?:\/\//.test(s.name)))) {
    const actions = $(`preview-${source.id}`)?.previousElementSibling;
    if (!actions) continue;
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = '浏览器读取';
    button.onclick = async () => { button.disabled=true;try { await importInBrowser(source.origin_url || source.name, state.project.id, source.category_id, state.conversation, source.id); } catch (err) { error(err); } finally {button.disabled=false;} };
    actions.append(button);
  }
}
function renderCategoriesManager() {
  $('categoriesManager').innerHTML = state.categories.length ? state.categories.map(c => `<div class="category-manage"><div><strong>${escapeHtml(c.name)}</strong><small>${c.source_count} 份资料</small></div><div class="category-actions"><button type="button" data-manager-select="${c.id}">整类选用</button><button type="button" data-rename-category="${c.id}">重命名</button><button type="button" data-delete-category="${c.id}">删除分类</button></div><form class="inline-form rename-form" data-rename-form="${c.id}" hidden><input maxlength="80" value="${escapeHtml(c.name)}" required><button type="submit" class="secondary">保存</button></form></div>`).join('') : '<p class="small-note">还没有自建分类。可按学科、课程或专题创建。</p>';
}
$('sourceSearch').oninput = renderQuickSources;
$('quickSources').onchange = event => { const id = event.target.dataset.quickSource; if (id) setSourceSelected(id, event.target.checked); };
$('quickSources').onclick = event => { const button = event.target.closest('[data-toggle-category]'); if (button) toggleCategory(button.dataset.toggleCategory); };
$('selectedSources').onclick = event => { const button = event.target.closest('[data-remove-source]'); if (button) setSourceSelected(button.dataset.removeSource, false); };
$('selectAllSources').onclick = () => { state.sources.filter(s => ['ready', 'stored'].includes(s.status)).forEach(s => state.selected.add(s.id)); persistSelection(); renderSourceUI(); };
$('clearSources').onclick = () => { state.selected.clear(); persistSelection(); renderSourceUI(); };
$('quickAddFile').onclick = () => $('composerFiles').click();
$('quickAddUrl').onclick = () => { $('composerUrlForm').hidden = false; $('composerUrl').focus(); };
for (const id of ['quickImportCategory', 'importCategory']) $(id).onchange = event => {
  state.importCategory = event.target.value || null;
  $('quickImportCategory').value = state.importCategory || '';
  $('importCategory').value = state.importCategory || '';
};
$('createCategoryForm').onsubmit = async event => {
  event.preventDefault();
  try { const category = await api(`/api/projects/${state.project.id}/categories`, jsonOptions('POST', { name: $('categoryName').value.trim() })); $('categoryName').value = ''; await refreshSources(); state.importCategory = category.id; renderSourceUI(); toast(`已创建分类：${category.name}`); }
  catch (e) { error(e); }
};
$('categoriesManager').onclick = async event => {
  const select = event.target.closest('[data-manager-select]'); if (select) { toggleCategory(select.dataset.managerSelect); showView('study'); return; }
  const rename = event.target.closest('[data-rename-category]'); if (rename) { const form = document.querySelector(`[data-rename-form="${rename.dataset.renameCategory}"]`); form.hidden = !form.hidden; if (!form.hidden) form.querySelector('input').focus(); return; }
  const remove = event.target.closest('[data-delete-category]'); if (!remove) return;
  if (remove.dataset.armed !== 'yes') { remove.dataset.armed = 'yes'; remove.textContent = '再点一次确认'; setTimeout(() => { if (remove.isConnected) { remove.dataset.armed = ''; remove.textContent = '删除分类'; } }, 5000); return; }
  try { const result = await api(`/api/categories/${remove.dataset.deleteCategory}`, { method: 'DELETE' }); await refreshSources(); toast(result.note); }
  catch (e) { error(e); }
};
$('categoriesManager').onsubmit = async event => {
  const form = event.target.closest('[data-rename-form]'); if (!form) return;
  event.preventDefault();
  try { await api(`/api/categories/${form.dataset.renameForm}`, jsonOptions('PUT', { name: form.querySelector('input').value.trim() })); await refreshSources(); toast('分类已重命名'); }
  catch (e) { error(e); }
};
$('sources').onchange = async event => {
  const id = event.target.dataset.moveSource; if (!id) return;
  try { await api(`/api/sources/${id}/category`, jsonOptions('PUT', { category_id: event.target.value || null })); await refreshSources(); toast('资料已移动'); }
  catch (e) { error(e); await refreshSources(); }
};
$('sources').onclick = async event => {
  const group = event.target.closest('[data-library-category]'); if (group) { toggleCategory(group.dataset.libraryCategory); showView('study'); return; }
  const use = event.target.closest('[data-use-source]'); if (use) { setSourceSelected(use.dataset.useSource, !state.selected.has(use.dataset.useSource)); showView('study'); return; }
  const preview = event.target.closest('[data-preview]');
  if (preview) { try { const box = $(`preview-${preview.dataset.preview}`); if (!box.hidden) { box.hidden = true; return; } const data = await api(`/api/sources/${preview.dataset.preview}`); box.innerHTML = data.segments.slice(0, 30).map(x => `<p><b>${escapeHtml(x.locator)}</b><br>${escapeHtml(x.text).slice(0, 1000)}</p>`).join('') || '<p>没有可预览内容</p>'; box.hidden = false; } catch (e) { error(e); } return; }
  const remove = event.target.closest('[data-delete-source]'); if (!remove) return;
  if (remove.dataset.armed !== 'yes') { remove.dataset.armed = 'yes'; remove.textContent = '再点一次确认删除'; setTimeout(() => { if (remove.isConnected) { remove.dataset.armed = ''; remove.textContent = '删除'; } }, 5000); return; }
  try { const result = await api(`/api/sources/${remove.dataset.deleteSource}`, { method: 'DELETE' }); state.selected.delete(result.source_id); persistSelection(); await refreshSources(); toast(result.note); }
  catch (e) { error(e); }
};
async function trackJob(jobId) {
  for (let i = 0; i < 1800; i++) {
    const job = await window.studyforgeRefresh.pollTask(api,jobId);
    const visible = state.project?.id === job.project_id;
    if (visible) $('status').textContent = `${taskLabel(job)} · ${job.progress}%`;
    if (job.status === 'completed') {
      toast('任务已完成');
      if (visible) { $('status').textContent = '本机工作台'; await Promise.all([refreshSources(), refreshArtifacts(), refreshExercises(), refreshConversations()]); if(state.project?.id===job.project_id)await refreshConversationMessages(); }
      return job;
    }
    if (job.status === 'failed') { if(visible){$('status').textContent = job.result?.stage || '任务失败'; await Promise.all([refreshSources(), refreshArtifacts()]);} const failure = new Error(job.error); failure.requiresBrowser = job.result?.requires_browser; throw failure; }
    if (job.status === 'paused' || job.status === 'cancelled') { if(visible)await refreshArtifacts(); return job; }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  throw new Error('任务仍在运行，请稍后查看成果文档');
}
async function uploadFiles(files) {
  if (!state.project || !files?.length) return;
  const projectId = state.project.id;
  const conversationId = state.conversation;
  const categoryId = state.importCategory;
  for (const file of files) {
    try {
      const body = new FormData();
      body.append('project_id', projectId); body.append('file', file);
      if (categoryId) body.append('category_id', categoryId);
      const result = await api('/api/import/file', { method: 'POST', body });
      if (state.project?.id === projectId) await refreshSources();
      const selectUploaded = () => {
        if (state.project?.id === projectId && state.conversation === conversationId && state.settings?.auto_select_imports !== false)
          setSourceSelected(result.source_id, true);
      };
      if (result.job_id) trackJob(result.job_id).then(selectUploaded).catch(error);
      else selectUploaded();
      toast(`已入库：${file.name}。${result.parse_type==='image'?'点击“解析图片”后才会识别。':'选择解析范围后才会读取内容。'}`);
    } catch (e) { error(e); }
  }
  await refreshSources();
}
$('fileInput').onchange = e => { uploadFiles(e.target.files); e.target.value = ''; };
$('attachFiles').onclick = () => $('composerFiles').click();
$('composerFiles').onchange = async e => { await uploadFiles(e.target.files); e.target.value = ''; showView('study'); };
$('studyDropZone').onclick = () => $('composerFiles').click();
$('studyDropZone').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('composerFiles').click(); } };
const studyView = $('view-study');
let studyDragDepth = 0;
const draggingFiles = event => [...(event.dataTransfer?.types || [])].includes('Files');
studyView.addEventListener('dragenter', event => {
  if (!draggingFiles(event)) return;
  event.preventDefault(); studyDragDepth += 1; $('studyDropOverlay').hidden = false;
});
studyView.addEventListener('dragover', event => { if (draggingFiles(event)) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } });
studyView.addEventListener('dragleave', event => {
  if (!draggingFiles(event)) return;
  studyDragDepth = Math.max(0, studyDragDepth - 1);
  if (!studyDragDepth) $('studyDropOverlay').hidden = true;
});
studyView.addEventListener('drop', event => {
  if (!draggingFiles(event)) return;
  event.preventDefault(); studyDragDepth = 0; $('studyDropOverlay').hidden = true;
  if (event.dataTransfer.files.length) uploadFiles(event.dataTransfer.files).catch(error);
});
window.addEventListener('dragover', event => { if (draggingFiles(event)) event.preventDefault(); });
window.addEventListener('drop', event => {
  if (!draggingFiles(event)) return;
  event.preventDefault();
  if (state.view === 'study' && !studyView.contains(event.target) && event.dataTransfer.files.length)
    uploadFiles(event.dataTransfer.files).catch(error);
});
$('dropZone').ondragover = e => { e.preventDefault(); e.currentTarget.classList.add('drag'); };
$('dropZone').ondragleave = e => e.currentTarget.classList.remove('drag');
$('dropZone').ondrop = e => { e.preventDefault(); e.currentTarget.classList.remove('drag'); uploadFiles(e.dataTransfer.files); };
async function importInBrowser(url, projectId = state.project?.id, categoryId = state.importCategory, conversationId = state.conversation, replaceSourceId = null) {
  if (!projectId) throw new Error('请先新建或选择学习项目');
  if (!window.studyforgeDesktop?.importBrowserPage) throw new Error('浏览器导入需要桌面版；也可上传本地视频、PDF 或 HTML');
  toast('请在新窗口完成登录或验证：视频播放后点“导入视频内容”，文章点“导入当前页面”');
  const page = await window.studyforgeDesktop.importBrowserPage(url);
  if (!page) return null;
  const result = await api('/api/import/browser-page', jsonOptions('POST', {...page, project_id: projectId, category_id: categoryId}));
  if (result.kind === 'video') toast('已识别视频，只读取字幕／语音和画面，不读取页面评论或推荐');
  trackJob(result.job_id).then(async job => {
    if(job.status!=='completed')return;
    if(replaceSourceId){await api(`/api/sources/${replaceSourceId}`,{method:'DELETE'});state.selected.delete(replaceSourceId);}
    if (state.project?.id === projectId && state.conversation === conversationId && state.settings?.auto_select_imports !== false) setSourceSelected(result.source_id, true);
    if(state.project?.id===projectId)await refreshSources();
  }).catch(error);
  await refreshSources();
  return result;
}
async function importUrl(url) {
  if (!state.project) return toast('请先创建学习项目');
  const projectId = state.project.id, conversationId = state.conversation;
  const result = await api('/api/import/url', jsonOptions('POST', { project_id: projectId, url, category_id: state.importCategory }));
  await refreshSources();
  if(state.project?.id===projectId && state.conversation===conversationId && state.settings?.auto_select_imports!==false)
    setSourceSelected(result.source_id,true);
  toast('网址已入库，尚未读取；点击资料旁的“解析网址”即可读取。');
}
$('libraryUrlForm').onsubmit = async event => { event.preventDefault(); try { await importUrl($('videoUrl').value.trim()); $('videoUrl').value = ''; } catch (e) { error(e); } };
$('attachUrl').onclick = () => { $('composerUrlForm').hidden = !$('composerUrlForm').hidden; if (!$('composerUrlForm').hidden) $('composerUrl').focus(); };
$('composerUrlForm').onsubmit = async event => { event.preventDefault(); try { await importUrl($('composerUrl').value.trim()); $('composerUrl').value = ''; $('composerUrlForm').hidden = true; } catch (e) { error(e); } };

function makeMessage(role, value = '',id,projectId=state.project?.id,conversationId=state.conversation,reply_reference) { const el = document.createElement('div'); el.className = `message ${role}`; const label = document.createElement('span'); label.className = 'role'; label.textContent = role === 'user' ? '你' : 'AI 导师'; const content = document.createElement('div'); content.className = 'message-content'; if (role === 'assistant' && value) renderLessonText(content, value); else content.textContent = value; el.append(label, content);if(id&&projectId&&conversationId){el.dataset.exportMessage=id;el.exportMessage={id,role,content:value,projectId,conversationId,reply_reference};window.studyforgeDocumentExports?.attachMessage(el);window.studyforgeMessageFocus?.attach(el);} return el; }
function message(role, value = '') { const empty = $('messages').querySelector('.empty-state'); if (empty) empty.remove(); const el=makeMessage(role,value);$('messages').append(el); $('messages').scrollTop = $('messages').scrollHeight; return el.querySelector('.message-content'); }
$('sendMessage').onclick = async () => {
  const active=liveChats.get(state.conversation);
  if(active){active.cancelRequested=true;active.controller.abort();syncWorkControls();return;}
  const text=$('prompt').value.trim();if(!text||isChatBusy()||!state.ready||state.projectLoading||conversationUI.restoring)return;
  const request={...captureStudyRequest(),text};
  request.reply_reference=window.studyforgeMessageFocus?.capture(request.project_id,request.conversation_id)||null;
  if($('chatSourceMode').value==='none'){request.source_ids=[];request.include_materials=false;}
  const live={request,text,answer:'',status:'准备回复…',output:null,finished:false,controller:new AbortController()};
  liveChats.set(request.conversation_id,live);
  live.priorMessageIds=window.studyforgeMessageHistory.ids($('messages'));
  $('prompt').value='';live.userNode=message('user',text).parentElement;live.output=message('assistant');syncWorkControls();
  try {
    await waitForChatStep(agentPermissionSave,live);
    await waitForChatStep(window.libraryFlush?.(request.conversation_id),live);
    await waitForChatStep(saveConversation({draft:''},request.conversation_id,request.project_id),live);
    const reading = state.reading?.reading_id ? state.reading : null;
    if(reading)request.reading_id=reading.reading_id;
    live.status='等待导师回复…';if(live.output?.isConnected)showReplyStatus(live.output,live.status);
    await consumeTutorResponse(await fetch('/api/chat/stream',{...jsonOptions('POST',request),signal:live.controller.signal}),live);
    window.studyforgeMessageFocus?.sent(request);
    if(inCapturedChat(request)&&$('speakReplies').checked&&live.answer){const audio=await api('/api/voice/speak',jsonOptions('POST',{text:live.answer.slice(0,3000)}));const url=URL.createObjectURL(await audio.blob());const player=new Audio(url);player.onended=()=>URL.revokeObjectURL(url);player.play();}
  }catch(failure){
    if(live.controller.signal.aborted){live.answer+='\n\n[本次回复已停止，以上内容尚未完成。]';paintLiveReply(live);}
    else{live.answer+=`\n\n[错误：${failure.message}]`;paintLiveReply(live);if(inCapturedChat(request)&&!$('prompt').value)$('prompt').value=text;error(failure);}
  }
  finally{live.finished=true;live.status='';live.waitingApproval=false;
    if(live.output?.isConnected)showReplyStatus(live.output,'');
    liveChats.delete(request.conversation_id);syncWorkControls();
    await refreshConversations().catch(error);if(inCapturedChat(request)){await refreshConversationMessages().catch(error);saveConversation({draft:$('prompt').value});}}
};
$('prompt').onkeydown = e => {
  if (e.isComposing || e.keyCode === 229 || e.key !== 'Enter') return;
  const control = document.documentElement.dataset.sendKey === 'ctrl-enter';
  if (!e.shiftKey && (control ? e.ctrlKey || e.metaKey : !e.ctrlKey && !e.metaKey)) {
    if(isChatBusy()){e.preventDefault();return;}
    e.preventDefault(); $('sendMessage').click();
  }
};
$('summaryLevel').oninput = () => $('summaryLabel').textContent = levelNames[Number($('summaryLevel').value) - 1];
$('withExercises').onchange = () => $('exerciseFormatWrap').hidden = !$('withExercises').checked;
$('readMaterials').onclick = () => {
  const stored = state.sources.find(row => state.selected.has(row.id) && row.status === 'stored');
  if(stored){ if(window.openSourceScope)window.openSourceScope(stored.id).catch(error); return; }

  if(['pausing','paused'].includes(state.reading?.status)&&state.reading.job_id)return changeTask(state.reading.job_id,'resume').catch(error);
  ensureReading(true).catch(failure=>{if(!failure.taskPaused)error(failure);});
};
$('generate').onclick = async () => {
  if (generationLaunches.has(state.conversation) || !state.ready || state.projectLoading || conversationUI.restoring) return;
  const onlyExercises = $('generationContent').value === 'exercises';
  const stored = state.sources.find(row => state.selected.has(row.id) && row.status === 'stored');
  if(stored){ if(window.openSourceScope)window.openSourceScope(stored.id).catch(error); return toast(stored.partial_parse_supported===false?'正在解析所选网址或图片，完成后再生成成果。':'先选择资料的解析范围，再生成成果。'); }

  if (!state.selected.size && !window.libraryHasPrimary?.() && (!onlyExercises || !$('prompt').value.trim())) return toast('请选择项目资料或书库重点节点，或在只出题时填写出题范围');
  const request={...captureStudyRequest(),format:$('outputFormat').value,summary_level:Number($('summaryLevel').value),
    exercises:$('withExercises').checked||onlyExercises,only_exercises:onlyExercises,exercise_format:$('exerciseFormat').value,
    review_mode:$('reviewMode').value,parallel:$('generationParallel').checked,instructions:$('prompt').value.trim(),
    mentor_provider:$('provider').value,mentor_model:currentModel(),mentor_reasoning_effort:currentEffort()};
  generationLaunches.add(request.conversation_id);syncWorkControls();
  try {
    await conversationSave;
    await window.libraryFlush?.(request.conversation_id);
    const dependency=await readDependency(request);
    if(dependency.reading)request.reading_id=dependency.reading.reading_id;
    else if(dependency.job_id){request.reading_job_id=dependency.job_id;watchOutcomeTask(dependency.job_id).catch(error);}
    const result=await api('/api/generate',jsonOptions('POST',request));
    if(inCapturedChat(request)&&request.instructions&&$('prompt').value.trim()===request.instructions){
      message('user',(onlyExercises?'本次出题要求：':'本次讲解要求：')+request.instructions);$('prompt').value='';saveConversation({draft:''});}
    refreshConversations().catch(error);
    toast(`当前导师继续${onlyExercises ? '出题' : '生成讲解'}${result.model ? ' · ' + result.model : ''}`);
    trackJob(result.job_id).catch(error);
  } catch(e) { error(e); }
  finally {generationLaunches.delete(request.conversation_id);syncWorkControls();}
};

const artifactsRefreshing = new Map();
const jobDeleteArmed = new Map();
function refreshArtifacts() {
  if (!state.project) return Promise.resolve();
  const projectId = state.project.id, projectVersion = state.projectRequest, sort = $('artifactSort').value;
  const key = JSON.stringify([projectId, projectVersion, sort]);
  if (!artifactsRefreshing.has(key)) {
    const pending = loadProjectArtifacts(projectId, projectVersion, sort).finally(() => artifactsRefreshing.delete(key));
    artifactsRefreshing.set(key, pending);
  }
  return artifactsRefreshing.get(key);
}
async function loadProjectArtifacts(projectId, projectVersion, sort) {
    const [artifacts, jobs, feedbacks, folders, homework] = await Promise.all([api(`/api/projects/${projectId}/artifacts?sort=${encodeURIComponent(sort)}`), api(`/api/projects/${projectId}/jobs`), api(`/api/projects/${projectId}/lesson-feedback`), api('/api/artifact-folders'),api(`/api/projects/${projectId}/homework`)]);
    if (state.project?.id !== projectId || state.projectRequest !== projectVersion || $('artifactSort').value !== sort) return;
    setArtifactFolderProjects(folders);
    syncLessonFeedback(feedbacks, projectId);
    syncHomework(homework,projectId);
    syncTaskWidgets(jobs.map(job=>({...job,project_id:projectId})));
    const visibleJobs = jobs.filter(x => $('showJobHistory').checked || ['queued', 'running', 'pausing', 'paused', 'failed'].includes(x.status));
    $('jobs').innerHTML = visibleJobs.map(x => {
      const progress = Math.max(0, Math.min(100, Number(x.progress) || 0));
      const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(x.created_at)) / 1000));
      const time = elapsed >= 60 ? `${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒` : `${elapsed} 秒`;
      const label = taskLabel(x);
      const retryText = window.studyforgeTaskRetry?.summary(x);
      const statusText = x.status === 'failed' ? escapeHtml(window.studyforgeOperationErrors?.summary(x.error||'任务失败')||x.error||'任务失败')
        : x.status === 'paused' ? '已暂停 · 进度已保留，可继续'
        : x.status === 'pausing' ? '正在暂停 · 等待当前步骤完成并保存结果'
        : x.status === 'completed' ? '已完成' : x.status === 'cancelled' ? '已取消'
        : x.retry?.state==='waiting' ? '等待服务恢复 · 可以继续使用其他功能' : `运行中 · 已用 ${time}`;
      const control = x.status==='failed'&&x.recovery?.available ? `<button type="button" data-generation-control="${x.id}" data-action="retry" title="${escapeHtml(x.recovery.reason)}">重试未完成步骤</button>` : x.status==='paused'&&x.waiting_for_causes ? `<button type="button" data-homework-open="${x.homework_attempt_id}">填写错因问卷</button>` : x.can_pause && ['queued','running','pausing','paused'].includes(x.status)
        ? `<button type="button" data-generation-control="${x.id}" data-action="${['pausing','paused'].includes(x.status) ? 'resume' : 'pause'}">${['pausing','paused'].includes(x.status) ? '继续任务' : '暂停任务'}</button>` : '';
      const deleting = Date.now()-(jobDeleteArmed.get(x.id)||0)<5000;
      const scheduling=`<div class="job-scheduling"><span>模型运行 ${x.execution?.running||0} · 排队 ${x.execution?.queued||0}</span>${x.parallel!=null?`<span>内部${x.parallel?'并行':'顺序'}生成</span>`:''}${retryText?`<span role="status" class="task-retry-status">${escapeHtml(retryText)}</span>`:''}</div>`;
      return `<div class="job-card" data-local-job="${x.id}" data-generation-status="${escapeHtml(x.status)}"><div class="job-meta"><strong>${escapeHtml(label)}</strong><span>${x.status==='failed'?'未完成':progress+'%'}</span></div><div class="progress" role="progressbar" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100"${x.status==='failed'?' aria-valuetext="任务未成功完成"':''}><i style="width:${progress}%"></i></div>${scheduling}<div class="job-controls"><small>${statusText}</small>${control}<button type="button" class="danger-action" data-delete-job="${x.id}">${deleting ? '再点确认删除' : ['queued','running','pausing','paused'].includes(x.status) ? '取消并删除任务' : '删除记录'}</button></div></div>`;
    }).join('');
    for(const row of visibleJobs)if(row.status==='failed')window.studyforgeOperationErrors?.attach($('jobs').querySelector(`[data-local-job="${row.id}"] .job-controls`),row.error||'任务失败');
    for(const row of visibleJobs)if(row.status==='failed'&&row.recovery){const note=document.createElement('p');note.className='small-note';note.textContent=row.recovery.reason+(row.recovery.manual_count?' · 已手动重试 '+row.recovery.manual_count+' 次':'');$('jobs').querySelector(`[data-local-job="${row.id}"]`).append(note);}
    for(const row of visibleJobs)window.studyforgeDocumentExports?.attachJob(row,$('jobs').querySelector(`[data-local-job="${row.id}"] .job-controls`),projectId);
    for(const row of visibleJobs)window.studyforgeTaskTiming?.attachJob(row,$('jobs').querySelector(`[data-local-job="${row.id}"] .job-controls`));
    const active = visibleJobs.find(x => ['running', 'queued', 'pausing'].includes(x.status));
    if (active) $('status').textContent = `${taskLabel(active)} · ${active.progress}%`;
    else if(visibleJobs.some(x=>x.status==='paused'&&x.waiting_for_causes))$('status').textContent='等待错因问卷 · 批改文档已暂停';
    else if (!isChatBusy()) $('status').textContent = visibleJobs.some(x=>x.status==='paused')?'有任务已暂停 · 可继续':'本机工作台';
    const signature = `${projectId}:${sort}:${JSON.stringify(artifacts.map(a => [a.id, a.title, a.download_filename, a.origin,a.export_formats]))}`;
    if (signature !== state.artifactSignature) {
      state.artifactSignature = signature;
      const kinds = { explanation: 'AI 讲解', original: '视频原文档', exercise: '配套习题', solutions: '原题与答案解析', grading:'批改与错题讲解', external: '联动成果', review: '作业审查' };
      $('artifacts').innerHTML = artifacts.length ? artifacts.map(a => `<div class="card" data-artifact="${a.id}"><div class="card-title"><h3>${escapeHtml(a.title)}</h3><span class="badge">${escapeHtml(a.format.toUpperCase())}</span></div><p>${escapeHtml(kinds[a.kind] || a.kind)} · ${escapeHtml(new Date(a.created_at).toLocaleString('zh-CN'))}</p><div class="artifact-name">${escapeHtml(a.download_filename || a.title)}</div><div class="card-actions"><a href="${a.download_url}" download="${escapeHtml(a.download_filename || '')}" title="保存为 ${escapeHtml(a.download_filename || a.title)}">下载文件 ↓</a><button type="button" data-rename-artifact="${a.id}">重命名</button><button type="button" class="danger-action" data-delete-artifact="${a.id}">删除</button></div><form class="inline-form artifact-rename" data-artifact-rename-form="${a.id}" hidden><input aria-label="成果文件名称" maxlength="100" value="${escapeHtml(a.title)}" required><button type="submit" class="secondary">保存名称</button><button type="button" data-cancel-artifact-rename="${a.id}">取消</button></form></div>`).join('') : '<div class="artifact-empty"><span aria-hidden="true">▱</span><h3>这个项目还没有成果</h3><p class="small-note">在学习工作台生成的讲解、习题及其他成果会保存到这里。</p><button type="button" class="secondary" data-view="study">去学习工作台</button></div>';
      $('artifacts').querySelector('[data-view="study"]')?.addEventListener('click', () => showView('study'));
      artifacts.forEach((artifact, index) => {
        const meta = artifact.metadata;
        if (!meta) return;
        const card = $('artifacts').children[index];
        window.studyforgeDocumentExports?.attachArtifact(artifact,card.querySelector('.card-actions'),projectId);
        const origin = document.createElement('p'); origin.className = 'artifact-origin';
        if (artifact.origin) {
          origin.append('来源对话：');
          const link = document.createElement(artifact.origin.deleted ? 'span' : 'button');
          link.textContent = artifact.origin.title+(artifact.origin.deleted ? '（已删除）' : '');
          if (!artifact.origin.deleted) { link.type='button'; link.dataset.originConversation=artifact.origin.conversation_id; }
          origin.append(link);
        } else origin.textContent = '来源：项目任务或导入成果（未记录对话）';
        card.insertBefore(origin, card.querySelector('.card-actions'));
        if (artifact.kind === 'explanation' && meta.generation_job_id && !artifact.origin?.deleted) {
          const button = document.createElement('button'); button.type = 'button';
          button.dataset.feedbackJob = meta.generation_job_id; button.textContent = '理解反馈 · 请导师补讲';
          card.querySelector('.card-actions').append(button);
        }
        if (meta.mentor_handoff) renderMentorHandoff(card, meta.mentor_handoff);
        const teachingReview = window.studyforgeTeachingReview?.create(meta,artifact.id,artifact.kind);
        if (teachingReview) card.insertBefore(teachingReview,card.querySelector('.card-actions'));
        if(meta.reexport){const reused=document.createElement('p');reused.className='small-note';reused.textContent='本机另存 · 0 次新增模型请求 · 沿用原讲解正文与来源，内容未改写。';card.insertBefore(reused,card.querySelector('.card-actions'));}
        if(meta.delivery){
          const data=meta.delivery,details=document.createElement('details');details.className='delivery-check small-note';
          const summary=document.createElement('summary');summary.textContent='格式与运行验证';details.append(summary);
          const info=document.createElement('p');info.textContent=data.detail||'文件已写入；程序尚未执行验证。';details.append(info);
          if(data.card_count){const note=document.createElement('p');note.textContent=`${data.card_count}张记忆卡片 · ${data.source_warning_count||0}项来源定位待核对。`;details.append(note);}
          for(const warning of data.source_warnings||[]){const note=document.createElement('p');note.textContent=warning;details.append(note);}
          if(data.source_warning_count>(data.source_warnings||[]).length){const note=document.createElement('p');note.textContent='来源提示仅列出前50项；每张受影响卡片的背面保留自己的核对提示。';details.append(note);}
          for(const check of data.checks||[]){if(!check)continue;const line=document.createElement('p');line.textContent=check.file+'：'+check.detail;details.append(line);}
          if(data.format_model_requests){const usage=document.createElement('p');usage.textContent=`按所选格式整理额外调用模型${data.format_model_requests}次。`;details.append(usage);}
          card.insertBefore(details,card.querySelector('.card-actions'));
        }
        if(meta.lesson_quality){
          const quality=meta.lesson_quality,details=document.createElement('details');details.className='lesson-quality small-note';
          const summary=document.createElement('summary');summary.textContent=`来源定位核对 · ${quality.matched_citations}/${quality.citation_count}处匹配${quality.warning_count?' · '+quality.warning_count+'项待核对':''}`;details.append(summary);
          const quotation=Number.isInteger(quality.verbatim_quotes)
            ? '引句片段逐字匹配 '+quality.verbatim_quotes+'/'+quality.quote_count+'；仅忽略空白匹配 '+(quality.whitespace_only_quotes||0)+' 处'
            : '旧记录引句匹配 '+quality.matched_quotes+'/'+quality.quote_count+'；未区分空白差异，不能据此确认逐字一致';
          const info=document.createElement('p');info.textContent=(quality.checked_content||'讲解正文')+' · '+quality.chapter_count+'部分完整原文输入 · 解析复用'+quality.parse_cache_hits+'份 · '+quotation+'。'+quality.note;details.append(info);
          if(quality.navigation_omitted){const omitted=document.createElement('p');omitted.textContent=`全文导航另有${quality.navigation_omitted}项未列出；导航不是原文摘要，正文仍按部分读取全部原文。`;details.append(omitted);}
          if(quality.summary_context_excerpted){const excerpt=document.createElement('p');excerpt.textContent=`总结的辅助输入已节选${quality.summary_chapters_omitted?'，另有'+quality.summary_chapters_omitted+'部分未列入总结输入':''}；已生成的讲解正文保留，总结不代表逐一覆盖全部细节。`;details.append(excerpt);}
          for(const warning of (quality.warnings||[])){const line=document.createElement('p');line.textContent=warning;details.append(line);}
          for(const result of (quality.quote_results||[]).filter(x=>x.status==='whitespace_only').slice(0,10)){const line=document.createElement('p');line.textContent='引用块'+result.quote_index+'：仅忽略空白或换行后匹配；空白变化可能改变公式、代码或词义，不能视为逐字确认。';details.append(line);}
          if(quality.warning_count>(quality.warnings||[]).length){const omitted=document.createElement('p');omitted.textContent=`记录列出前${(quality.warnings||[]).length}项，另有${quality.warning_count-(quality.warnings||[]).length}项未逐一列出，请对照原文核查。`;details.append(omitted);}
          card.insertBefore(details,card.querySelector('.card-actions'));
        }
        if (!meta.source_reading && !meta.library_evidence && !meta.library_references?.references?.length) return;
        const note = document.createElement('p'); note.className = 'small-note';
        note.textContent = window.studyforgeSourceEvidence.summary(meta,learningModeDescriptions[meta.learning_mode || 'deep']?.[0] || '模式未记录');
        card.insertBefore(note, card.querySelector('.card-actions'));
        const evidence = window.studyforgeSourceEvidence.create(meta,artifact.id);
        if (evidence) card.insertBefore(evidence, card.querySelector('.card-actions'));
        const limitations = (Array.isArray(meta.source_reading) ? meta.source_reading : []).flatMap(source => (source.limitations || []).map(note => `${source.name}：${note}`));
        if (limitations.length) { const warning = document.createElement('p'); warning.className = 'small-note'; warning.textContent = `资料有 ${limitations.length} 项待核对，请展开“资料依据”查看完整提示。`; card.insertBefore(warning, card.querySelector('.card-actions')); }
      });
    }
}

$('jobs').onclick = async event => {
  const remove = event.target.closest('[data-delete-job]');
  if (remove) {
    if (Date.now()-(jobDeleteArmed.get(remove.dataset.deleteJob)||0)>5000) { jobDeleteArmed.set(remove.dataset.deleteJob,Date.now()); remove.textContent='再点确认删除'; return; }
    remove.disabled=true;
    try { const result=await api('/api/jobs/'+remove.dataset.deleteJob,{method:'DELETE'});await refreshArtifacts();toast(result.note); }
    catch(failure){error(failure);} return;
  }
  const button = event.target.closest('[data-generation-control]'); if (!button) return;
  button.disabled = true;
  try {
    await changeTask(button.dataset.generationControl,button.dataset.action);
  } catch (err) { error(err); }
  finally { if (button.isConnected) button.disabled = false; }
};

function renderMentorHandoff(card, handoff) {
  const details = document.createElement('details'); details.className = 'mentor-handoff small-note';
  const summary = document.createElement('summary');
  summary.textContent = handoff.mode === 'default' ? '默认讲解 · 尚无对话理解证据' : '导师已交接 · 查看讲解要求与理解情况';
  details.appendChild(summary);
  const add = (tag, content) => { const element = document.createElement(tag); element.textContent = content; details.appendChild(element); };
  const mentor = handoff.mentor || {};
  add('p', `导师：${serviceName(mentor.provider)}${mentor.model ? ' · ' + mentor.model : ''}。理解观察仅用于调整教学，不是测验成绩。`);
  const packet = handoff.packet || {};
  if (packet.learning_goal) add('p', '学习目标：' + packet.learning_goal);
  for (const item of packet.instructions || []) {
    add('p', '讲解要求：' + item.instruction);
    for (const evidence of item.evidence || []) add('blockquote', '你的原话：' + evidence.quote);
  }
  const statuses = { demonstrated: '已展示理解', partial: '理解尚不完整', needs_support: '需要解释', misconception: '存在具体误解', not_assessed: '证据不足，尚未评估' };
  for (const item of packet.understanding || []) {
    add('p', `${item.topic} · ${statuses[item.status] || '尚未评估'}${item.observation ? '：' + item.observation : ''}`);
    for (const evidence of item.evidence || []) add('blockquote', '你的原话：' + evidence.quote);
    if (item.teaching_action) add('p', '讲解如何调整：' + item.teaching_action);
  }
  for (const strategy of packet.teaching_strategy || []) add('p', '教学安排：' + strategy);
  for (const question of packet.unresolved_questions || []) add('p', '待进一步确认：' + question);
  card.insertBefore(details, card.querySelector('.card-actions'));
}

$('artifactSort').value = localStorage.getItem('studyforge:artifactSort') || 'newest';
$('showJobHistory').onchange=()=>refreshArtifacts().catch(error);
initializeArtifactFolders();
if (!$('artifactSort').value) $('artifactSort').value = 'newest';
$('artifactSort').onchange = () => { localStorage.setItem('studyforge:artifactSort', $('artifactSort').value); state.artifactSignature = null; refreshArtifacts().catch(error); };
$('artifacts').onclick = async event => {
  const origin = event.target.closest('[data-origin-conversation]');
  if (origin) { try {await selectConversation(origin.dataset.originConversation);showView('study');}catch(failure){error(failure);} return; }
  const feedback = event.target.closest('[data-feedback-job]');
  if (feedback) { try { await openLessonFeedback(null, feedback.dataset.feedbackJob); } catch (failure) { error(failure); } return; }
  const rename = event.target.closest('[data-rename-artifact]');
  const cancel = event.target.closest('[data-cancel-artifact-rename]');
  if (rename || cancel) {
    const id = rename?.dataset.renameArtifact || cancel.dataset.cancelArtifactRename;
    const form = document.querySelector(`[data-artifact-rename-form="${id}"]`);
    form.hidden = Boolean(cancel) || !form.hidden;
    if (!form.hidden) { form.querySelector('input').focus(); form.querySelector('input').select(); }
    return;
  }
  const remove = event.target.closest('[data-delete-artifact]'); if (!remove) return;
  if (remove.dataset.armed !== 'yes') {
    remove.dataset.armed = 'yes'; remove.textContent = '再点一次确认删除';
    setTimeout(() => { if (remove.isConnected) { remove.dataset.armed = ''; remove.textContent = '删除'; } }, 5000); return;
  }
  try { const result = await api(`/api/artifacts/${remove.dataset.deleteArtifact}`, { method: 'DELETE' }); await Promise.all([refreshArtifacts(), refreshSources()]); persistSelection(); toast(result.note); }
  catch (err) { error(err); }
};
$('artifacts').onsubmit = async event => {
  const form = event.target.closest('[data-artifact-rename-form]'); if (!form) return;
  event.preventDefault();
  try { await api(`/api/artifacts/${form.dataset.artifactRenameForm}`, jsonOptions('PUT', { name: form.querySelector('input').value.trim() })); await Promise.all([refreshArtifacts(), refreshSources()]); toast('名称已保存，下载文件也使用新名称'); }
  catch (err) { error(err); }
};

async function refreshExercises() {
  if (!state.project) return;
  capturePracticeDrafts();
  const projectId=state.project.id,token=++exerciseRefreshToken;
  const sets = await api(`/api/projects/${projectId}/exercises`);
  if(state.project?.id!==projectId||token!==exerciseRefreshToken)return;
  capturePracticeDrafts();
  const fragment=document.createDocumentFragment(),changed=[];
  for(const s of sets){
    let card=$('set-'+s.id)?.closest('.card');
    if(!card){const template=document.createElement('template');template.innerHTML=`<div class="card"><div class="card-title"><h3></h3><span class="badge"></span></div><p data-exercise-meta></p><div class="card-actions"><button data-open-set="${s.id}">打开题目</button><button data-share-set="${s.id}">复制给 Codex / Harness 的指令</button></div><div class="exercise-body" id="set-${s.id}" hidden></div></div>`;card=template.content.firstElementChild;}
    const status=s.homework?.status||s.status;
    const revision=status+'|'+String(s.homework?.current_version_matches);
    if(card.dataset.exerciseStatus!==revision&&!card.querySelector('.exercise-body').hidden)changed.push(s.id);
    card.dataset.exerciseStatus=revision;
    card.querySelector('h3').textContent=s.title;card.querySelector('.badge').textContent=s.homework?(homeworkLabels[status]||status):(exerciseStatusLabels[s.status]||s.status);
    card.querySelector('[data-exercise-meta]').textContent=`${s.questions.length} 题 · 难度 ${s.difficulty}/5${s.practice?.is_review?' · 混合复习':''}`;
    fragment.appendChild(card);
  }
  $('exercises').replaceChildren(fragment);
  if(!sets.length)$('exercises').innerHTML='<p class="small-note">还没有习题。生成讲解时可勾选“同步生成习题”；不勾选时不会安排练习或复习。</p>';
  $('exercises').querySelectorAll('[data-open-set]').forEach(el => el.onclick = () => openSet(el.dataset.openSet,false));
  $('exercises').querySelectorAll('[data-share-set]').forEach(el => el.onclick = async () => { try { await copyText(`请连接 StudyForge MCP，调用 read_assignment，assignment_id=${el.dataset.shareSet}。读取题目和相关资料，协助我完成作业；若是编程题，请在 VS Code 中编辑并通过 submit_code_file 提交。`); toast('联动指令已复制，可粘贴到 Codex 或 DeepSeek Harness'); } catch(e) { error(e); } });
  await Promise.all([refreshReviews(),...changed.map(id=>openSet(id,true))]);
}
async function openSet(id,forceOpen=true) {
  try {
    const box = $(`set-${id}`); if (!box) return; if (!forceOpen&&!box.hidden) { capturePracticeDrafts(); box.hidden = true; return; }
    const [s, submissions] = await Promise.all([api(`/api/exercises/${id}`), api(`/api/exercises/${id}/submissions`)]); const coding = Boolean(s.questions[0]?.language);
    if(!box.isConnected||state.project?.id!==s.project_id)return;
    // A historical submission must never be displayed below a revised problem.
    if(s.homework?.current_version_matches===false){box.innerHTML=homeworkRow(s.homework);box.hidden=false;return;}
    box.innerHTML = s.questions.map(q => `<div><label>第 ${q.index + 1} 题 · ${escapeHtml(q.topic)}</label><div class="practice-statement" data-question-statement="${q.index}"></div>${q.source_url ? `<a href="${escapeHtml(q.source_url)}" target="_blank" rel="noopener">题源</a>` : ''}${q.starter_code ? `<pre>${escapeHtml(q.starter_code)}</pre>` : ''}${!coding && s.status === 'assigned' && !s.homework ? `<textarea data-answer="${q.index}" placeholder="在此作答；所有题目完成后提交"></textarea>${hintControls(s,q)}` : ''}</div>`).join('');
    box.insertAdjacentHTML('afterbegin',repairLearningNote(s));
    if (s.homework) box.innerHTML+=homeworkRow(s.homework);
    if (coding && s.status==='assigned' && !s.homework) { const extension = {python:'.py',javascript:'.js',typescript:'.ts',cpp:'.cpp',matlab:'.m',wolfram:'.wl'}[s.questions[0].language]; box.innerHTML += `<input type="file" accept="${extension}" id="codeFile"><button class="secondary" id="submitCode">提交 ${escapeHtml(extension)} 文件并批改</button>`; }
    else if (s.status === 'assigned' && !s.homework) box.innerHTML += '<label>已有手写或电子版作答？</label><input type="file" id="answerFile" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"><button id="extractAnswers">提取到答题框供我核对</button><p class="small-note">图片识别可能出错；请核对每题内容后再提交。</p>'+attemptControls(s)+'<button class="secondary" id="submitAnswers">提交全部答案并批改</button>';
    else if (s.solutions) box.innerHTML += s.solutions.map(x => `<div><label>第 ${x.index + 1} 题解析</label><div class="practice-statement" data-practice-solution="${x.index}"></div><p>评分标准：${escapeHtml(x.rubric)}</p></div>`).join('');
    if (['feynman_required','feynman_retry','repair_required','repair_retry'].includes(s.status)) box.innerHTML += '<details class="practice-feynman"'+(s.status.startsWith('feynman')?' open':'')+'><summary>'+ (s.status.startsWith('feynman')?'当前费曼环节':'可选：用费曼讲解修复理解')+'</summary><label>用自己的话说明概念、推导与例子</label><textarea id="feynmanText"></textarea><button class="secondary" id="submitFeynman">提交讲解</button></details>';
    if(s.status==='retry_ready') box.innerHTML += '<p class="small-note">费曼讲解已通过并保存，可继续或查看进阶练习；重复点击会复用已生成的题目。</p><button type="button" class="secondary" id="resumeAdvance">继续生成进阶'+(coding?'作业':'习题')+'</button>';
    if (submissions.length) {
      const latest = submissions[0], grade = latest.grade || {}, feynman = latest.feynman || {};
      const feedbackTexts=[];
      const teachingText=value=>{const index=feedbackTexts.push(String(value??''))-1;return `<div data-grading-rich="${index}"></div>`;};
      const feedback = (Array.isArray(grade.feedback)?grade.feedback:[]).map((item, i) => `<article class="grading-item"><h5>第 ${i + 1} 题 · ${escapeHtml(grade.scores?.[i] ?? '尚未确定')} 分</h5>${teachingText(item)}</article>`).join('');
      const issues = (Array.isArray(grade.uncertainties)?grade.uncertainties:[]).map(item => `<li>${teachingText(item)}</li>`).join('');
      const staticReview = grade.review && grade.static_score!=null ? `<h5>静态审查 · ${escapeHtml(grade.static_score)} 分</h5>${teachingText(grade.review.feedback)}<pre class="grading-test-output">${escapeHtml(grade.test?.output || grade.test?.reason || '')}</pre>` : '';
      box.innerHTML += `<section class="grading-feedback"><h4>最近一次批改 · ${latest.score==null?'尚未定分':escapeHtml(latest.score)+' 分'}</h4>${feedback}${teachingText(grade.overall_feedback)}${issues ? `<label>有待核查</label><ul>${issues}</ul>` : ''}${staticReview}${feynman.score !== undefined ? `<h4>费曼讲解 · ${escapeHtml(feynman.score)} 分</h4>${teachingText(feynman.feedback)}${teachingText((Array.isArray(feynman.gaps)?feynman.gaps:[]).join('；'))}` : ''}</section>`;
      box.querySelectorAll('[data-grading-rich]').forEach(el=>renderLessonText(el,feedbackTexts[Number(el.dataset.gradingRich)]));
      if(!coding){box.innerHTML += practiceAfterSubmission(s,latest);renderPracticeDiagnostics(box,grade);}
    }
    box.hidden = false;
    box.querySelectorAll('[data-question-statement]').forEach(el=>renderLessonText(el,s.questions.find(q=>String(q.index)===el.dataset.questionStatement).question));
    box.querySelectorAll('[data-practice-solution]').forEach(el=>renderLessonText(el,s.solutions.find(q=>String(q.index)===el.dataset.practiceSolution).solution));
    restorePracticeDraft(box,s);
    const answerButton = box.querySelector('#submitAnswers'); if (answerButton) answerButton.onclick = async () => { answerButton.disabled=true;try { capturePracticeDrafts();const answers = [...box.querySelectorAll('[data-answer]')].map(x => x.value); await launchOutcomeTask(`/api/exercises/${id}/submit`, jsonOptions('POST', { answers, ...backgroundAssessmentSelection(),...attemptPayload(box) })); } catch(e) { error(e); }finally{answerButton.disabled=false;} };
    const extractButton = box.querySelector('#extractAnswers'); if (extractButton) extractButton.onclick = async () => { try { const file = box.querySelector('#answerFile').files[0]; if (!file) return toast('请选择作答文件'); const body = assessmentUpload(file); const result = await api(`/api/exercises/${id}/extract-answers`, { method: 'POST', body }); box.querySelectorAll('[data-answer]').forEach((el, index) => el.value = result.answers[index] || ''); toast(result.uncertainties?.length ? `已提取答案；${result.uncertainties.length} 处需重点核对` : '已提取答案，请逐题核对后提交'); } catch(e) { error(e); } };
    const codeButton = box.querySelector('#submitCode'); if (codeButton) codeButton.onclick = async () => { codeButton.disabled=true;try { const file = box.querySelector('#codeFile').files[0]; if (!file) return toast('请选择代码文件'); const body = assessmentUpload(file);body.append('background','true');body.append('detailed_feedback','true');if(state.conversation)body.append('conversation_id',state.conversation);await launchOutcomeTask(`/api/coding/${id}/submit`, { method: 'POST', body }); } catch(e) { error(e); }finally{codeButton.disabled=false;} };
    const advanceButton = box.querySelector('#resumeAdvance'); if(advanceButton) advanceButton.onclick=async()=>{advanceButton.disabled=true;try{await launchOutcomeTask(`/api/exercises/${id}/advance`,jsonOptions('POST',backgroundAssessmentSelection()));}catch(e){error(e);}finally{advanceButton.disabled=false;}};
    const feynmanButton = box.querySelector('#submitFeynman'); if (feynmanButton) feynmanButton.onclick = async () => { feynmanButton.disabled=true;try { await launchOutcomeTask(`/api/exercises/${id}/feynman`, jsonOptions('POST', { explanation: box.querySelector('#feynmanText').value, ...backgroundAssessmentSelection() })); } catch(e) { error(e); }finally{feynmanButton.disabled=false;} };
    const regradeButton=box.querySelector('#regradeAnswers');if(regradeButton)regradeButton.onclick=async()=>{regradeButton.disabled=true;try{await launchOutcomeTask(`/api/exercises/${id}/regrade`,jsonOptions('POST',backgroundAssessmentSelection()));}catch(e){error(e);}finally{if(regradeButton.isConnected)regradeButton.disabled=false;}};
  } catch(e) { error(e); }
}
$('newCoding').onclick = async () => {
  if (!state.selected.size) return toast('请先选中学习资料');
  const button = $('newCoding'); const label = button.textContent;
  button.disabled = true; button.textContent = '正在出题、核查与修订…';
  try {
    await launchOutcomeTask('/api/coding/generate', jsonOptions('POST', { project_id: state.project.id, source_ids: [...state.selected], language: $('codingLanguage').value, ...backgroundAssessmentSelection() }));
  } catch(e) { error(e); }
  finally { button.disabled = false; button.textContent = label; }
};

async function refreshProfile(loadControls = true) {
  return renderLearningProfile(loadControls);
}
$('saveMemorySettings').onclick = async () => {
  try {
    await api('/api/settings', jsonOptions('PUT', {background_learning_enabled:$('backgroundLearningEnabled').checked,
      background_learning_interval_minutes:Number($('backgroundLearningInterval').value), background_learning_daily_limit:Number($('backgroundLearningDailyLimit').value)}));
    toast('后台记忆设置已保存'); await refreshProfile();
  } catch(e) { error(e); }
};
$('saveRating').onclick = async () => { try { await api('/api/profile/rating', jsonOptions('POST', { topic: $('ratingTopic').value.trim(), rating: Number($('ratingValue').value), difficulty_rating: Number($('difficultyValue').value) })); toast('自评已记录'); refreshProfile(); } catch(e) { error(e); } };
const codexPrompt = '请使用 studyforge MCP 的 list_projects 列出我的学习项目，再用 list_sources 查看当前项目的资料。需要阅读某份资料时调用 read_source。';
const dshPrompt = '请调用 mcp__studyforge__list_projects 列出 StudyForge 学习项目，再调用 mcp__studyforge__list_sources 查看资料；若工具未出现，请检查 MCP 配置并重启 DSH Desktop。';
async function refreshSettings() {
  const apiNetworkRevision=apiNetworkSettings.revision;
  const noticeSettingsRevision=desktopNoticeSettingsRevision;
  const schedulingRevision=schedulingSettingsRevision;
  const appearanceRevision=studioRevision;
  const [config, health] = await Promise.all([api('/api/settings'), api('/api/health')]);
  state.settings = config; applyAgentSettings(config);
  applyApiNetworkSettings(config,apiNetworkRevision);
  applyDesktopNotificationSettings(config,noticeSettingsRevision);
  applySchedulingSettings(config,schedulingRevision);
  applyStudioPreferences(config,false,appearanceRevision);
  $('modelName').value = config.deepseek_model || 'deepseek-flash';
  $('visionModel').value = config.deepseek_vision_model || 'deepseek-flash';
  $('codexModel').value = config.codex_model || '';
  $('codexModelHelp').textContent = (config.codex_model ? `对话模型：${config.codex_model}` : `对话使用本机默认：${config.codex_local_default || '由 Codex 决定'}`)
    + '；生成讲解继续当前学习对话'
    + ($('provider').value === 'deepseek' ? '。当前选择 DeepSeek；切换学习对话右上角的服务后才会使用 Codex 模型。' : '。');
  $('whisperModel').value = state.asrSelectionDraft?.model || config.whisper_model || 'small';
  $('whisperDevice').value = state.asrSelectionDraft?.device || config.whisper_device || 'auto';
  $('voiceLanguage').value = config.voice_language || 'zh';
  $('defaultReviewMode').value = config.review_mode || 'express';
  $('defaultExplanationStyle').value = config.explanation_style || 'clear';
  $('defaultOutputLanguage').value = config.output_language || 'zh';
  $('defaultOutputFormat').value = config.default_output_format || 'docx';
  $('autoSelectImports').checked = config.auto_select_imports !== false;
  $('keyStatus').textContent = config.deepseek_configured ? 'DeepSeek API 密钥已配置' : '尚未配置 DeepSeek API 密钥';
  $('healthDetails').innerHTML = `<p>DeepSeek 可独立运行，无需安装或打开 Codex。</p><p>可选联动 · Codex CLI：${health.codex_available ? '已找到' : '未找到'} · DSH Desktop 配置：${health.dsh_desktop_available ? '已找到' : '未找到'} · Docker 客户端：${health.docker_available ? '已找到' : '未找到'}</p><p>输入解析器 ${health.input_formats.length} 种扩展名，输出器 ${health.output_formats.length} 种格式。</p><p>数据目录：${escapeHtml(health.data_dir)}</p>`;
  $('mcpCommand').textContent = `Codex 对话示例：\n${codexPrompt}\n\nDSH 对话示例：\n${dshPrompt}`;
  await refreshDesktopControls();
  await refreshUpdateControls();
  await refreshDesktopNotificationControls();
  await loadModelServices();
}
let updateState=null,updateActionBusy=false;
function renderUpdateState(value){
  updateState=value;$('updateControls').hidden=false;
  const cfg=value.settings,busy=updateActionBusy||['checking','downloading','installing'].includes(value.status);
  $('updateVersion').textContent=`当前版本 ${value.current_version}${value.packaged?' · 安装版':' · 源码验收版，改动尚未打包'}`;
  $('updateModeNote').textContent=!value.packaged?'当前入口直接运行源码，只预留更新设置；下载安装在包含更新功能的新安装版中启用。'
    :!value.signature_configured?'正式发布者签名尚未配置，可检查版本；签名接入后才能自动安装。':'更新安装前核验发布者签名和文件校验值。';
  const labels={unconfigured:'尚未配置更新源，正式发布时接入。',development:'更新设置可保存；源码模式不自动安装。',idle:'等待检查更新。',
    checking:'正在检查更新…',current:'当前已是更新源提供的最新版本。',available:`发现新版本 ${value.candidate?.version||''}，可下载。`,
    downloading:`正在下载 ${value.candidate?.version||''}…`,downloaded:`版本 ${value.candidate?.version||''} 已下载，等待你重启安装。`,
    installing:'正在保存任务并准备重启安装…',error:'更新未完成，可核对设置后重试。'};
  $('updateStatus').textContent=(labels[value.status]||'更新状态待确认')+(value.error?' '+value.error:'')
    +(value.last_checked?' 上次检查：'+new Date(value.last_checked).toLocaleString('zh-CN'):'');
  const progress=value.progress;$('updateProgress').hidden=!progress;
  if(progress){const percent=Math.round(progress.percent);$('updateProgress').setAttribute('aria-valuenow',String(percent));$('updateProgress').querySelector('i').style.width=percent+'%';
    $('updateTransfer').textContent=`${percent}% · ${(progress.transferred/1024**2).toFixed(1)} / ${(progress.total/1024**2).toFixed(1)} MB`;
  }else $('updateTransfer').textContent='';
  $('saveUpdateSettings').disabled=busy;$('checkUpdates').disabled=busy||!value.packaged||!cfg.feed_url;
  $('downloadUpdate').hidden=!value.can_download;$('downloadUpdate').disabled=busy;
  $('installUpdate').hidden=!value.can_install;$('installUpdate').disabled=busy;
  $('rollbackUpdate').disabled=busy||!value.can_rollback;$('rollbackUpdate').textContent=value.rollback_version?'回退到 '+value.rollback_version:'暂无可回退版本';
  $('updateNotes').hidden=!value.candidate?.notes;$('updateNotes').querySelector('pre').textContent=value.candidate?.notes||'';
}
async function refreshUpdateControls(){
  if(!window.studyforgeDesktop?.updateStatus)return;
  try{const value=await window.studyforgeDesktop.updateStatus();renderUpdateState(value);
    $('updateFeed').value=value.settings.feed_url;$('updateAutoCheck').checked=value.settings.auto_check;
    $('updateAutoDownload').checked=value.settings.auto_download;$('updateInterval').value=value.settings.interval_hours;
  }catch(_){$('updateControls').hidden=true;}
}
async function runUpdateAction(operation){
  if(updateActionBusy)return;updateActionBusy=true;if(updateState)renderUpdateState(updateState);
  try{const result=await operation();if(result?.settings)renderUpdateState(result);}
  catch(failure){error(failure);}
  finally{updateActionBusy=false;if(updateState)renderUpdateState(updateState);}
}
$('saveUpdateSettings').onclick=()=>runUpdateAction(async()=>{const result=await window.studyforgeDesktop.saveUpdateSettings({
  feed_url:$('updateFeed').value.trim(),auto_check:$('updateAutoCheck').checked,auto_download:$('updateAutoDownload').checked,
  interval_hours:Number($('updateInterval').value)});toast('更新设置已保存');return result;});
$('checkUpdates').onclick=()=>runUpdateAction(()=>window.studyforgeDesktop.checkUpdates());
$('downloadUpdate').onclick=()=>runUpdateAction(()=>window.studyforgeDesktop.downloadUpdate());
$('installUpdate').onclick=()=>runUpdateAction(()=>window.studyforgeDesktop.installUpdate());
$('rollbackUpdate').onclick=()=>runUpdateAction(()=>window.studyforgeDesktop.rollbackUpdate());
$('openUpdateRecovery').onclick=()=>runUpdateAction(()=>window.studyforgeDesktop.openUpdateRecovery());
window.studyforgeDesktop?.onUpdateChanged?.(renderUpdateState);
async function refreshDesktopControls() {
  if(!window.studyforgeDesktop?.desktopStatus)return;
  try {
    const result=await window.studyforgeDesktop.desktopStatus();
    $('desktopControls').hidden=false;
    $('desktopRunStatus').textContent=result.tray_available
      ? '关闭窗口或按 Alt+F4 后隐藏到右下角托盘，任务继续。单击托盘可重新打开；完全退出会保存生成的可恢复状态。'
      : '当前托盘不可用；关闭窗口会完全退出。生成任务将在重开后显示为可继续。';
    $('hideDesktop').disabled=!result.tray_available||result.quitting;
    $('quitDesktop').disabled=result.quitting;
    await window.studyforgeStartup?.refresh();
  } catch(_){$('desktopControls').hidden=true;}
}
async function prepareDesktopExit() {
  clearTimeout(readingTimer);
  await flushConversation();
  await flushHomeworkDrafts();
  if(state.recording?.state==='recording')state.recording.stop();
  flushStudioDraft();
  await Promise.allSettled([modelPreferenceSave,learningModeSave,studioSave,navigationSave,schedulingSettingsSave,agentPermissionSave]);
}
$('hideDesktop').onclick=()=>window.studyforgeDesktop?.hideToTray().catch(error);
$('quitDesktop').onclick=()=>window.studyforgeDesktop?.quit().catch(error);
if(window.studyforgeDesktop?.onDesktopEvent)window.studyforgeDesktop.onDesktopEvent((kind,view)=>{
  if(kind==='hidden'&&state.recording?.state==='recording')state.recording.stop();
  if(kind==='quitting'){
    clearTimeout(readingTimer);$('status').textContent='正在保存任务状态并退出…';
    $('sendMessage').disabled=true;$('generate').disabled=true;
  }
  if(kind==='visible'&&state.project){refreshArtifacts().catch(error);renderReadingStatus();}
  if(kind==='navigate')navigateDesktopNotice(view).catch(error);
});
function applyGenerationDefaults(config) {
  applySchedulingSettings(config);
  applyReviewMode(state.conversationConfig?.review_mode || config.review_mode || 'express', false);
  applyExplanationStyle(state.conversationConfig?.explanation_style || config.explanation_style || 'clear', false);
  applyOutputLanguage(state.conversationConfig?.output_language || config.output_language || 'zh', false);
  $('outputFormat').value = config.default_output_format || 'docx';
  $('generationProviderLabel').textContent = `${serviceName($('provider').value)} · GENERATE`;
  updateGenerationModelInfo();
}
$('saveSettings').onclick = async () => {
  try {
    const config = await api('/api/settings', jsonOptions('PUT', {
      deepseek_api_key: $('apiKey').value || undefined,
      deepseek_model: $('modelName').value.trim(), deepseek_vision_model: $('visionModel').value.trim(),
      codex_model: $('codexModel').value.trim(), whisper_model: $('whisperModel').value,
      whisper_device: $('whisperDevice').value,
      api_connection_mode: $('apiConnectionMode').value,
      voice_language: $('voiceLanguage').value, review_mode: $('defaultReviewMode').value,
      explanation_style: $('defaultExplanationStyle').value, output_language: $('defaultOutputLanguage').value,
      default_output_format: $('defaultOutputFormat').value, auto_select_imports: $('autoSelectImports').checked,
      generation_quality: 'custom', ...agentSettingsPayload()
    }));
    state.settings = config; state.asrSelectionDraft=null; applyGenerationDefaults(config); $('apiKey').value = ''; $('imageApiKey').value = '';
    toast('设置已保存；教学默认值用于新对话，当前对话保留自己的选择'); await refreshSettings(); await refreshStudyModels();
  } catch(e) { error(e); }
};
$('loadCodexModels').onclick = async () => { try { const result = await loadCodexCatalog(true); if ($('provider').value === 'codex') renderStudyModels(); toast(result.warning || `已读取 ${result.models.length} 个 Codex 模型`); } catch(e) { error(e); } };
$('loadDeepSeekModels').onclick = async () => { try { const result = await loadDeepSeekCatalog(true); if ($('provider').value === 'deepseek') renderStudyModels(); toast(result.warning || `服务目录列出 ${result.listed_count} 个型号`); } catch(e) { error(e); } };
$('reloadStudyModels').onclick = () => refreshStudyModels(true);
$('studyModel').onchange = () => { updateEffortOptions(); saveModelPreferences(); updateGenerationModelInfo(); };
$('reasoningEffort').onchange = () => { $('reasoningEffort').dataset.saved = $('reasoningEffort').value; saveModelPreferences(); updateGenerationModelInfo(); };
$('testDeepSeek').onclick = async () => { $('networkStatus').textContent = '正在检测连接…'; try { const result = await api('/api/diagnostics/deepseek', { method: 'POST' }); $('networkStatus').textContent = result.message; } catch(e) { $('networkStatus').textContent = e.message; error(e); } };
$('detectAsrDevice').onclick = async () => {
  state.asrSelectionDraft={model:$('whisperModel').value,device:$('whisperDevice').value};
  const button=$('detectAsrDevice'),status=$('asrDeviceStatus');button.disabled=true;status.textContent='正在核验当前选择；可继续使用其他功能…';
  try { const result=await api('/api/asr/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('whisperModel').value,device:$('whisperDevice').value})});status.textContent=`模型 ${result.selected_model} · 实际可用设备 ${result.actual_device==='cuda'?'GPU':'CPU'}。${result.reason||'设备自检通过。'} 保存设置后用于后续识别。`; }
  catch(e){status.textContent=e.message;error(e);} finally{button.disabled=false;}
};
for(const id of ['whisperModel','whisperDevice'])$(id).addEventListener('change',()=>{state.asrSelectionDraft={model:$('whisperModel').value,device:$('whisperDevice').value};});
$('connectCodex').onclick = async () => { try { const result = await api('/api/integrations/codex', { method: 'POST' }); toast(result.message); } catch(e) { error(e); } };
$('connectDsh').onclick = async () => { try { const result = await api('/api/integrations/dsh', { method: 'POST' }); toast(result.message); } catch(e) { error(e); } };
$('copyCodexPrompt').onclick = async () => { try { await copyText(codexPrompt); toast('Codex 示例指令已复制'); } catch(e) { error(e); } };
$('copyDshPrompt').onclick = async () => { try { await copyText(dshPrompt); toast('DSH 示例指令已复制'); } catch(e) { error(e); } };

$('recordVoice').onclick = async () => {
  try {
    if (state.recording) { state.recording.stop(); return; }
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前窗口无法访问麦克风');
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined); const parts = [];
    recorder.ondataavailable = e => parts.push(e.data);
    recorder.onerror = event => error(new Error(`录音失败：${event.error?.message || '麦克风中断'}`));
    recorder.onstop = async () => { stream.getTracks().forEach(t => t.stop()); state.recording = null; $('recordVoice').disabled = true; $('recordVoice').textContent = '识别中…'; try { const suffix = mime?.includes('ogg') ? '.ogg' : '.webm'; const blob = new Blob(parts, { type: mime || 'audio/webm' }); if (blob.size < 1000) throw new Error('录音太短；请说至少两秒后结束'); const body = new FormData(); body.append('file', blob, `voice${suffix}`); const result = await api('/api/voice/transcribe', { method: 'POST', body }); $('prompt').value = ($('prompt').value + ' ' + result.text).trim(); toast(`识别结果：${result.text.slice(0, 80)}${result.text.length > 80 ? '…' : ''}`); } catch(e) { error(e); } finally { $('recordVoice').disabled = false; $('recordVoice').textContent = '🎙 语音'; } };
    recorder.start(250); state.recording = recorder; $('recordVoice').textContent = '■ 结束录音'; toast('正在录音，请说至少两秒');
  } catch(e) { error(e.name === 'NotAllowedError' ? new Error('麦克风权限被拒绝；请在 Windows 隐私设置中允许桌面应用访问麦克风') : e); }
};

async function initialize() {
  const appearanceRevision=studioRevision;
  const apiNetworkRevision=apiNetworkSettings.revision;
  const [config, health] = await Promise.all([api('/api/settings'), api('/api/health')]);
  state.settings = config; applyAgentSettings(config);
  applyApiNetworkSettings(config,apiNetworkRevision);
  applyStudioPreferences(config,false,appearanceRevision);
  await loadModelServices();
  const preferred = config.chat_provider || 'codex';
  $('provider').value = preferred === 'codex' && !health.codex_available ? 'deepseek' : preferred;
  applyGenerationDefaults(config);
  applyLearningMode(config.learning_mode || 'deep', false);
  await refreshProjects();
  state.ready = true; setConversationLoading(false);
  applyDesktopNotificationSettings(config);
  if(desktopNoticePendingTarget){const target=desktopNoticePendingTarget;desktopNoticePendingTarget=null;navigateDesktopNotice(target).catch(error);}
  refreshStudyModels().catch(error);
  scheduleReading();
  updateGenerationModelInfo();
}
$('provider').onchange = async () => {
  if (state.busy) { $('provider').value = state.conversationConfig?.provider || 'deepseek'; return toast('请等当前回复完成后切换 AI 服务'); }
  const provider = $('provider').value;
  state.conversationConfig = {...state.conversationConfig, provider, model: null,
    model_choice: servicePreference(provider) || '', reasoning_effort: ['codex','deepseek'].includes(provider) ? state.settings?.[`chat_effort_${provider}`] || null : null};
  $('generationProviderLabel').textContent = `${serviceName(provider)} · GENERATE`;
  updateGenerationModelInfo();
  refreshStudyModels().catch(error);
  scheduleReading();
  saveConversation({provider, model: currentModel(), model_choice: $('studyModel').value, reasoning_effort: currentEffort()});
  try { await api('/api/settings', jsonOptions('PUT', { chat_provider: $('provider').value })); }
  catch (e) { error(e); }
};
function arrangeWorkspace() {
  const header = document.querySelector('.conversation-panel > .section-head');
  const modelToolbar = document.querySelector('.model-toolbar');
  const providerLabel = document.createElement('label');
  providerLabel.className = 'provider-choice';
  providerLabel.textContent = 'AI 服务';
  providerLabel.append($('provider'));
  modelToolbar.prepend(providerLabel);
  header.append(modelToolbar);

  const status = $('modelStatus');
  const updateStatus = () => { status.classList.toggle('warning', /暂不可用|失败|错误|无法/.test(status.textContent));status.title=status.textContent; };
  new MutationObserver(updateStatus).observe(status, { childList: true, subtree: true, characterData: true });
  updateStatus();

  const generationBar = document.querySelector('.generation-bar');
  const exerciseToggle = document.querySelector('.exercise-toggle');
  exerciseToggle.querySelector('span').firstChild.textContent = '同步出题';
  exerciseToggle.title = '同时生成举一反三习题，习题默认单独输出 DOCX';
  exerciseToggle.hidden=true;
  const contentChoice=document.createElement('label');contentChoice.className='generation-content-choice';
  contentChoice.innerHTML='<span>生成内容</span><select id="generationContent"><option value="explanation">只生成讲解</option><option value="both">讲解＋习题</option><option value="exercises">只生成习题</option></select>';
  generationBar.insertBefore(contentChoice,$('generate'));
  $('generationContent').onchange=()=>{$('withExercises').checked=$('generationContent').value!=='explanation';$('withExercises').onchange();$('outputFormat').disabled=$('generationContent').value==='exercises';$('generate').textContent=$('generationContent').value==='exercises'?'✦ 生成习题':'✦ 生成讲解';};
  const advancedGeneration = document.querySelector('.advanced-generation');
  advancedGeneration.querySelector('summary').textContent = '更多设置';
  generationBar.append(advancedGeneration);
  document.querySelector('.advanced-grid').prepend($('reviewMode').closest('.control'));
  const strategy = document.createElement('div');
  strategy.className = 'control';
  strategy.innerHTML = '<label>导师与讲解共用同一 AI</label><small id="generationModelInfo" class="small-note"></small>';
  document.querySelector('.advanced-grid').prepend(strategy);
  for (const [formId, inputId] of [['composerUrlForm', 'composerUrl'], ['libraryUrlForm', 'videoUrl']]) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'browser-import-button';
    button.textContent = '浏览器导入'; button.title = '知乎等需要登录或验证的网页';
    button.onclick = async () => { try { const url = $(inputId).value.trim(); if (!url) return toast('请先填入网址'); await importInBrowser(url); } catch (err) { error(err); } };
    $(formId).append(button);
  }

  const importRow = document.createElement('div');
  importRow.className = 'source-import-row';
  const contextFooter = document.querySelector('.context-footer');
  importRow.append(contextFooter.querySelector('label[for="quickImportCategory"]'), contextFooter.querySelector('.quick-actions'));
  document.querySelector('.context-toolbar').append(importRow);
}
function updateGenerationModelInfo() {
  document.querySelector('.model-toolbar').dataset.provider=$('provider').value;
  if (!$('generationModelInfo')) return;
  $('generationModelInfo').textContent = `${currentModel() || '当前默认模型'}${currentEffort() ? ' · ' + currentEffort() : ''} · ${learningModeDescriptions[currentLearningMode()][0]} · 按当前对话选中的资料和要求生成`;
  $('generate').title = $('generationModelInfo').textContent;
}
function agentSettingsPayload() {
  const roots = id => $(id).value.split('\n').map(value => value.trim()).filter(Boolean);
  return { agent_tools_enabled: $('agentToolsEnabled').checked, agent_network_enabled: $('agentNetworkEnabled').checked,
    agent_web_video_enabled: $('allowWebVideo').checked, agent_file_write_enabled: $('agentWriteEnabled').checked,
    agent_image_generation_enabled: $('agentImageEnabled').checked,
    agent_read_roots: roots('agentReadRoots'), agent_write_roots: roots('agentWriteRoots'),
    agent_max_tool_calls: Number($('agentToolBudget').value), image_api_key: $('imageApiKey').value || undefined,
    image_api_base: $('imageApiBase').value.trim(), image_model: $('imageModel').value.trim() };
}
function applyAgentSettings(config) {
  applyAgentPermissionPreferences(config);
  for (const [id, key, fallback] of [['agentToolsEnabled', 'agent_tools_enabled', true], ['agentNetworkEnabled', 'agent_network_enabled', true],
    ['allowWebVideo', 'agent_web_video_enabled', false], ['agentWriteEnabled', 'agent_file_write_enabled', true], ['agentImageEnabled', 'agent_image_generation_enabled', true]])
    $(id).checked = config[key] ?? fallback;
  $('agentReadRoots').value = (config.agent_read_roots || []).join('\n');
  $('agentWriteRoots').value = (config.agent_write_roots || []).join('\n');
  $('agentToolBudget').value = config.agent_max_tool_calls || 12;
  $('imageApiBase').value = config.image_api_base || 'https://api.openai.com/v1';
  $('imageModel').value = config.image_model || 'gpt-image-2.5-flare';
  $('imageKeyStatus').textContent = config.image_api_configured ? '绘图密钥已配置' : '绘图需要单独的 API 密钥';
}
$('allowWebVideo').onchange = async () => {
  const checkbox = $('allowWebVideo'); const previous = !checkbox.checked;
  checkbox.disabled = true;
  try { state.settings = await api('/api/settings', jsonOptions('PUT', { agent_web_video_enabled: checkbox.checked })); toast(checkbox.checked ? '已允许导师读取网页视频' : '已关闭网页视频读取'); }
  catch (e) { checkbox.checked = previous; error(e); }
  finally { checkbox.disabled = false; }
};
for (const [button, input] of [['chooseReadRoot', 'agentReadRoots'], ['chooseWriteRoot', 'agentWriteRoots']]) {
  $(button).onclick = async () => {
    try {
      if (!window.studyforgeDesktop?.chooseDirectory) return toast('请在上方填写目录绝对路径，每行一个');
      const selected = await window.studyforgeDesktop.chooseDirectory();
      if (selected) $(input).value = [...new Set([...$(input).value.split('\n').filter(Boolean), selected])].join('\n');
    } catch (e) { error(e); }
  };
}
function showToolActivity(content, event) {
  let status = content.parentElement.querySelector('.tool-activity:not(.reply-status)');
  if (!status) { status = document.createElement('div'); status.className = 'tool-activity'; status.setAttribute('role', 'status'); content.before(status); }
  const names = {sf_list_files:'查看文件',sf_read_file:'读取原文件',sf_read_source:'读取资料',sf_check_math:'数学核验',sf_write_text:'写入文件',sf_edit_text:'修改文件',sf_search_web:'检索网络',sf_read_url:'读取网页',sf_inspect_media:'读取画面',sf_generate_image:'生成图片',sf_create_document:'导出文档',session:'更新对话工具'};
  status.textContent = `${names[event.tool] || event.tool} · ${event.status === 'waiting_approval' ? '等待你审批' : event.status === 'running' ? '进行中' : event.status === 'failed' ? '未完成' : '完成'}${event.result?.error ? '：' + event.result.error : ''}`;
  if(event.status==='waiting_approval')refreshAgentApprovals();
}

function showReplyStatus(content, text) {
  let status = content.parentElement.querySelector('.reply-status');
  if (!status && text) {
    status = document.createElement('div');
    status.className = 'reply-status tool-activity';
    status.setAttribute('role', 'status');
    content.parentElement.append(status);
  }
  if (status) { status.textContent = text; status.hidden = !text; }
}
arrangeWorkspace();
initializeStudio();
initializeModelServices();
initializeParallel();
initializeHomework();
initializeConversations();
initializeNavigation();
initializeConversationDisplay();
initializeReadingNotes();
initializeAgentPermissions();
initializeConversationLayout();
initializeDesktopNotifications();
initialize().catch(error);
let workspacePoll = null;
function refreshWorkspacePoll() {
  if (workspacePoll) return workspacePoll;
  workspacePoll = (async () => {
    const updates = [refreshNavigation()];
    if (state.project && !conversationUI.restoring)
      updates.push(refreshSources(), refreshConversations(), refreshConversationMessages());
    const results = await Promise.allSettled(updates);
    for (const result of results) if (result.status === 'rejected') error(result.reason);
  })().finally(() => { workspacePoll = null; });
  return workspacePoll;
}
setInterval(refreshWorkspacePoll, 5000);
