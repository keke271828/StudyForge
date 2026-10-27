/* Real Electron interactions against an isolated server with mocked model replies. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const casePath=process.env.STUDYFORGE_FEEDBACK_UI_CASE_PATH;
const input=JSON.parse(fs.readFileSync(casePath,'utf8')),root=path.dirname(casePath);
app.setPath('userData',path.join(root,'electron-practice'));
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:1440,height:1200,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  const errors=[],calls=()=>JSON.parse(fs.readFileSync(path.join(root,'cloud_requests.json'),'utf8')).requests;
  let phase='init',controls=0;
  const run=async(code)=>win.webContents.executeJavaScript(`(async()=>{
    const input=${JSON.stringify(input)};
    const wait=async predicate=>{for(let i=0;i<160;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
    const box=()=>document.getElementById('set-'+input.practice_set_id);
    ${code}
  })()`);
  win.webContents.on('console-message',(_event,level,text)=>{if(level===3&&!text.includes('404'))errors.push(text);});
  try{
    await win.loadURL(input.url);
    await run(`
      await wait(()=>state.project&&state.settings);
      const projects=await api('/api/projects');await selectProject(projects.find(x=>x.id===input.project_id));
      await refreshStudyModels();await ensureReading();await openLessonFeedback(input.submit_id);
      showView('exercises');await wait(()=>document.querySelector('[data-open-set="'+input.practice_set_id+'"]'));
      await openSet(input.practice_set_id);
    `);
    phase='hints and drafts';let before=calls();
    const hints=await run(`
      if(!box().querySelector('.katex')||box().textContent.includes('PRIVATE_'))throw new Error('公式未渲染或答案提前泄露');
      box().querySelector('[data-answer="0"]').value='因为相似，因此机制相同。';
      box().querySelector('[data-recovery-mode]').value='adaptive';box().querySelector('[data-used-notes]').value='false';
      await Promise.all([refreshExercises(),refreshExercises()]);
      if(box().hidden||!box().querySelector('[data-answer]'))throw new Error('并发刷新关闭正在作答的题目');
      if(box().querySelector('[data-answer="0"]').value!=='因为相似，因此机制相同。'||box().querySelector('[data-recovery-mode]').value!=='adaptive')throw new Error('刷新覆盖作答草稿或选项');
      const panel=box().querySelector('[data-hint-controls="0"]');panel.open=true;
      const kind=panel.querySelector('[data-hint-kind]');kind.value='argumentation';kind.dispatchEvent(new Event('change',{bubbles:true}));
      for(const level of [1,2,3]){panel.querySelector('[data-get-hint]').click();await wait(()=>!panel.querySelector('[data-get-hint]').disabled&&panel.querySelector('[data-hint-text]').textContent.startsWith('第'+level+'层'));}
      if(panel.textContent.includes('PRIVATE_'))throw new Error('提示泄露答案');
      box().querySelector('#submitAnswers').click();await wait(()=>!box().querySelector('#submitAnswers').disabled);
      if((await api('/api/exercises/'+input.practice_set_id)).status!=='assigned'||!$('toast').textContent.includes('全部题目'))throw new Error('部分提交未阻止');
      box().querySelector('[data-answer="1"]').value='因为相似，所以可以推广。';
      return {math_rendered:true,answer_hidden:true,draft_preserved:true,open_form_survives_concurrent_refresh:true,three_hints:true,partial_submission_blocked:true};
    `);controls+=calls()-before;
    phase='adaptive grading';
    const diagnosis=await run(`
      box().querySelector('#submitAnswers').click();
      await wait(()=>box()?.querySelector('.practice-followup'));
      const s=await api('/api/exercises/'+input.practice_set_id);
      if(s.status!=='repair_required'||!box().querySelector('.practice-diagnosis').textContent.includes('暂定诊断'))throw new Error('低分诊断流程失败');
      if(box().querySelector('.practice-feynman').open)throw new Error('自主修复强制费曼');
      if(!box().querySelector('.practice-diagnosis blockquote').textContent.includes('因为相似'))throw new Error('缺少作答依据');
      if((await api('/api/projects/'+input.project_id+'/exercises')).length!==1)throw new Error('低分擅自出新题');
      return {tentative_diagnosis:true,quote:true,no_automatic_harder_set:true,optional_feynman:true};
    `);
    const screenshot=path.join(root,'按需练习.png');
    await run(`box().querySelector('.practice-followup').scrollIntoView({block:'center',behavior:'instant'});await new Promise(r=>setTimeout(r,160));`);
    fs.writeFileSync(screenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    phase='scheduling and same mentor';before=calls();
    const schedule=await run(`
      box().querySelector('.review-scheduling').open=true;
      box().querySelector('[data-review-question][value="1"]').checked=false;
      box().querySelector('[data-review-interval]').value='3';box().querySelector('[data-schedule-review]').click();
      await wait(()=>$('reviewQueueItems').querySelectorAll('[data-review-select]').length===2);
      if((await api('/api/reviews')).items.find(x=>x.origin_set_id===input.practice_set_id).interval_days!==3)throw new Error('复习间隔未保存');
      const cid=state.conversation;$('prompt').value='已有要求：解释适用条件。';box().querySelector('[data-practice-tutor]').click();
      await wait(()=>$('prompt').value.includes('这次练习的卡点'));
      if(state.conversation!==cid||!$('prompt').value.startsWith('已有要求：'))throw new Error('导师或输入要求丢失');
      showView('exercises');await wait(()=>document.querySelector('[data-open-set="'+input.practice_set_id+'"]'));await openSet(input.practice_set_id);
      $('reviewDueOnly').checked=true;$('reviewDueOnly').dispatchEvent(new Event('change',{bubbles:true}));
      await wait(()=>$('reviewQueueItems').querySelectorAll('[data-review-select]').length===0);
      $('reviewDueOnly').checked=false;$('reviewDueOnly').dispatchEvent(new Event('change',{bubbles:true}));
      await wait(()=>$('reviewQueueItems').querySelectorAll('[data-review-select]').length===2);
      $('reviewQueuePanel').open=true;
      for(const item of $('reviewQueueItems').querySelectorAll('[data-review-select]')){item.checked=true;item.dispatchEvent(new Event('change',{bubbles:true}));}
      $('startMixedReview').click();let s;
      await wait(async()=>{s=(await api('/api/projects/'+input.project_id+'/exercises')).find(x=>x.practice.is_review);return s&&document.getElementById('set-'+s.id)?.querySelector('#submitAnswers');});
      if(s.questions.length!==2||s.solutions||document.getElementById('set-'+s.id).textContent.includes('PRIVATE_'))throw new Error('混合复习提前泄露答案');
      window.practiceSmokeReviewId=s.id;
      return {chosen_interval:true,due_filter:true,cross_project_mixed:true,review_answers_hidden:true,same_tutor:true,prompt_preserved:true};
    `);controls+=calls()-before;
    const queueScreenshot=path.join(root,'混合复习.png');
    await run(`$('reviewQueuePanel').scrollIntoView({block:'start',behavior:'instant'});await new Promise(r=>setTimeout(r,160));`);
    fs.writeFileSync(queueScreenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    phase='early review grading';
    const review=await run(`
      const id=window.practiceSmokeReviewId,reviewBox=()=>document.getElementById('set-'+id);
      reviewBox().querySelectorAll('[data-answer]').forEach(x=>x.value='完整论证：相似本身不证明机制，需要机制证据与边界。');
      reviewBox().querySelector('[data-used-notes]').value='false';reviewBox().querySelector('#submitAnswers').click();
      await wait(()=>reviewBox()?.querySelector('.practice-followup'));
      const s=await api('/api/exercises/'+id),grade=(await api('/api/exercises/'+id+'/submissions'))[0].grade;
      if(s.status!=='passed'||!s.solutions||grade.practice_context.timing.some(x=>x.due_reached||x.delay_hours>=24))throw new Error('提前复习被视为延迟掌握，或80分边界失败');
      if((await api('/api/reviews')).items.some(x=>x.active_set_id))throw new Error('复习未完成解锁');
      const profile=(await api('/api/profile')).find(x=>x.topic==='论证');
      if(profile.assisted_count!==1||profile.review_count!==1||profile.delayed_count!==0)throw new Error('画像未区分提示支持和提前复习');
      return {complete_submission_releases_answers:true,boundary_80:true,early_review_not_delayed:true,profile_conditions:true,next_due_saved:true};
    `);
    phase='optional feynman';
    await run(`
      await openSet(input.practice_set_id);box().querySelector('.practice-feynman').open=true;
      box().querySelector('#feynmanText').value='我先区分现象相似与机制相同，再说明哪些证据能帮助排除其他解释。论证要有前提、依据与适用边界，不能从表面相似直接得到共同机制。'.repeat(3);
      box().querySelector('#submitFeynman').click();await wait(async()=> (await api('/api/exercises/'+input.practice_set_id)).status==='repair_ready'&&box()?.querySelector('.grading-feedback')?.textContent.includes('费曼讲解 · 80'));
      if((await api('/api/projects/'+input.project_id+'/exercises')).length!==2)throw new Error('可选费曼通过后自动加难出题');
    `);
    phase='explicit repair and removal';before=calls();
    const repair=await run(`
      box().querySelector('[data-repair-set]').click();let repaired;
      await wait(async()=>{repaired=(await api('/api/projects/'+input.project_id+'/exercises')).find(x=>x.id!==input.practice_set_id&&!x.practice.is_review);return repaired&&document.getElementById('set-'+repaired.id)?.querySelector('#submitAnswers');});
      if(repaired.difficulty!==3||repaired.solutions)throw new Error('修复改变难度或公开解析');
      const cached=await api('/api/exercises/'+input.practice_set_id+'/repair',jsonOptions('POST',assessmentSelection()));
      if(!cached.cached||cached.exercise_set.id!==repaired.id)throw new Error('重复生成修复题');
      const artifact=(await api('/api/projects/'+input.project_id+'/artifacts')).find(x=>x.kind==='exercise');
      if(artifact?.format!=='docx')throw new Error('修复练习缺少独立DOCX');
      for(const item of [...$('reviewQueueItems').querySelectorAll('[data-remove-review]')]){const id=item.dataset.removeReview;document.querySelector('[data-remove-review="'+id+'"]').click();await wait(()=>!document.querySelector('[data-remove-review="'+id+'"]'));}
      if((await api('/api/reviews')).total!==0||(await api('/api/exercises/'+input.practice_set_id+'/submissions')).length!==1)throw new Error('移除复习损坏旧成绩');
      return {explicit_same_difficulty_repair:true,repair_docx:true,cached_repair:true,queue_removal_preserves_grade:true};
    `);controls+=calls()-before;
    if(errors.length)throw new Error(errors.join('; '));
    const repairs=JSON.parse(fs.readFileSync(path.join(root,'repair_requests.json'),'utf8'));
    if(repairs.length!==1||repairs[0].model!=='ui-test-model')throw new Error('修复模型或调用去重失败');
    console.log(JSON.stringify({ok:true,hints,diagnosis,schedule,review,repair,controls_cloud_requests:controls,screenshot,queueScreenshot,console_errors:errors}));
    win.destroy();app.quit();
  }catch(error){
    console.error(phase,error);
    try{console.error(await run(`return JSON.stringify({toast:$('toast').textContent,project:state.project?.id,queue:$('reviewQueueItems').textContent,exercise:$('exercises').textContent.slice(-1800),sets:await api('/api/projects/'+state.project.id+'/exercises')});`));}catch(_){ }
    win.destroy();app.exit(1);
  }
});
