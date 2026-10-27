/* Configured services participate in the same workspace model selection. */
function serviceRow(id) { return (state.modelServices || []).find(row => row.id === id); }
function serviceName(id) { return ({codex:'Codex',deepseek:'DeepSeek'})[id] || serviceRow(id)?.name || '已移除的服务'; }
function serviceModel(id) {
  return serviceRow(id)?.default_model || state.settings?.[`${id}_model`]
    || (id === 'codex' ? state.settings?.codex_local_default || state.codexCatalog?.models?.find(row=>row.is_default)?.id : id === 'deepseek' ? 'deepseek-flash' : null);
}
function serviceCatalog(id) {
  return id === 'codex' ? state.codexCatalog : id === 'deepseek' ? state.deepseekCatalog : state.serviceCatalogs?.[id];
}
function servicePreference(id) {
  return id.startsWith('svc_') ? state.settings?.provider_model_preferences?.[id] : state.settings?.[`chat_model_${id}`];
}
function renderProviderChoices(wanted = $('provider').value) {
  const rows = [{id:'codex',name:'Codex',enabled:true},{id:'deepseek',name:'DeepSeek',enabled:true},...(state.modelServices || [])];
  if (wanted && !rows.some(row=>row.id===wanted)) rows.push({id:wanted,name:'已移除的服务 · 请切换',enabled:false});
  $('provider').innerHTML = rows.map(row=>`<option value="${escapeHtml(row.id)}" ${row.enabled?'':'disabled'}>${escapeHtml(row.name)}${row.enabled?'':' · 已停用'}</option>`).join('');
  $('provider').value = wanted || 'deepseek';
}
async function loadModelServices() {
  const result = await api('/api/providers'); state.modelServices = result.services;
  renderProviderChoices(); renderServiceList(); return result.services;
}
async function loadServiceCatalog(id) {
  const result = await api(`/api/providers/${encodeURIComponent(id)}/models`);
  state.serviceCatalogs ||= {}; state.serviceCatalogs[id] = result; return result;
}
function openServiceManager(id=null) {
  showView('settings'); showSettingsSection('models');
  $('modelServicesCard').scrollIntoView({block:'start',behavior:'smooth'});
  editService(id);
}
let editingService=null, serviceFormBusy=false;
function serviceProtocolDefaults(protocol) {
  if (protocol === 'gemini') return {name:'Gemini API',base_url:'https://generativelanguage.googleapis.com/v1beta',default_model:'gemini-flash-latest',models:['gemini-flash-latest'],supports_vision:true,requires_key:true};
  if (protocol === 'gemini_cli') return {name:'Gemini · Google 账号',base_url:'',default_model:'auto',models:['auto','pro','flash'],supports_vision:false,requires_key:false};
  return {name:'',base_url:'',default_model:'',models:[],supports_vision:false,requires_key:true};
}
function editService(id) {
  const row = id ? serviceRow(id) : {protocol:'openai',...serviceProtocolDefaults('openai'),enabled:true,supports_tools:true,supports_json:true};
  if (!row) return;
  editingService = id;
  $('serviceEditor').hidden=false;
  $('serviceEditorTitle').textContent=id?`编辑 ${row.name}`:'添加 AI 服务';
  $('serviceName').value=row.name; $('serviceProtocol').value=row.protocol; $('serviceProtocol').disabled=Boolean(id);
  $('serviceBase').value=row.base_url; $('serviceDefaultModel').value=row.default_model;
  $('serviceModels').value=(row.models||[]).join('\n'); $('serviceKey').value=''; $('serviceClearKey').checked=false;
  for (const [element,key] of [['serviceEnabled','enabled'],['serviceTools','supports_tools'],['serviceVision','supports_vision'],['serviceJson','supports_json'],['serviceRequiresKey','requires_key']]) $(element).checked=row[key];
  updateServiceProtocolUI();
  $('serviceFeedback').textContent=id ? (row.protocol==='gemini_cli'?row.auth_status:row.configured?'密钥已保存；留空会保留已有密钥':'尚未配置密钥') : '';
  $('useService').hidden=!id;
}
function updateServiceProtocolUI() {
  const protocol=$('serviceProtocol').value, account=protocol==='gemini_cli';
  $('serviceApiFields').hidden=account; $('geminiAccountActions').hidden=!account;
  $('serviceRequiresKey').disabled=protocol!=='openai'; $('serviceVision').disabled=account;
  $('serviceJson').disabled=account;
  if(account){$('serviceRequiresKey').checked=false;$('serviceVision').checked=false;$('serviceJson').checked=true;}
  $('serviceHint').textContent=account
    ? '通过官方 Gemini CLI 登录 Google 账号；授权缓存在本机专用目录。账号入口支持流式正文和软件工具审批；图片分析请选择 Gemini API。'
    : protocol==='gemini'?'Gemini 原生接口支持流式回复、图片分析和允许 AI 使用软件工具。请从 Google AI Studio 获取 API 密钥；网页登录状态不能直接替代密钥。'
    :'适用于服务商说明中写有“兼容 OpenAI”的服务，也支持本机模型。请从服务商处复制接口地址、密钥和模型名称。';
  $('serviceBase').required=!account; $('serviceKeyHelp').textContent='密钥存入本机凭据管理器，不显示在模型列表或导出配置中。';
  $('geminiKeyLink').hidden=protocol!=='gemini';
  $('serviceLogin').disabled=serviceFormBusy||!editingService;
  $('serviceLogout').disabled=serviceFormBusy||!editingService;
  $('serviceInstall').disabled=serviceFormBusy;
}
function renderServiceList() {
  const host=$('serviceList'); if(!host)return; host.replaceChildren();
  for(const row of state.modelServices||[]){
    const card=document.createElement('article');card.className='service-item';card.dataset.serviceId=row.id;
    const status=!row.enabled?'已停用':row.configured?'已配置':row.protocol==='gemini_cli'?'待登录':'待配置';
    card.innerHTML=`<div class="service-item-main"><strong>${escapeHtml(row.name)}</strong><span class="service-badge ${row.configured?'ready':''}">${status}</span><p>${escapeHtml(row.default_model)} · ${escapeHtml({openai:'兼容接口',gemini:'Gemini 原生接口',gemini_cli:'Google 账号'}[row.protocol])}</p></div><div class="service-item-actions"></div>`;
    const actions=card.querySelector('.service-item-actions');
    for(const [label,handler] of [['使用',()=>useService(row.id)],['编辑',()=>editService(row.id)],['检测',()=>testService(row.id)],['移除',()=>removeService(row.id)]]){
      const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=()=>Promise.resolve(handler()).catch(error);
      if(label==='使用'&&!row.enabled)button.disabled=true;
      actions.append(button);
    } host.append(card);
  }
  if(!host.children.length)host.innerHTML='<p class="small-note">添加一个服务，工作台就会出现对应的服务与模型选项。</p>';
}
async function useService(id) {
  if(state.busy)return toast('请等当前回复完成后切换服务；其他独立任务可继续运行');
  if(!serviceRow(id)?.enabled)throw Error('请先启用此服务');
  $('provider').value=id; await $('provider').onchange();
  showView('study'); $('prompt').focus();
}
async function testService(id) {
  if(serviceFormBusy)return; serviceFormBusy=true;
  updateServiceProtocolUI();
  $('serviceFeedback').textContent='正在检测连接，会使用少量模型额度…';
  try{
    const result=await api(`/api/providers/${id}/test`,jsonOptions('POST',{model:serviceRow(id)?.default_model}));
    $('serviceFeedback').textContent=`连接成功 · ${result.model}：${result.message}`;toast('服务连接成功');await loadModelServices();
  }catch(e){$('serviceFeedback').textContent=e.message;throw e;}
  finally{serviceFormBusy=false;updateServiceProtocolUI();}
}
async function removeService(id) {
  if(!confirm(`移除“${serviceName(id)}”服务及其密钥？已保存的对话、资料和成果仍保留。`))return;
  await api(`/api/providers/${id}`,{method:'DELETE'});
  delete state.serviceCatalogs?.[id];
  if($('provider').value===id){$('provider').value='deepseek';await $('provider').onchange();}
  await loadModelServices();$('serviceEditor').hidden=true;toast('服务已移除；历史对话可保留并切换其他服务');
}
function initializeModelServices() {
  const card=document.createElement('div');card.id='modelServicesCard';card.className='settings-card model-services-card';
  card.innerHTML=`<div class="settings-card-head"><span>自由选择你的导师</span><h3>第三方 AI 服务</h3><p>添加服务后，在学习工作台的“AI 服务”和“模型”中选择。导师、通读、讲解、习题和批改共用你的选择。</p></div>
    <div class="service-presets"><button id="addCompatibleService" type="button">＋ 兼容服务</button><button id="addGeminiService" type="button">＋ Gemini API</button><button id="addGeminiAccount" type="button">＋ Gemini 账号</button><button id="reloadServices" type="button">刷新状态</button></div>
    <div id="serviceList" class="service-list"></div>
    <form id="serviceEditor" class="service-editor" hidden><h4 id="serviceEditorTitle">添加 AI 服务</h4>
      <div class="service-field-grid"><label>服务名称<input id="serviceName" maxlength="60" required placeholder="例如：我的 Gemini"></label>
      <label>接入方式<select id="serviceProtocol"><option value="openai">OpenAI 兼容接口</option><option value="gemini">Gemini 原生 API</option><option value="gemini_cli">Gemini · Google 账号</option></select></label></div>
      <p id="serviceHint" class="small-note"></p><div id="serviceApiFields"><label>接口地址（从服务商处复制）<input id="serviceBase" type="url" placeholder="https://服务域名/v1"></label>
      <label>API 密钥<input id="serviceKey" type="password" autocomplete="new-password" placeholder="已保存则留空" maxlength="4096"></label>
      <p id="serviceKeyHelp" class="small-note"></p><label class="service-check"><input id="serviceClearKey" type="checkbox">清除已保存的密钥</label>
      <p id="geminiKeyLink" class="small-note"><a href="https://aistudio.google.com/api-keys" target="_blank" rel="noopener noreferrer">打开 Google AI Studio 获取 Gemini API 密钥</a></p></div>
      <div class="service-field-grid"><label>默认模型名称（服务商提供的英文 ID）<input id="serviceDefaultModel" maxlength="120" required placeholder="填写服务实际支持的模型名"></label>
      <label>其他可选模型（每行一个）<textarea id="serviceModels" rows="3" placeholder="可手动添加，也可保存后刷新服务目录"></textarea></label></div>
      <div class="service-capabilities"><label class="service-check"><input id="serviceEnabled" type="checkbox" checked>启用服务</label><label class="service-check"><input id="serviceRequiresKey" type="checkbox" checked>需要 API 密钥</label>
      <label class="service-check"><input id="serviceTools" type="checkbox" checked>允许 AI 使用软件工具</label><label class="service-check"><input id="serviceVision" type="checkbox">图片读取</label><label class="service-check"><input id="serviceJson" type="checkbox" checked>支持按指定格式返回结果（JSON）</label></div>
      <p class="small-note">能力选项须与模型实际支持一致。不支持 支持按指定格式返回结果（JSON）时，仍会通过任务提示和格式校验生成文档。只有软件已适配的服务会显示“推理强度”；其他服务使用模型自己的默认设置。</p>
      <div id="geminiAccountActions" hidden><button id="serviceInstall" type="button">安装官方 Gemini CLI</button><button id="serviceLogin" type="button">登录 Google 账号</button><button id="serviceLogout" type="button">退出／重新登录</button><p class="small-note">先保存服务，再登录。登录会打开官方终端及浏览器，完成后关闭终端并检测连接。需安装 Node.js 20+；安装仅写入软件资料目录。Gemini CLI 账号额度与 API 额度分别管理。</p></div>
      <div class="service-editor-actions"><button id="saveService" class="primary" type="submit">保存服务</button><button id="useService" type="button" hidden>在工作台使用</button><button id="cancelServiceEditor" type="button">收起</button></div></form>
    <p id="serviceFeedback" class="small-note" role="status" aria-live="polite"></p>`;
  $('settings-models').prepend(card);
  const add=document.createElement('button');add.id='manageModelServices';add.type='button';add.className='manage-model-services';add.textContent='＋';add.title='添加或管理 AI 服务';add.setAttribute('aria-label','添加或管理 AI 服务');add.onclick=()=>openServiceManager(serviceRow($('provider').value)?.id||null);
  document.querySelector('.provider-choice').append(add);
  const preset=protocol=>{editService(null);$('serviceProtocol').value=protocol;$('serviceProtocol').dispatchEvent(new Event('change'));};
  $('addCompatibleService').onclick=()=>preset('openai');$('addGeminiService').onclick=()=>preset('gemini');$('addGeminiAccount').onclick=()=>preset('gemini_cli');
  $('reloadServices').onclick=()=>loadModelServices().catch(error);
  $('serviceProtocol').onchange=()=>{const defaults=serviceProtocolDefaults($('serviceProtocol').value);$('serviceName').value=defaults.name;$('serviceBase').value=defaults.base_url;$('serviceDefaultModel').value=defaults.default_model;$('serviceModels').value=defaults.models.join('\n');$('serviceVision').checked=defaults.supports_vision;$('serviceRequiresKey').checked=defaults.requires_key;updateServiceProtocolUI();};
  $('cancelServiceEditor').onclick=()=>{$('serviceEditor').hidden=true;};$('useService').onclick=()=>useService(editingService).catch(error);
  $('serviceEditor').onsubmit=async event=>{
    event.preventDefault();if(serviceFormBusy)return;serviceFormBusy=true;$('saveService').disabled=true;
    try{
      const payload={name:$('serviceName').value.trim(),protocol:$('serviceProtocol').value,base_url:$('serviceBase').value.trim(),default_model:$('serviceDefaultModel').value.trim(),models:$('serviceModels').value.split('\n').map(v=>v.trim()).filter(Boolean),
        api_key:$('serviceKey').value,clear_key:$('serviceClearKey').checked,enabled:$('serviceEnabled').checked,requires_key:$('serviceRequiresKey').checked,supports_tools:$('serviceTools').checked,supports_vision:$('serviceVision').checked,supports_json:$('serviceJson').checked};
      const saved=await api('/api/providers'+(editingService?'/'+editingService:''),jsonOptions(editingService?'PUT':'POST',payload));
      delete state.serviceCatalogs?.[saved.id];await loadModelServices();editService(saved.id);$('serviceKey').value='';
      $('serviceFeedback').textContent='服务已保存，可在工作台选择。刷新模型目录只读取目录；检测连接会使用少量额度。';
      if($('provider').value===saved.id)await refreshStudyModels();toast('AI 服务已保存');
    }catch(e){$('serviceFeedback').textContent=e.message;error(e);}finally{serviceFormBusy=false;$('saveService').disabled=false;updateServiceProtocolUI();}
  };
  $('serviceInstall').onclick=async()=>{if(serviceFormBusy)return;serviceFormBusy=true;updateServiceProtocolUI();$('serviceFeedback').textContent='正在安装官方 Gemini CLI，请保持软件运行…';try{const result=await api('/api/providers/gemini-cli/install',{method:'POST'});$('serviceFeedback').textContent=result.message;await loadModelServices();}catch(e){$('serviceFeedback').textContent=e.message;error(e);}finally{serviceFormBusy=false;updateServiceProtocolUI();}};
  $('serviceLogin').onclick=async()=>{try{const result=await api(`/api/providers/${editingService}/login`,{method:'POST'});$('serviceFeedback').textContent=result.message;toast(result.message,{duration:12000});}catch(e){error(e);}};
  $('serviceLogout').onclick=async()=>{if(!confirm('清除此服务的本地 Gemini 授权并重新登录？学习对话与成果仍保留。'))return;try{const result=await api(`/api/providers/${editingService}/logout`,{method:'POST'});await loadModelServices();$('serviceFeedback').textContent=result.message;toast(result.message);}catch(e){error(e);}};
}
