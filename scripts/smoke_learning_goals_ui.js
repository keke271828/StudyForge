const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_GOALS_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_GOALS_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let i=0;i<400;i++){if(await run(code))return;await sleep(80);}throw Error('Timeout: '+code);}
async function inspect(){return run(`api('/__goals_test__/state')`);}
async function snapshot(name){await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');win.webContents.invalidate();await sleep(300);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
const checks=[],contrastResults=[];
function luminance(rgb){return rgb.slice(0,3).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);}
async function contrast(panel,text,theme){
  const colors=await run(`(()=>{const box=document.querySelector('${panel}'),p=box.querySelector('${text}'),canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');const rgba=color=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return Array.from(ctx.getImageData(0,0,1,1).data);};const layers=[];for(let node=p;node;node=node.parentElement){layers.push(rgba(getComputedStyle(node).backgroundColor));if(node===box)break;}return {layers,text:rgba(getComputedStyle(p).color)};})()`);
  const ink=colors.text;
  assert.ok(colors.layers.at(-1)[3]/255>=.96,'Background readability protection must be applied: '+panel);
  const min=Math.min(...[[0,0,0],[255,255,255],[244,166,83]].map(wallpaper=>{
    let bg=wallpaper;for(const layer of [...colors.layers].reverse()){const alpha=layer[3]/255;bg=layer.slice(0,3).map((v,i)=>v*alpha+bg[i]*(1-alpha));}
    const a=luminance(bg),b=luminance(ink.slice(0,3).map((v,i)=>v*ink[3]/255+bg[i]*(1-ink[3]/255)));return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  }));
  assert.ok(min>=4.5,`${theme} ${panel} ${text}: ${min}`);contrastResults.push({theme,panel,text,minimum:Number(min.toFixed(2))});
}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1480,height:1080,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
    await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.project}'),{conversationId:'${input.chat}'})`);
    if(input.phase===1){
      await run(`$('openModeGuide').click()`);await until(`$('modeGuideDialog').open&&document.querySelectorAll('[data-mode-guide-select]').length===3`);
      for(const mode of ['overview','research','deep']){
        if(!await run(`$('modeGuideDialog').open`))await run(`$('openModeGuide').click()`);
        await run(`document.querySelector('[data-mode-guide-select="${mode}"]').click()`);
        await until(`!$('modeGuideDialog').open&&$('learningMode').value==='${mode}'`);
        await run(`flushConversation()`);
        assert.equal(await run(`(async()=>{const chat=await api('/api/conversations/${input.chat}?project_id=${input.project}');return chat.learning_mode;})()`),mode);
      }
      assert.equal((await inspect()).calls.length,0);checks.push('模式指南实际切换并保存当前对话模式，不调用模型');
      await run(`document.querySelector('[data-view="goals"]').click()`);await until(`goalUI.project==='${input.project}'`);
      assert.equal(await run('goalUI.items.length'),0);
      await run(`$('newLearningGoal').click()`);await until(`$('learningGoalDialog').open&&!$('saveLearningGoal').disabled`);
      await run(`$('goalName').value='描述与规范';$('goalDomain').value='哲学';$('goalIntent').value='deep';$('goalIntent').dispatchEvent(new Event('change',{bubbles:true}));$('goalCriterion').value='解释事实为何不足以独立推出评价结论，检查加入评价前提后的适用条件';$('learningGoalForm').requestSubmit()`);
      await until(`goalUI.items.length===1&&!$('learningGoalDialog').open`);
      const goal=await run('goalUI.items[0]');assert.equal(goal.intent,'deep');assert.deepEqual(goal.source_ids,[input.source]);
      assert.equal((await inspect()).calls.length,0,'Planning must not silently call the model');checks.push('规划不调用模型');
      await run(`$('goalFromKnowledge').click()`);await until(`$('knowledgeDialog').open&&knowledgeState.row?.structure`);
      await run(`$('addKnowledgeGoals').click()`);await until(`goalUI.items.length===3`);
      assert.equal(await run(`goalUI.items.filter(g=>g.intent==='explore').length`),2);
      assert.equal(await run(`goalUI.items.find(g=>g.name==='规范性判断').prerequisites[0].basis`),'teaching');checks.push('知识结构带依据加入路线，不认定已掌握');
      await run(`document.querySelector('[data-study-goal="${goal.id}"]').click()`);await until(`state.view==='study'&&goalUI.focus==='${goal.id}'`);
      assert.equal(await run(`$('learningMode').value`),'deep');assert.equal(await run(`$('prompt').value.includes('评价前提')`),true);
      assert.equal((await inspect()).calls.length,0,'Preparing a learning request must not send it');
      await run(`$('sendMessage').click()`);await until(`!isChatBusy('${input.chat}')&&$('messages').textContent.includes('二者之间需要评价前提')`);
      let data=await inspect();const chatCall=data.calls.find(c=>c.kind==='chat');assert.ok(chatCall.user.includes(goal.criterion));assert.ok(!chatCall.user.includes('PRIVATE_SECOND_CHAT'));assert.ok(!chatCall.user.includes('DO_NOT_READ_PREVIEW'));checks.push('导师读取学习目标和完整原资料，隔离其他对话');
      await run(`selectConversation('${input.second}')`);assert.equal(await run('goalUI.focus'),null);assert.equal(await run('state.selected.size'),0);
      await run(`(async()=>{await selectConversation('${input.chat}');showView('goals');})()`);await until(`goalUI.focus==='${goal.id}'`);
      await run(`document.querySelector('[data-check-goal="${goal.id}"]').click()`);
      await until(`(async()=>{const x=await api('/__goals_test__/state');return x.calls.some(c=>c.kind==='design');})()`);
      await run(`showView('goals');refreshLearningGoals()`);await until(`goalUI.tasks.length===1&&document.querySelector('[data-goal-task]')`);
      const job=await run('goalUI.tasks[0].job_id');await run(`document.querySelector('[data-goal-task="${job}"]').click()`);
      await until(`goalUI.tasks.some(t=>t.status==='pausing')`);
      await run(`api('/__goals_test__/release',{method:'POST'})`);
      await until(`goalUI.tasks.some(t=>t.status==='paused')`);assert.equal((await inspect()).artifacts.length,0);checks.push('理解检查真实暂停，不提前导出');
      await run(`document.querySelector('[data-goal-task="${job}"]').click()`);
      await until(`(async()=>{const job=await api('/api/jobs/${job}');if(job.status==='failed')throw Error(job.error);return job.status==='completed';})()`);
      await run(`refreshLearningGoals()`);data=await inspect();const set=data.checks[0].exercise_set_id;
      assert.equal(data.artifacts.length,1);assert.equal(data.artifacts[0].format,'docx');assert.ok(!data.artifacts[0].paragraphs.includes('PRIVATE_REFERENCE'));
      assert.ok(!await run(`(async()=>JSON.stringify(await api('/api/exercises/${set}')).includes('PRIVATE_REFERENCE'))()`));checks.push('仅三题DOCX，提交前不显示私有解析');
      await run(`showView('study');$('submitHomework').click()`);await until(`$('homeworkSet').value==='${set}'`);
      await run(`$('homeworkQuestions').querySelectorAll('[data-homework-answer]').forEach(x=>x.value='事实描述不含评价原则，规范结论需要相应评价前提，并核对适用条件');$('homeworkQuestions').querySelector('[data-used-notes]').value='false';$('homeworkQuestions').querySelector('[data-used-notes]').dispatchEvent(new Event('change',{bubbles:true}));$('homeworkComplete').checked=true;$('homeworkSubmit').click()`);
      await until(`(async()=>{const x=await api('/__goals_test__/state');if(x.attempts[0]?.status==='failed')throw Error(x.attempts[0].error);return x.attempts[0]?.status==='completed';})()`);
      await run(`$('closeHomework').click();showView('goals');refreshLearningGoals()`);await until(`goalUI.items.find(g=>g.id==='${goal.id}').evidence.every(e=>e.latest?.score===100)`);
      assert.equal(await run(`goalUI.items.find(g=>g.id==='${goal.id}').recommendation.action`),'review');checks.push('作答条件进入证据，单次高分不判为精通');
      await run(`document.querySelector('[data-review-goal="${goal.id}"]').click()`);
      await until(`(async()=>{const q=await api('/api/reviews');return q.items.length===3;})()`);checks.push('按需安排延迟复习');
      await run(`document.querySelector('[data-goal-card="${goal.id}"] .goal-records').open=true;window.savedGoalNode=document.querySelector('[data-goal-card="${goal.id}"]');refreshLearningGoals()`);
      await sleep(2800);assert.equal(await run(`window.savedGoalNode===document.querySelector('[data-goal-card="${goal.id}"]')`),true);assert.equal(await run(`document.querySelector('[data-goal-card="${goal.id}"] .goal-records').open`),true);checks.push('轮询保留节点、展开状态与操作位置');
      for(const theme of ['paper','night']){
        await run(`surfacePreset('clear');saveStudioPreferences({ui_theme:'${theme}',ui_readability:'always',ui_background:'dusk',ui_background_transparency:0,ui_background_blur:0});`);
        await until(`document.documentElement.dataset.readability==='on'&&studioPending===0`);
        await run(`showView('study');$('openModeGuide').click()`);await until(`$('modeGuideDialog').open&&document.querySelectorAll('.mode-guide-card').length===3`);
        await contrast('.mode-guide-dialog','.small-note',theme);
        await contrast('.mode-guide-dialog','.section-head h2',theme);
        await contrast('.mode-guide-dialog','.section-head .eyebrow',theme);
        await contrast('.mode-guide-dialog','.mode-guide-card p',theme);
        await contrast('.mode-guide-dialog','.mode-guide-card li',theme);
        await snapshot('模式指南-'+theme);
        await run(`$('closeModeGuide').click();showView('goals')`);
        for(const [panel,text] of [['.goal-intro','p'],['.goal-count','span'],['.goal-card','.small-note'],['.goal-card','.goal-criterion-text'],['.goal-card','.goal-evidence-item span'],['.goal-card','.goal-records summary']])await contrast(panel,text,theme);
        await snapshot('学习路线-'+theme);
      }
      win.setSize(980,900);await snapshot('学习路线-窄窗口');assert.ok(await run(`document.documentElement.scrollWidth<=window.innerWidth+2`));
      win.setSize(660,900);await run(`showView('study');$('openModeGuide').click()`);await until(`$('modeGuideDialog').open`);
      assert.equal(await run(`getComputedStyle($('modeGuideCards')).gridTemplateColumns.trim().split(' ').filter(Boolean).length`),1);
      assert.ok(await run(`$('modeGuideDialog').scrollWidth<=$('modeGuideDialog').clientWidth+2`));
      await snapshot('模式指南-窄窗口');await run(`$('closeModeGuide').click();showView('goals')`);checks.push('模式指南窄窗口改为单列，弹窗内容不横向溢出');win.setSize(1480,1080);
      await run(`(async()=>{await selectProject(navigationUI.projects.find(p=>p.id==='${input.other}'));showView('goals');})()`);await until(`goalUI.project==='${input.other}'`);assert.equal(await run('goalUI.items.length'),0);checks.push('其他项目路线为空');
      await run(`(async()=>{await selectProject(navigationUI.projects.find(p=>p.id==='${input.project}'),{conversationId:'${input.chat}'});await prepareDesktopExit();})()`);
      fs.writeFileSync(path.join(root,'phase1.json'),JSON.stringify({goal:goal.id,set,checks,contrastResults},null,2));
    }else{
      const saved=JSON.parse(fs.readFileSync(path.join(root,'phase1.json'),'utf8'));checks.push(...saved.checks);contrastResults.push(...saved.contrastResults);
      assert.equal(await run('goalUI.focus'),saved.goal);assert.equal(await run('state.selected.has('+JSON.stringify(input.source)+')'),true);
      await run(`showView('goals')`);await until(`goalUI.items.length===3`);
      assert.equal(await run(`goalUI.items.find(g=>g.id==='${saved.goal}').evidence[0].latest.aid`),'self_reported_unassisted');checks.push('后台重启恢复目标、资料选择与成绩证据');
      await run(`document.querySelector('[data-edit-goal="${saved.goal}"]').click()`);await until(`$('learningGoalDialog').open&&!$('saveLearningGoal').disabled`);
      await run(`$('goalCriterion').value='新增独立重建论证要求';$('learningGoalForm').requestSubmit()`);await until(`!$('learningGoalDialog').open&&goalUI.items.find(g=>g.id==='${saved.goal}').outdated_record_count===3`);
      assert.equal(await run(`goalUI.items.find(g=>g.id==='${saved.goal}').evidence.every(e=>e.latest===null)`),true);checks.push('新目标范围不沿用旧成绩');
      await run(`document.querySelector('[data-remove-goal="${saved.goal}"]').click();refreshLearningGoals()`);await sleep(2800);assert.equal(await run(`document.querySelector('[data-remove-goal="${saved.goal}"]').textContent`),'再点确认移除');
      await run(`document.querySelector('[data-remove-goal="${saved.goal}"]').click()`);await until(`goalUI.items.length===2`);
      assert.equal(await run('goalUI.focus'),null);const data=await inspect();assert.equal(data.submissions.length,1);assert.equal(data.artifacts.length,3);checks.push('删除计划保留原题、作答、解析与批改文档');
      await run(`requestNavigationDelete('project','${input.project}')`);await run(`$('confirmNavigationDelete').click()`);
      await until(`!$('navigationDeleteDialog').open&&state.project?.id==='${input.other}'&&!conversationUI.restoring`);
      await run(`showView('goals');refreshLearningGoals()`);await until(`goalUI.project==='${input.other}'`);
      assert.equal(await run('goalUI.items.length'),0);assert.equal(await run('goalUI.focus'),null);checks.push('回收当前项目后清空其路线与对话目标');
      assert.deepEqual(errors,[]);fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:true,isolated:true,checks,artifacts:3,contrastResults,errors},null,2));
    }
    assert.deepEqual(errors,[]);app.exit(0);
  }catch(error){fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,console:errors},null,2));console.error(error);app.exit(1);}
});
