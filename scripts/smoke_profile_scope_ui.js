const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_PROFILE_SCOPE_CASE,root=path.dirname(casePath),data=JSON.parse(fs.readFileSync(casePath,'utf8'));
const phase=process.env.STUDYFORGE_PROFILE_SCOPE_PHASE||'1';
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let i=0;i<400;i++){if(await run(code))return;await sleep(100);}throw new Error('Timeout: '+code);}
async function stats(){return run(`api('/__profile_scope/stats')`);}
async function send(text){
  const before=(await stats()).requests.length;
  await run(`$('prompt').value=${JSON.stringify(text)};$('prompt').dispatchEvent(new Event('input'));$('sendMessage').click()`);
  await until(`!state.busy && (async()=>{return (await api('/__profile_scope/stats')).requests.length>${before};})()`);
}
async function project(index,chat){
  await run(`(async()=>{await selectProject(${JSON.stringify(data.projects[index])});await selectConversation('${chat.id}');})()`);
  await until(`!state.projectLoading && !conversationUI.restoring && state.conversation==='${chat.id}'`);
}
async function screenshot(name){fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1440,height:960,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(data.url);await until('state.ready && state.conversation && !conversationUI.restoring && state.deepseekCatalog');
    if(phase==='1'){
      assert.equal(await run('state.conversation'),data.chats[1].id);
      await send('我的用户画像是什么？');
      assert.ok(await run(`$('messages').textContent.includes('做题79分') && $('messages').textContent.includes('费曼讲解86分')`));
      let evidence=await stats();assert.equal(evidence.events,3);assert.ok(evidence.requests[0].profile_tool);
      assert.equal(evidence.requests[0].a1,false);assert.equal(evidence.requests[0].b1,false);assert.equal(evidence.requests[0].a2,true);
      assert.ok(evidence.requests.every(x=>!x.raw_quote&&!x.legacy));
      await send('为什么删除按钮没有反应？');assert.equal((await stats()).events,3);
      await send('读取别的对话文件');assert.ok(await run(`$('messages').textContent.includes('访问被拒绝')`));
      assert.ok((await stats()).requests.every(x=>!x.foreign_content));
      await screenshot('画像可见与对话隔离');
      await project(1,data.chats[2]);await send('查看我的学习画像');
      const latest=(await stats()).requests.at(-1);assert.equal(latest.a1,false);assert.equal(latest.a2,false);assert.equal(latest.b1,true);
      assert.ok(await run(`$('messages').textContent.includes('做题79分') && !$('messages').textContent.includes('CHAT_A2_ONLY')`));
      await screenshot('跨项目画像与独立聊天');
      await run('prepareDesktopExit()');
      fs.writeFileSync(path.join(root,'phase-1.json'),JSON.stringify({requests:(await stats()).requests.length},null,2));
    }else{
      assert.equal(await run('state.conversation'),data.chats[2].id);
      assert.ok(await run(`$('messages').textContent.includes('做题79分') && !$('messages').textContent.includes('CHAT_A2_ONLY')`));
      await send('我的用户画像是什么？');assert.ok((await stats()).requests.every(x=>!x.raw_quote&&!x.legacy&&!x.a2&&!x.a1));
      await project(0,data.chats[1]);
      assert.ok(await run(`$('messages').textContent.includes('访问被拒绝') && !$('messages').textContent.includes('CHAT_B1_ONLY')`));
      await run(`(async()=>{state.selected.add('${data.source}');await flushConversation();renderQuickSources();await applyReviewMode('fast');})()`);
      await run(`$('generationContent').value='both';$('generationContent').dispatchEvent(new Event('change'));$('prompt').value='讲解相关与因果，再出一道题，不要答案。';$('prompt').dispatchEvent(new Event('input'));$('generate').click()`);
      await until(`(async()=>{return (await api('/api/projects/${data.projects[0].id}/jobs')).some(x=>x.kind==='generate'&&['completed','failed'].includes(x.status));})()`);
      const jobs=await run(`api('/api/projects/${data.projects[0].id}/jobs')`);
      const task=jobs.find(x=>x.kind==='generate');assert.equal(task.status,'completed',task.error);
      const files=await run(`api('/__profile_scope/files')`);assert.equal(files.length,2);assert.ok(files.every(x=>x.opens&&x.answer_hidden));
      const evidence=await stats();assert.ok(evidence.quiz_repaired&&evidence.audit_format_repaired);
      await run(`showView('artifacts');refreshArtifacts()`);
      await until(`$('artifacts').querySelectorAll('[data-artifact]').length===2`);
      assert.ok(!await run(`$('messages').textContent.includes('PRIVATE_SOLUTION_NOT_PUBLISHED')`));
      await screenshot('讲解与习题修订后交付');
      await run(`showView('profile')`);await until(`$('learningMemory').textContent.includes('辅助函数')`);
      assert.ok(await run(`$('learningMemory').textContent.includes('辅助函数') && !$('learningMemory').textContent.includes('删除按钮')`));
      await screenshot('仅知识学习进入画像');
      assert.deepEqual(errors,[]);
      fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({success:true,actual_backend_restart:true,profile_tool_used:true,
        global_profile_with_quiz_and_feynman:true,same_project_chats_isolated:true,projects_isolated:true,foreign_files_denied:true,
        legacy_unscoped_cache_discarded:true,raw_evidence_not_forwarded:true,unrelated_chat_not_recorded:true,
        lecture_json_repaired:true,exercise_revision_rechecked:true,docx_files_opened:files.length,answers_hidden:true,
        real_model_calls:0,mock_model_calls_phase2:evidence.requests.length},null,2));
    }
    assert.deepEqual(errors,[]);app.exit(0);
  }catch(error){await screenshot('failure-'+phase);console.error(error);fs.writeFileSync(path.join(root,'failure-'+phase+'.txt'),error.stack+'\n'+errors.join('\n'));app.exit(1);}
});
