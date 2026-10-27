const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_PAUSE_CASE,root=path.dirname(casePath),data=JSON.parse(fs.readFileSync(casePath,'utf8'));
const phase=process.env.STUDYFORGE_PAUSE_PHASE,statePath=path.join(root,'ui-state.json');
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let n=0;n<220;n++){if(await run(code))return;await sleep(100);}throw Error('Timeout: '+code);}
async function fixture(){return run(`api('/__pause_fixture/state')`);}
async function hold(kind){await until(`api('/__pause_fixture/state').then(x=>x.holds.includes('${kind}'))`);}
async function saveImage(name){await sleep(150);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function pauseInline(job,kind){
  await until(`document.querySelector('[data-task-control="${job}"][data-action="pause"]')`);
  await run(`document.querySelector('[data-task-control="${job}"]').click()`);
  await until(`api('/api/jobs/${job}').then(x=>x.status==='pausing')`);
  await run(`api('/__pause_fixture/release/${kind}',{method:'POST'})`);
  await until(`api('/api/jobs/${job}').then(x=>x.status==='paused')`);
}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(data.url);await until('state.ready && state.conversation && !conversationUI.restoring && state.deepseekCatalog');
    if(phase==='1'){
      await run(`setSourceSelected('${data.source}',true)`);await hold('read');
      await until(`!$('readingTaskControl').hidden && $('readingTaskControl').dataset.action==='pause'`);
      const read=await run('state.reading.job_id');await run(`$('readingTaskControl').click()`);
      await until(`api('/api/jobs/${read}').then(x=>x.status==='pausing')`);
      await run(`api('/__pause_fixture/release/read',{method:'POST'})`);
      await until(`state.reading?.status==='paused' && $('readingTaskControl').textContent==='继续通读'`);
      assert.equal((await fixture()).calls.filter(x=>x==='read').length,1);await saveImage('通读暂停');
      await run(`showView('exercises');$('codingLanguage').value='matlab';$('newCoding').click()`);await hold('coding');
      const coding=(await fixture()).jobs.find(x=>x.kind==='coding_generate').id;
      assert.equal(await run(`$('newCoding').disabled`),false,'The page still waits for the whole task');
      await pauseInline(coding,'coding');
      await run(`openSet('${data.quiz}')`);await until(`$('set-${data.quiz}').querySelector('[data-answer]')`);
      await run(`$('set-${data.quiz}').querySelector('[data-answer]').value='可能存在共同原因；需要更多证据。';$('submitAnswers').click()`);await hold('quiz');
      const quiz=(await fixture()).jobs.find(x=>x.kind==='quiz_grade').id;await pauseInline(quiz,'quiz');
      assert.equal((await fixture()).submissions,0);
      assert.equal(await run(`api('/api/exercises/${data.quiz}').then(x=>'solutions' in x)`),false);
      await saveImage('习题任务暂停');
      await run(`showView('artifacts');refreshArtifacts()`);
      assert.equal(await run(`$('jobs').querySelectorAll('[data-generation-control][data-action="resume"]').length`),3);
      await saveImage('全部暂停任务');
      win.setContentSize(560,740);await run(`document.querySelector('[data-generation-status="paused"]').scrollIntoView({block:'start'})`);await saveImage('小窗口暂停按钮');
      assert.ok(await run(`document.body.scrollWidth<=window.innerWidth+2`));win.setContentSize(1440,950);
      await run(`$('artifactFolders').querySelector('[data-artifact-project="${data.projects[1].id}"]').click()`);
      await until(`state.project.id==='${data.projects[1].id}' && !state.projectLoading && !conversationUI.restoring`);
      assert.equal(await run(`$('jobs').querySelectorAll('[data-generation-control]').length`),0);
      await run(`$('artifactFolders').querySelector('[data-artifact-project="${data.projects[0].id}"]').click()`);
      await until(`state.project.id==='${data.projects[0].id}' && !state.projectLoading && !conversationUI.restoring`);
      await run('flushConversation()');fs.writeFileSync(statePath,JSON.stringify({read,coding,quiz}));
    }else{
      const saved=JSON.parse(fs.readFileSync(statePath,'utf8'));
      await until(`state.reading?.status==='paused'`);
      assert.deepEqual((await fixture()).calls,['read','coding','quiz'],'Reopen caused automatic model calls');
      await run(`showView('study');$('readingTaskControl').click()`);
      await until(`state.reading?.status==='completed'`);
      const reads=(await fixture()).calls.filter(x=>x==='read').length;assert.ok(reads>1);
      await run(`$('showKnowledge').click()`);await until(`$('knowledgeDialog').open && !$('buildKnowledge').disabled`);
      await run(`$('buildKnowledge').click()`);await hold('knowledge');
      await until(`!$('knowledgeTaskControl').hidden`);
      const knowledge=await run('knowledgeState.jobId');await run(`$('knowledgeTaskControl').click()`);
      await until(`api('/api/jobs/${knowledge}').then(x=>x.status==='pausing')`);
      await run(`api('/__pause_fixture/release/knowledge',{method:'POST'})`);
      await until(`$('knowledgeTaskControl').textContent==='继续整理'`);
      await run(`$('closeKnowledge').click();$('showKnowledge').click()`);
      await until(`!$('knowledgeTaskControl').hidden && $('knowledgeTaskControl').dataset.action==='resume'`);
      await run(`$('knowledgeTaskControl').click()`);
      await until(`api('/api/jobs/${knowledge}').then(x=>x.status==='completed')`);
      await until(`!$('knowledgeBody').hidden`);await saveImage('知识结构继续完成');
      await run(`$('closeKnowledge').click();showView('exercises');refreshArtifacts()`);
      await until(`document.querySelector('[data-task-control="${saved.coding}"][data-action="resume"]')`);
      await run(`document.querySelector('[data-task-control="${saved.coding}"]').click()`);
      await until(`api('/api/jobs/${saved.coding}').then(x=>x.status==='completed')`);
      await run(`document.querySelector('[data-task-control="${saved.quiz}"]').click()`);
      await until(`api('/api/jobs/${saved.quiz}').then(x=>x.status==='completed')`);
      await until(`$('set-${data.quiz}').textContent.includes('80')`);
      const final=await fixture();assert.equal(final.submissions,1);assert.equal(final.sets,2);assert.equal(final.maps,1);
      const documents=await run(`api('/__pause_fixture/check-documents')`);
      assert.equal(final.calls.filter(x=>x==='coding').length,4);assert.equal(final.calls.filter(x=>x==='quiz').length,2);
      await run(`showView('artifacts');refreshArtifacts()`);await until(`$('artifacts').textContent.includes('习题与解析')`);
      await saveImage('恢复后成果');win.setContentSize(560,740);await saveImage('小窗口任务');
      fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({ok:true,actualBackendRestart:true,
        readingParts:reads,modelCalls:final.calls,oneGrade:true,oneCodingAssignment:true,knowledgeResume:true,scopeIsolation:true,documents,errors},null,2));
    }
    assert.deepEqual(errors,[]);win.destroy();app.exit(0);
  }catch(failure){const ui=await run(`({reading:state.reading,knowledge:knowledgeState,knowledgeStatus:$('knowledgeStatus').textContent,jobs:[...taskUI.jobs.values()]})`).catch(()=>null);fs.writeFileSync(path.join(root,'failure-'+phase+'.json'),JSON.stringify({error:failure.stack,errors,ui},null,2));console.error(failure);win.destroy();app.exit(1);}
});
