const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const casePath=process.env.STUDYFORGE_FEEDBACK_UI_CASE_PATH;
const input=JSON.parse(fs.readFileSync(casePath,'utf8'));
app.setPath('userData',path.join(path.dirname(casePath),'electron-profile'));
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:1400,height:1200,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  const errors=[];
  win.webContents.on('console-message',(_event,level,text)=>{if(level===3&&!text.includes('404'))errors.push(text);});
  try {
    await win.loadURL(input.url);
    const result=await win.webContents.executeJavaScript(`(async()=>{
      const input=${JSON.stringify(input)};
      const wait=async predicate=>{for(let i=0;i<200;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
      await wait(()=>state.project?.id===input.project_id&&state.settings);
      await openLessonFeedback(input.submit_id);
      const cid=state.conversation,reading=state.reading.reading_id;
      $('showKnowledge').click();await wait(()=>$('knowledgeDialog').open&&!$('buildKnowledge').disabled);
      if(knowledgeState.row?.structure)throw new Error('打开面板不应自动生成结构');
      $('buildKnowledge').click();await wait(()=>knowledgeState.row?.structure&&!knowledgeState.busy);
      if(knowledgeState.row.structure.concepts.length!==2||knowledgeState.row.structure.relations.length!==1)throw new Error('结构缺少概念或关系');
      if(!$('knowledgeDetail').textContent.includes('教学建议')||!$('knowledgeDetail').textContent.includes('不是唯一顺序'))throw new Error('关系未区分依据与边界');
      if($('knowledgeDialog').scrollWidth>$('knowledgeDialog').clientWidth+2)throw new Error('面板横向溢出');
      document.querySelector('[data-knowledge-source]').click();
      await wait(()=>$('knowledgeSourceExcerpt').textContent.includes('福柯讨论规训权力'));
      if($('knowledgeTitle').getBoundingClientRect().top<$('knowledgeDialog').getBoundingClientRect().top)throw new Error('查看来源后标题和关闭按钮被卷走');
      document.querySelector('#knowledgeNodes [data-knowledge-node="p1-discipline"]').click();
      if(!$('knowledgeDetail').textContent.includes('人物与角色')||!$('knowledgeDetail').textContent.includes('福柯'))throw new Error('人物归属未显示');
      $('knowledgeSearch').value='规训';$('knowledgeSearch').dispatchEvent(new Event('input',{bubbles:true}));
      if($('knowledgeNodes').querySelectorAll('button').length!==1)throw new Error('搜索没有过滤知识点');
      $('knowledgeContent').scrollTop=0;
      await new Promise(r=>setTimeout(r,150));
      return {optional:true,concepts_and_relations:true,evidence_opened:true,search:true,attribution:true,no_overflow:true};
    })()`);
    const screenshot=path.join(path.dirname(casePath),'知识结构.png');
    fs.writeFileSync(screenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    const actions=await win.webContents.executeJavaScript(`(async()=>{
      const input=${JSON.stringify(input)};
      const wait=async predicate=>{for(let i=0;i<200;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
      const cid=state.conversation,reading=state.reading.reading_id,mapId=knowledgeState.row.id;
      $('prompt').value='请保留原文语境，不要出题。';
      document.querySelector('[data-knowledge-teach]').click();
      if($('knowledgeDialog').open||state.conversation!==cid||state.reading.reading_id!==reading||!$('prompt').value.includes('请保留原文语境')||!$('prompt').value.includes('规训权力'))throw new Error('带回导师丢失要求或原对话');
      // Viewing and returning to the mentor is local until the student sends.
      if((await api('/api/profile')).length||(await api('/api/projects/'+input.project_id+'/exercises')).length)throw new Error('结构整理错误地评分或出题');
      $('sendMessage').click();await wait(()=>!state.busy&&!$('prompt').value);
      const before=(await api('/api/projects/'+input.project_id+'/jobs')).map(x=>x.id);
      $('withExercises').checked=false;$('generate').click();let generated;
      await wait(async()=>{generated=(await api('/api/projects/'+input.project_id+'/jobs')).find(x=>x.kind==='generate'&&!before.includes(x.id));return generated?.status==='completed'&&!state.busy;});
      const job=await api('/api/jobs/'+generated.id);
      if(job.payload.knowledge_map_id!==mapId||!job.payload.knowledge_context.includes('原资料知识结构'))throw new Error('生成未固定知识结构');
      const artifact=(await api('/api/projects/'+input.project_id+'/artifacts')).find(x=>x.metadata.generation_job_id===job.id);
      if(artifact.metadata.knowledge_map_id!==mapId)throw new Error('成果丢失结构来源');
      if(state.conversation!==cid)throw new Error('生成变成另一个导师');
      showView('study');await openKnowledge();
      if(knowledgeState.row.id!==mapId)throw new Error('重新打开没有复用结构');
      const cached=await api('/api/knowledge/build',jsonOptions('POST',{project_id:input.project_id,source_ids:[...state.selected],provider:'deepseek',model:'ui-test-model',reading_id:reading}));
      await wait(async()=>(await api('/api/jobs/'+cached.job_id)).status==='completed');
      if(!(await api('/api/jobs/'+cached.job_id)).result.cached)throw new Error('相同资料与模型未复用结果');
      return {same_tutor:true,instructions_preserved:true,no_score_or_exercises:true,mentor_and_lecture_context:true,generation_snapshot:true,cache_reused:true};
    })()`);
    if(errors.length)throw new Error(errors.join('; '));
    console.log(JSON.stringify({ok:true,result,actions,screenshot,console_errors:errors}));
    win.destroy();app.quit();
  }catch(error){console.error(error);win.destroy();app.exit(1);}
});
