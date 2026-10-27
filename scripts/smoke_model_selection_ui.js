const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const casePath=process.env.STUDYFORGE_MODELS_UI_CASE;
const input=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(path.dirname(casePath),'electron-profile'));
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:1440,height:1100,webPreferences:{nodeIntegration:false,
    contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  const errors=[];
  win.webContents.on('console-message',details=>{if(details.level==='error'&&!details.message.includes('404'))errors.push(details.message);});
  try {
    await win.loadURL(input.urls[0]);
    const first=await win.webContents.executeJavaScript(`(async()=>{
      const input=${JSON.stringify(input)};
      const wait=async fn=>{for(let i=0;i<150;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw new Error('wait timed out: '+JSON.stringify({project:state.project?.id,ready:state.ready,conversation:state.conversation,restoring:conversationUI.restoring,deepseekCatalog:!!state.deepseekCatalog,codexCatalog:!!state.codexCatalog}));};
      await wait(()=>state.project?.id===input.project_id&&state.deepseekCatalog&&state.ready&&state.conversation&&!conversationUI.restoring);
      if($('provider').value!=='deepseek'||state.codexCatalog)throw new Error('DeepSeek initialization required Codex');
      if(!$('studyModel').textContent.includes('V4.1 Flash')||!$('studyModel').textContent.includes('V4 Pro')||!$('studyModel').textContent.includes('兼容名'))throw new Error('DeepSeek choices missing');
      if(state.settings.deepseek_model!=='deepseek-flash')throw new Error('New default not Flash');
      await $('reloadStudyModels').onclick();
      if(state.deepseekCatalog.source!=='api')throw new Error('DeepSeek refresh did not read metadata');
      $('studyModel').value='deepseek-v4-pro';$('studyModel').dispatchEvent(new Event('change'));await modelPreferenceSave;
      if($('reasoningEffort').disabled || ![...$('reasoningEffort').options].some(row=>row.value==='max'))throw new Error('DeepSeek native effort choices are unavailable');
      $('reasoningEffort').value='low';$('reasoningEffort').dispatchEvent(new Event('change'));await modelPreferenceSave;
      state.selected.add(input.source_id);scheduleReading();await ensureReading();
      $('prompt').value='请解释概念、论证与适用条件。';await $('sendMessage').onclick();
      if(!state.conversation)throw new Error('Tutor did not establish dialogue');
      const conversation=state.conversation;
      $('withExercises').checked=false;$('reviewMode').value='express';$('outputFormat').value='docx';
      await $('generate').onclick();
      const jobs=await api('/api/projects/'+input.project_id+'/jobs');
      const generated=jobs.find(row=>row.kind==='generate');
      await wait(async()=>['completed','failed'].includes((await api('/api/jobs/'+generated.id)).status));
      const job=await api('/api/jobs/'+generated.id);
      if(job.status!=='completed')throw new Error('Generation failed: '+job.error);
      if(state.conversation!==conversation||job.payload.model!=='deepseek-v4-pro')throw new Error('Generation did not continue tutor model/dialogue');
      const calls=await api('/__model_test__/requests');
      if(calls.model_requests.length!==2||calls.model_requests.some(row=>row.model!=='deepseek-v4-pro'))throw new Error('Wrong DeepSeek model requests: '+JSON.stringify(calls));
      if(calls.model_requests.some(row=>row.effort!=='low'||row.thinking?.type!=='enabled'))throw new Error('DeepSeek chat/document ignored selected native effort');
      $('studyModel').value='';$('studyModel').dispatchEvent(new Event('change'));await modelPreferenceSave;
      if(currentModel()!=='deepseek-flash')throw new Error('Automatic default did not resolve actual model');
      $('prompt').value='回到默认模型，再解释论证。';await $('sendMessage').onclick();await $('generate').onclick();
      const newer=(await api('/api/projects/'+input.project_id+'/jobs')).find(row=>row.kind==='generate'&&row.id!==generated.id);
      await wait(async()=>['completed','failed'].includes((await api('/api/jobs/'+newer.id)).status));
      const renewed=await api('/api/jobs/'+newer.id);
      const latest=(await api('/__model_test__/requests')).model_requests.slice(2);
      if(renewed.status!=='completed'||renewed.payload.model!=='deepseek-flash'||latest.length!==2||latest.some(row=>row.model!=='deepseek-flash'))throw new Error('Default selection reused previous Pro model');
      $('studyModel').value='deepseek-v4-pro';$('studyModel').dispatchEvent(new Event('change'));await modelPreferenceSave;
      state.selected.clear();scheduleReading();clearTimeout(readingTimer);
      $('provider').value='codex';await $('provider').onchange();
      await wait(()=>state.codexCatalog?.models?.length===8);
      if(!$('studyModel').textContent.includes('gpt-6.1-sol')||!$('studyModel').textContent.includes('gpt-6-astra'))throw new Error('Codex models truncated');
      $('studyModel').value='gpt-6.1-sol';$('studyModel').dispatchEvent(new Event('change'));
      $('reasoningEffort').value='ultra';$('reasoningEffort').dispatchEvent(new Event('change'));await modelPreferenceSave;
      $('prompt').value='解释论证的构造动机。';await $('sendMessage').onclick();
      const codex=(await api('/__model_test__/requests')).model_requests.at(-1);
      if(codex.model!=='gpt-6.1-sol'||codex.effort!=='ultra')throw new Error('Codex model/effort not sent');
      localStorage.clear();
      await flushConversation();
      return {deepseek_independent:true,deepseek_choices:true,paginated_codex_models:8,
              same_tutor_generation_model:true,deepseek_chat_document_effort_reached:true,default_selection_resolves_actual_model:true,codex_model_effort_reached:true};
    })()`);
    // A fresh origin reproduces the new random port used on desktop restarts.
    await win.loadURL(input.urls[1]);
    const second=await win.webContents.executeJavaScript(`(async()=>{
      const wait=async fn=>{for(let i=0;i<150;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw new Error('wait timed out at new origin: '+JSON.stringify({project:state.project?.id,ready:state.ready,conversation:state.conversation,restoring:conversationUI.restoring,deepseekCatalog:!!state.deepseekCatalog,codexCatalog:!!state.codexCatalog}));};
      await wait(()=>state.project&&state.codexCatalog&&state.ready&&state.conversation&&!conversationUI.restoring);
      if(currentModel()!=='gpt-6.1-sol'||currentEffort()!=='ultra')throw new Error('New origin lost Codex preference');
      $('provider').value='deepseek';await $('provider').onchange();await wait(()=>state.deepseekCatalog);
      if(currentModel()!=='deepseek-v4-pro'||currentEffort()!=='low')throw new Error('Provider switch lost native preference or leaked Codex effort');
      $('reasoningEffort').value='high';$('reasoningEffort').dispatchEvent(new Event('change'));await modelPreferenceSave;
      if(currentEffort()!=='high'||state.settings.chat_effort_deepseek!=='high')throw new Error('DeepSeek high effort did not persist');
      await api('/__model_test__/offline',{method:'POST'});await $('reloadStudyModels').onclick();
      if(state.deepseekCatalog.source!=='cached'||currentModel()!=='deepseek-v4-pro'||!$('modelStatus').textContent.includes('上次'))throw new Error('Offline lost DeepSeek choice');
      $('provider').value='codex';await $('provider').onchange();await refreshStudyModels(true);
      if(state.codexCatalog.source!=='cached'||state.codexCatalog.models.length!==8||currentModel()!=='gpt-6.1-sol')throw new Error('Offline lost full Codex directory');
      $('studyModel').value='gpt-6-luna';$('studyModel').dispatchEvent(new Event('change'));await modelPreferenceSave;
      if(currentEffort()!==null||[...$('reasoningEffort').options].some(row=>row.value==='ultra'))throw new Error('Unsupported effort not reset');
      $('studyModel').value='gpt-6.1-sol';$('studyModel').dispatchEvent(new Event('change'));await modelPreferenceSave;
      if(currentEffort()!==null)throw new Error('An invalidated effort silently reappeared after model switch');
      showView('study');
      if(document.documentElement.scrollWidth>innerWidth)throw new Error('Horizontal overflow');
      return {fresh_origin_restore:true,provider_preferences_separate:true,offline_preserves_choices:true,
              unsupported_effort_reset:true,overflow:false};
    })()`);
    await new Promise(r=>setTimeout(r,300));
    fs.writeFileSync(path.join(path.dirname(casePath),'模型选择验收.png'),(await win.webContents.capturePage()).toPNG());
    if(errors.length)throw new Error(JSON.stringify(errors));
    console.log(JSON.stringify({ok:true,...first,...second,errors},null,2));win.destroy();app.quit();
  }catch(error){
    console.error(error);console.error(JSON.stringify({errors}));
    fs.writeFileSync(path.join(path.dirname(casePath),'failure-ui.png'),(await win.webContents.capturePage()).toPNG());
    win.destroy();app.exit(1);
  }
});
