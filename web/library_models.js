/* One saved library selection, no conversation history or model credentials. */
(() => {
  'use strict';
  const labels={none:'关闭推理',minimal:'最少',low:'低',medium:'中',high:'高',xhigh:'极高',max:'最高',ultra:'超高'};
  const fields=['mode','provider','model','effort','vision_mode','vision_model'];
  function create({host,api,workbench,notify,catalog=()=>null}){
    const panel=document.createElement('details');panel.className='book-model-settings';
    panel.innerHTML=`<summary><span>阅读模型</span><strong data-model-summary>正在读取书库设置…</strong></summary>
      <div class="book-model-body"><p class="book-notice">书库 AI 只读你选中的章节和填写的阅读要求，不会看到项目聊天。回工作台后，导师可以参考这些阅读结果。</p>
      <div class="book-model-fields">
        <label>使用哪个模型<select data-field="mode"><option value="follow">跟随学习工作台</option><option value="independent">为书库单独选择</option></select></label>
        <label data-independent>AI 服务<select data-field="provider"></select></label>
        <label data-independent>阅读模型<input data-field="model" list="bookReadingModelChoices" maxlength="120" placeholder="留空使用此服务默认模型"><datalist id="bookReadingModelChoices"></datalist></label>
        <label data-independent>推理强度<select data-field="effort"><option value="">自动 · 服务默认</option></select></label>
        <label data-vision>扫描页看图<select data-field="vision_mode"><option value="configured">使用设置中的画面分析模型</option><option value="same">与阅读模型一致</option><option value="custom">单独选择看图模型</option></select></label>
        <label data-vision-custom>读取扫描页的模型<input data-field="vision_model" list="bookReadingModelChoices" maxlength="120" placeholder="填写支持图片的模型名称（服务商提供的英文 ID）"></label>
      </div><p data-model-preview class="book-model-preview" role="status"></p>
      <p class="small-note">这里选择书库阅读使用的 AI，只影响新开始的任务。已暂停的任务会继续使用原模型；读取扫描页的模型需要支持图片。列表没有时，可以填写服务商提供的模型名称。</p>
      <div class="book-actions"><button type="button" data-save-model class="primary">保存书库选择</button><button type="button" data-refresh-models>刷新模型列表</button><button type="button" data-reload-models>重新载入设置</button></div>
      <p data-model-status class="small-note" role="status"></p></div>`;
    host.append(panel);
    const el=key=>panel.querySelector(`[data-field="${key}"]`),summary=panel.querySelector('[data-model-summary]'),preview=panel.querySelector('[data-model-preview]'),status=panel.querySelector('[data-model-status]');
    const saveButton=panel.querySelector('[data-save-model]'),refreshButton=panel.querySelector('[data-refresh-models]');
    for(const control of panel.querySelectorAll('input,select'))control.disabled=true;
    saveButton.disabled=true;refreshButton.disabled=true;
    let saved=null,services=[],configuredVision=null,loading=null,saving=null,dirty=false,catalogEpoch=0,lastPreview='';
    const catalogs=new Map();
    const value=()=>Object.fromEntries(fields.map(key=>[key,['model','vision_model','effort'].includes(key)?el(key).value.trim()||null:el(key).value]));
    const service=id=>services.find(r=>r.id===id);
    function currentSelection(w=workbench()){
      const draft=value(),reading=draft.mode==='follow'?{...w}:{provider:draft.provider,model:draft.model||service(draft.provider)?.default_model||null,effort:draft.effort};
      reading.model=reading.model||service(reading.provider)?.default_model||null;
      if(reading.provider==='deepseek')reading.vision_model=draft.vision_mode==='custom'?draft.vision_model:draft.vision_mode==='same'?reading.model:configuredVision;
      else reading.vision_model=reading.model;
      return reading;
    }
    function updatePreview(){
      if(!saved)return;
      const draft=value(),reading=currentSelection(),row=service(reading.provider),available=reading.provider&&row?.enabled!==false;
      for(const e of panel.querySelectorAll('[data-independent]'))e.hidden=draft.mode!=='independent';
      const separate=reading.provider==='deepseek';
      panel.querySelector('[data-vision]').hidden=!separate;
      panel.querySelector('[data-vision-custom]').hidden=!separate||draft.vision_mode!=='custom';
      const name=row?.name||reading.provider||'尚未选择服务',m=reading.model||'服务默认',strength=labels[reading.effort]||'自动';
      const text=`${draft.mode==='follow'?'跟随工作台':'单独选择'} · ${name} · ${m} · ${strength}`;
      const description=`新任务将使用 ${name} / ${m}，推理 ${strength}；扫描页看图 ${reading.vision_model||'使用阅读模型'}。`+(!available?' 所选服务已停用或移除，请重新选择。':row?.supports_vision===false?' 此服务未启用图片读取；扫描公式的原图核对会标为待确认，建议另选支持图片的服务。':'');
      const key=JSON.stringify([text,description,dirty]);if(key===lastPreview)return;lastPreview=key;
      summary.textContent=text+(dirty?' · 未保存':'');preview.textContent=description;
      saveButton.disabled=!dirty||Boolean(saving);
    }
    function renderModels(wanted=el('effort').value){
      if(!saved)return;
      const id=value().mode==='follow'?workbench().provider:el('provider').value;
      const known=catalogs.get(id)||catalog(id),rows=[...(known?.models||[]),...(service(id)?.models||[]).map(model=>({id:model,name:model}))];
      const list=panel.querySelector('datalist');list.replaceChildren();
      for(const row of new Map(rows.map(r=>[r.id,r])).values()){
        const option=document.createElement('option');option.value=row.id;option.label=row.name||row.id;list.append(option);
      }
      const selected=el('model').value||service(id)?.default_model;
      const entry=known?.models?.find(r=>r.id===selected)||(!selected?known?.models?.find(r=>r.is_default):null);
      const strengths=id==='deepseek'?['none','low','high','max']:id==='codex'?(entry?.efforts?.length?entry.efforts:['low','medium','high','xhigh','max','ultra']):[];
      el('effort').replaceChildren(new Option('自动 · 服务默认',''));
      for(const level of strengths)el('effort').append(new Option(labels[level]||level,level));
      if(wanted&&!strengths.includes(wanted)){
        const option=new Option((labels[wanted]||wanted)+' · 请核对是否支持',wanted);el('effort').append(option);
      }
      el('effort').value=wanted;el('effort').disabled=!['codex','deepseek'].includes(id);
    }
    function apply(result){
      saved=result.selection;services=result.services||services;configuredVision=result.deepseek_vision_model||configuredVision;
      const options=el('provider');options.replaceChildren();
      for(const row of services){const option=new Option(row.name+(row.enabled?'':' · 已停用'),row.id);option.disabled=!row.enabled;options.append(option);}
      if(!services.some(r=>r.id===saved.provider))options.append(new Option('已移除的服务 · 请切换',saved.provider));
      for(const key of fields)if(key!=='effort')el(key).value=saved[key]||'';
      for(const control of panel.querySelectorAll('input,select'))control.disabled=Boolean(saving);
      refreshButton.disabled=Boolean(saving);
      dirty=false;lastPreview='';renderModels(saved.effort||'');updatePreview();status.textContent='已保存。只影响以后新建的书库阅读任务，不会改变工作台模型。';
    }
    async function load(force=false){
      if(loading)return loading;
      if((dirty||saving)&&!force)return saved;
      loading=(async()=>{const response=await api('/api/library/models');if(!dirty||force)apply(response);return saved;})().finally(()=>{loading=null;});
      try{return await loading;}catch(e){status.textContent='书库模型设置未载入：'+e.message;summary.textContent='设置未载入 · 点击重新载入';throw e;}
    }
    async function save(){
      if(saving)return saving;
      if(!saved)await load();if(!dirty)return saved;
      const draft=value();
      if(draft.mode==='independent'&&!['codex','deepseek'].includes(draft.provider))draft.effort=null;
      if(draft.mode==='independent'&&draft.provider!=='deepseek'){draft.vision_mode='configured';draft.vision_model=null;}
      if(draft.vision_mode==='custom'&&!draft.vision_model)throw new Error('请填写读取扫描页的模型。');
      const controls=[...panel.querySelectorAll('input,select,button')];for(const control of controls)control.disabled=true;
      status.textContent='正在保存书库选择…';
      saving=(async()=>{
        try{const result=await api('/api/library/models',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...draft,revision:saved.revision})});apply(result);return saved;}
        catch(e){status.textContent='尚未保存：'+e.message;throw e;}
        finally{saving=null;for(const control of controls)control.disabled=false;renderModels();lastPreview='';updatePreview();}
      })();return saving;
    }
    for(const key of fields)el(key).addEventListener('input',()=>{
      dirty=true;if(key==='provider'){el('model').value='';el('effort').value='';el('vision_mode').value='configured';el('vision_model').value='';}
      if(['provider','mode','model'].includes(key))renderModels();lastPreview='';updatePreview();status.textContent='选择已修改；点保存，或启动阅读时自动保存。';
    });
    saveButton.onclick=()=>save().catch(notify);
    panel.querySelector('[data-reload-models]').onclick=()=>load(true).catch(notify);
    refreshButton.onclick=async()=>{
      const id=value().mode==='follow'?workbench().provider:el('provider').value,epoch=++catalogEpoch;
      const url=id==='codex'?'/api/codex/models?refresh=true':id==='deepseek'?'/api/deepseek/models?refresh=true':'/api/providers/'+encodeURIComponent(id)+'/models';
      refreshButton.disabled=true;status.textContent='正在读取此服务的模型目录…';
      try{const result=await api(url);if(epoch!==catalogEpoch)return;catalogs.set(id,result);renderModels();updatePreview();if((value().mode==='follow'?workbench().provider:el('provider').value)!==id)return;status.textContent=result.warning||`已读取 ${result.models?.length||0} 个模型；也可填写模型名称（服务商提供的英文 ID）。`;}
      catch(e){status.textContent='模型目录未读取：'+e.message+'；原选择保留，可手动填写调用名。';}
      finally{if(epoch===catalogEpoch)refreshButton.disabled=false;}
    };
    for(const id of ['provider','studyModel','reasoningEffort','model','effort'])document.getElementById(id)?.addEventListener('change',()=>{renderModels();updatePreview();});
    return {load,refreshPreview:updatePreview,async selection(){
      const w={...workbench()};if(!saved)await load();
      if(dirty)await save();else if(saving)await saving;
      const reading=currentSelection(w);
      if(!reading.provider||service(reading.provider)?.enabled===false||!service(reading.provider))throw new Error('请先选择可用的书库阅读服务。');
      return reading;
    }};
  }
  window.studyforgeLibraryModels={create};
})();
