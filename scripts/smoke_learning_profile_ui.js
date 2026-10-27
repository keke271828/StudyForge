const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const casePath=process.env.STUDYFORGE_FEEDBACK_UI_CASE_PATH;
const input=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(path.dirname(casePath),'electron-profile'));
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:1400,height:1100,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  const errors=[];
  win.webContents.on('console-message',(_event,level,text)=>{if(level===3&&!text.includes('404'))errors.push(text);});
  try{
    await win.loadURL(input.url);
    await win.webContents.executeJavaScript(`(async()=>{
      for(let i=0;i<200;i++){if(state.project?.id===${JSON.stringify(input.project_id)}&&state.settings&&state.sources.length)break;await new Promise(r=>setTimeout(r,100));}
      await refreshStudyModels();await ensureReading();
    })()`);
    const beforeControls=JSON.parse(fs.readFileSync(path.join(path.dirname(casePath),'cloud_requests.json'),'utf8')).requests;
    const editing=await win.webContents.executeJavaScript(`(async()=>{
      const input=${JSON.stringify(input)};
      const wait=async predicate=>{for(let i=0;i<200;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
      await wait(()=>state.project?.id===input.project_id&&state.settings);
      showView('profile');await wait(()=>$('learningMemory').querySelectorAll('[data-profile-insight]').length===30);
      if(!$('profile').textContent.includes('未测验')||!$('profile').textContent.includes('缺少逐条证据'))throw new Error('自评与早期汇总未区分');
      const first=[...$('learningMemory').querySelectorAll('[data-profile-insight]')].map(x=>x.dataset.profileInsight);
      $('profileNext').click();await wait(()=>$('profilePage').textContent.startsWith('2 /'));
      if([...$('learningMemory').querySelectorAll('[data-profile-insight]')].some(x=>first.includes(x.dataset.profileInsight)))throw new Error('分页重复');
      $('profileSearch').value='规训权力';$('profileSearch').dispatchEvent(new Event('input',{bubbles:true}));
      await wait(()=>$('learningMemory').querySelectorAll('[data-profile-insight]').length===3);
      document.querySelector('[data-profile-insight="'+input.insight_id+'"]').click();await wait(()=>profileState.editor?.id===input.insight_id);
      if(!$('profileEvidenceText').textContent.includes('请解释概念')||!$('profileOriginalObservation').textContent.includes('旧判断'))throw new Error('原依据缺失');
      $('profileCorrection').value='已理解概念，请解释论证的适用边界。';
      await refreshProfile(false);
      if($('profileCorrection').value!=='已理解概念，请解释论证的适用边界。')throw new Error('自动刷新覆盖未保存纠正');
      $('saveProfileCorrection').click();await wait(()=>!profileState.saving&&profileState.editor?.version===1);
      if(!$('profileEvidenceMeta').textContent.includes('用户纠正')||!$('profileOriginalObservation').textContent.includes('旧判断'))throw new Error('纠正冒充原依据');
      $('resetProfileCorrection').click();await wait(()=>!profileState.saving&&profileState.editor?.version===2);
      if(!$('profileCorrection').value.includes('旧判断'))throw new Error('恢复原判断失败');
      $('profileCorrection').value='已理解概念，请解释论证的适用边界。';$('saveProfileCorrection').click();
      await wait(()=>!profileState.saving&&profileState.editor?.version===3);
      if($('profileEvidenceDialog').scrollWidth>$('profileEvidenceDialog').clientWidth+2)throw new Error('画像面板横向溢出');
      return {categories:true,pagination:true,old_evidence_searchable:true,evidence:true,correction:true,original_preserved:true,draft_survives_refresh:true,reset:true,no_overflow:true};
    })()`);
    const screenshot=path.join(path.dirname(casePath),'画像纠正.png');
    fs.writeFileSync(screenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    const actions=await win.webContents.executeJavaScript(`(async()=>{
      const input=${JSON.stringify(input)};
      const wait=async predicate=>{for(let i=0;i<200;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
      $('closeProfileEvidence').click();
      await openProfileInsight(input.high_id);
      $('removeProfileInsight').click();
      if($('profileRemovalConfirm').hidden)throw new Error('删除影响没有说明');
      $('confirmProfileRemoval').click();await wait(()=>!profileState.saving&&profileState.editor?.deleted);
      if((await api('/api/profile')).find(x=>x.topic==='规训权力').score!==60)throw new Error('已移出分数仍影响画像');
      $('closeProfileEvidence').click();$('profileStatus').value='removed';$('profileStatus').dispatchEvent(new Event('change',{bubbles:true}));
      await wait(()=>$('learningMemory').querySelector('[data-profile-insight="'+input.high_id+'"]'));
      document.querySelector('[data-profile-insight="'+input.high_id+'"]').click();await wait(()=>profileState.editor?.id===input.high_id);
      $('restoreProfileInsight').click();await wait(()=>!profileState.saving&&!profileState.editor?.deleted);
      if((await api('/api/profile')).find(x=>x.topic==='规训权力').score!==72)throw new Error('恢复后分数未重算');
      $('removeProfileInsight').click();$('confirmProfileRemoval').click();await wait(()=>!profileState.saving&&profileState.editor?.deleted);
      $('closeProfileEvidence').click();$('profileStatus').value='active';await refreshProfile(false);
      let legacy=document.querySelector('[data-remove-legacy="早期电场"]');legacy.click();legacy.click();
      await wait(()=>!document.querySelector('[data-remove-legacy="早期电场"]')&&!$('removedLegacyProfiles').hidden);
      $('removedLegacyProfiles').open=true;document.querySelector('[data-restore-legacy="早期电场"]').click();
      await wait(()=>document.querySelector('[data-remove-legacy="早期电场"]'));
      return {removed_score_recomputed:true,restore:true,legacy_remove_restore:true};
    })()`);
    const afterControls=JSON.parse(fs.readFileSync(path.join(path.dirname(casePath),'cloud_requests.json'),'utf8')).requests;
    if(beforeControls!==afterControls)throw new Error('画像管理额外调用了模型');
    const teaching=await win.webContents.executeJavaScript(`(async()=>{
      const input=${JSON.stringify(input)};
      const wait=async predicate=>{for(let i=0;i<200;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
      await openLessonFeedback(input.submit_id);
      const cid=state.conversation;
      $('prompt').value='请继续解释规训权力的论证。';$('sendMessage').click();await wait(()=>!state.busy&&!$('prompt').value);
      const before=(await api('/api/projects/'+input.project_id+'/jobs')).map(x=>x.id);
      $('withExercises').checked=false;$('generate').click();let generated;
      await wait(async()=>{generated=(await api('/api/projects/'+input.project_id+'/jobs')).find(x=>x.kind==='generate'&&!before.includes(x.id));return generated?.status==='completed'&&!state.busy;});
      const job=await api('/api/jobs/'+generated.id);
      if(state.conversation!==cid)throw new Error('画像操作切换了导师');
      if(job.result.exercises)throw new Error('画像操作擅自布置习题');
      return {same_tutor:true,chat_and_document:true};
    })()`);
    if(errors.length)throw new Error(errors.join('; '));
    const finalCalls=JSON.parse(fs.readFileSync(path.join(path.dirname(casePath),'cloud_requests.json'),'utf8')).requests;
    console.log(JSON.stringify({ok:true,editing,actions,teaching,controls_cloud_requests:afterControls-beforeControls,tutor_cloud_requests:finalCalls-afterControls,screenshot,console_errors:errors}));
    win.destroy();app.quit();
  }catch(error){
    console.error(error);
    try{console.error(await win.webContents.executeJavaScript(`(async()=>JSON.stringify({toast:$('toast').textContent,prompt:$('prompt').value,busy:state.busy,provider:$('provider').value,model:currentModel(),effort:currentEffort(),selected:[...state.selected],reading:state.reading,editor:profileState.editor,messages:$('messages').textContent.slice(-1800),jobs:await api('/api/projects/'+state.project.id+'/jobs')}))()`));}catch(_){ }
    win.destroy();app.exit(1);
  }
});
