// Uses real Electron windows, native Tray/Menu and an isolated fake-model backend.
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

exports.run=async function({app,window:win,lifecycle,backend,url,report,ownerToken}){
  const request=async(resource,method='GET')=>{
    const response=await fetch(url+resource,{method,headers:{'X-StudyForge-Desktop-Token':ownerToken},signal:AbortSignal.timeout(3500)});
    if(!response.ok)throw new Error(resource+': '+response.status+' '+await response.text());
    return response.json();
  };
  async function until(check,label){
    for(let i=0;i<160;i++){const value=await check();if(value)return value;await delay(100);}
    throw new Error('Native tray check timed out: '+label);
  }
  async function jobAt(id,status){
    return until(async()=>{const row=await request('/api/jobs/'+id);
      if(row.status==='failed')throw new Error(row.error);return row.status===status?row:null;},status);
  }
  await until(()=>win.webContents.executeJavaScript('Boolean(state.ready && state.settings && state.project && state.conversation && !conversationUI.restoring && !state.projectLoading)'), 'UI and conversation initialized');
  await win.webContents.executeJavaScript('clearTimeout(readingTimer); state.selected.clear(); renderReadingStatus();');
  await win.webContents.executeJavaScript("(async()=>{showView('settings');await refreshDesktopControls();})()");
  await until(()=>win.webContents.executeJavaScript('Boolean(document.getElementById("desktopControls") && !document.getElementById("desktopControls").hidden)'), 'desktop controls');
  const first=await request('/qa/tray/info');assert.equal(first.child_containment,true);
  const outcome={ok:true,phase:first.phase,url,desktop_pid:process.pid,backend_pid:backend.pid,child_pid:first.child_pid,
    native_tray_registered:Boolean(lifecycle.tray&&!lifecycle.tray.isDestroyed()),child_containment:true};
  assert.equal(outcome.native_tray_registered,true);
  if(first.phase===1){
    const windowId=win.id;
    await win.webContents.executeJavaScript(`$('prompt').value='托盘验收：未发送的要求与草稿';message('user','托盘验收：保留当前聊天画面');`);
    win.show();await delay(100);
    // Start-Process -WindowStyle Hidden supplies SW_HIDE for the first native show.
    // Consume that startup state before testing subsequent real hide/show events.
    if(!win.isVisible()){win.hide();win.show();}
    await until(()=>win.isVisible(),'initial show');win.close();await delay(200);
    assert.equal(win.isDestroyed(),false);assert.equal(win.isVisible(),false);
    assert.equal((await request('/api/health')).ok,true);outcome.close_hides_only=true;
    const hiddenJob=(await request('/qa/tray/start/hidden','POST')).job_id;
    const completed=await jobAt(hiddenJob,'completed');assert.equal(completed.progress,100);
    assert.equal(win.isVisible(),false);assert.equal(completed.result.artifacts.length,1);
    outcome.generated_while_hidden=true;
    await lifecycle.poll();lifecycle.tray.emit('click');
    await until(()=>win.isVisible(),'tray opens');assert.equal(win.id,windowId);
    const draft=await win.webContents.executeJavaScript(`({draft:$('prompt').value,chat:$('messages').textContent})`);
    assert.equal(draft.draft,'托盘验收：未发送的要求与草稿');assert.match(draft.chat,/保留当前聊天画面/);
    outcome.same_window_draft_and_chat=true;
    lifecycle.menu.getMenuItemById('progress').click();
    await until(()=>win.webContents.executeJavaScript(`state.view==='artifacts' && $('artifacts').textContent.includes('因果推断入门')`),'visible results');
    outcome.tray_progress_opens_results=true;
    await win.webContents.executeJavaScript(`showView('settings');$('hideDesktop').click();`);
    await until(()=>!win.isVisible(),'settings hide');outcome.settings_hide=true;
    const second=spawn(process.execPath,[path.resolve(__dirname,'..')],{cwd:path.resolve(__dirname,'..'),
      env:process.env,windowsHide:true,stdio:'ignore'});
    try{
      await until(()=>win.isVisible(),'second launch restores');
      await until(()=>second.exitCode!==null,'second instance exits');
    }finally{if(second.exitCode===null)second.kill();}
    assert.equal(win.id,windowId);assert.equal((await request('/qa/tray/info')).backend_pid,backend.pid);
    assert.equal(await win.webContents.executeJavaScript(`$('prompt').value`),'托盘验收：未发送的要求与草稿');
    outcome.second_launch_restores_same_window=true;
    const resumeJob=(await request('/qa/tray/start/resume','POST')).job_id;
    await until(async()=>{const info=await request('/qa/tray/info');return info.calls.some(x=>x.job_id===resumeJob&&x.kind==='exercise');},'unfinished exercise request');
    const partial=await request('/api/jobs/'+resumeJob);assert.equal(partial.status,'running');assert.equal(partial.progress,85);
    const info=await request('/qa/tray/info');
    const partialArtifact=info.artifacts.filter(x=>x.metadata.generation_job_id===resumeJob);
    assert.equal(partialArtifact.length,1);outcome.partial_artifact_id=partialArtifact[0].id;
    outcome.saved_steps_before_exit=(await request('/qa/tray/steps/'+resumeJob)).count;
    assert.ok(outcome.saved_steps_before_exit>=3);
    await lifecycle.poll();assert.match(lifecycle.menu.getMenuItemById('status').label,/1 项任务运行中/);
    outcome.tray_shows_running_task=true;outcome.hidden_job=hiddenJob;outcome.resume_job=resumeJob;
    fs.writeFileSync(report,JSON.stringify(outcome,null,2));
    lifecycle.menu.getMenuItemById('exit').click(); // Real native menu's Exit handler.
  }else{
    const paused=await request('/api/jobs/'+first.resume_job);
    assert.equal(paused.status,'paused');assert.equal(paused.progress,85);
    assert.equal(paused.payload.model,'tray-test-model');assert.equal(paused.payload.learning_mode,'overview');
    assert.equal(paused.payload.summary_level,2);assert.match(paused.payload.instructions,/保持原来的讲解要求/);
    assert.equal(first.calls.length,0);outcome.restart_requires_explicit_resume=true;
    await win.webContents.executeJavaScript(`(async()=>{showView('artifacts');await refreshArtifacts();})()`);
    // Click the regular UI resume button, through its production event handler.
    await until(()=>win.webContents.executeJavaScript(`Boolean(document.querySelector('[data-generation-control="${first.resume_job}"][data-action="resume"]'))`),'resume control');
    await win.webContents.executeJavaScript(`document.querySelector('[data-generation-control="${first.resume_job}"][data-action="resume"]').click();`);
    const completed=await jobAt(first.resume_job,'completed');assert.equal(completed.result.artifacts.length,2);
    const info=await request('/qa/tray/info'),calls=info.calls.filter(x=>x.job_id===first.resume_job);
    assert.deepEqual(calls.map(x=>x.kind),['exercise']);
    const explanations=info.artifacts.filter(x=>x.metadata.generation_job_id===first.resume_job&&x.kind==='explanation');
    assert.equal(explanations.length,1);
    outcome.restored_artifact_id=explanations[0].id;outcome.saved_lecture_reused=true;
    outcome.exercise_docx_separate=completed.result.artifacts.some(x=>x.kind==='exercise'&&x.format==='docx');
    assert.equal(outcome.exercise_docx_separate,true);
    await win.webContents.executeJavaScript(`(async()=>{showView('settings');await refreshDesktopControls();})()`);
    fs.writeFileSync(report,JSON.stringify(outcome,null,2));
    await win.webContents.executeJavaScript(`$('quitDesktop').click();`); // Real renderer -> preload -> main IPC.
  }
};
