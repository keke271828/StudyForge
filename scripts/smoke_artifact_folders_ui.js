const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const casePath=process.env.STUDYFORGE_ARTIFACT_FOLDERS_CASE,root=path.dirname(casePath),data=JSON.parse(fs.readFileSync(casePath,'utf8'));
const phase=process.env.STUDYFORGE_ARTIFACT_FOLDERS_PHASE||'1',savedPath=path.join(root,'ui-state.json');
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let n=0;n<160;n++){if(await run(code))return;await sleep(100);}throw new Error('Timeout: '+code);}
async function snapshot(name){await sleep(200);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function openFolder(index){
  const project=data.projects[index];
  await run(`$('artifactFolders').querySelector('[data-artifact-project="${project.id}"]').click()`);
  await until(`state.project?.id==='${project.id}' && !state.projectLoading && !conversationUI.restoring`);
  assert.equal(await run(`$('artifactFolderTitle').textContent`),project.name);
  assert.equal(await run(`$('artifactFolders').querySelector('[aria-current="page"]').dataset.artifactProject`),project.id);
  assert.equal(await run('state.view'),'artifacts');
}
async function fileIds(){return run(`[...$('artifacts').querySelectorAll('[data-artifact]')].map(row=>row.dataset.artifact).sort()`);}
async function count(index){return run(`Number($('artifactFolders').querySelector('[data-artifact-project="${data.projects[index].id}"] [data-folder-artifact-count]').textContent)`);}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1480,height:960,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(data.url);await until('state.ready && state.conversation && !conversationUI.restoring && state.deepseekCatalog');
    await run(`showView('artifacts');refreshArtifacts()`);
    assert.equal(await run(`$('artifactFolders').querySelectorAll('[data-artifact-project]').length`),3);
    assert.equal(await run(`$('artifactFolders').querySelector('img')!==null`),false);
    if(phase==='1'){
      assert.deepEqual(await fileIds(),data.files.slice(0,2).map(row=>row.id).sort());
      assert.equal(await count(0),2);assert.equal(await count(1),1);assert.equal(await count(2),0);
      assert.ok(await run(`document.querySelector('[data-artifact="${data.files[0].id}"]').textContent.includes('来源对话：哲学与社会科学对话')`));
      await run(`document.querySelector('[data-origin-conversation="${data.chats[0]}"]').click()`);
      await until(`state.view==='study' && state.conversation==='${data.chats[0]}' && !conversationUI.restoring`);
      await run(`showView('artifacts');refreshArtifacts()`);
      await snapshot('成果项目文件夹');
      await openFolder(1);assert.deepEqual(await fileIds(),[data.files[2].id]);
      await run(`$('artifactFolderSearch').value='哲学';$('artifactFolderSearch').dispatchEvent(new Event('input'))`);
      assert.equal(await run(`$('artifactFolders').querySelectorAll('[data-artifact-project]').length`),1);
      assert.equal(await run('state.project.id'),data.projects[1].id);
      await run(`$('artifactFolderSearch').value='没有这个项目';$('artifactFolderSearch').dispatchEvent(new Event('input'))`);
      assert.ok(await run(`$('artifactFolders').textContent.includes('没有匹配')`));
      await run(`$('artifactFolderSearch').value='';$('artifactFolderSearch').dispatchEvent(new Event('input'))`);
      await openFolder(2);assert.deepEqual(await fileIds(),[]);
      assert.ok(await run(`$('artifacts').textContent.includes('这个项目还没有成果')`));
      await openFolder(0);
      await run(`$('prompt').value='成果文件夹切换前的学习草稿';$('prompt').dispatchEvent(new Event('input'));flushConversation()`);
      // Delay an old response, leave and re-enter the same project, then release it.
      // The old response must not replace the newly renamed file's current title.
      await run(`clearInterval(artifactsPoller);artifactsPoller=null;window.__nativeFolderFetch=window.fetch;window.__holdOnce=true;window.fetch=async(...args)=>{const response=await window.__nativeFolderFetch(...args);if(window.__holdOnce && String(args[0]).includes('/api/projects/${data.projects[0].id}/artifacts?')){window.__holdOnce=false;window.__held=true;await new Promise(resolve=>window.__releaseFolder=resolve);}return response;};$('artifactSort').value='oldest';$('artifactSort').dispatchEvent(new Event('change'))`);
      await until('window.__held');await openFolder(1);
      await run(`api('/api/artifacts/${data.files[0].id}',jsonOptions('PUT',{name:'已更新的概念定义'}))`);
      await openFolder(0);
      assert.ok(await run(`$('artifacts').textContent.includes('已更新的概念定义')`));
      await run(`window.__releaseFolder()`);await until('artifactsRefreshing.size===0');
      assert.ok(await run(`$('artifacts').textContent.includes('已更新的概念定义')`),'Old project response replaced the renamed file');
      assert.equal(await run(`$('prompt').value`),'成果文件夹切换前的学习草稿');
      await run(`window.fetch=window.__nativeFolderFetch;showView('artifacts')`);
      // Sorting stays inside this project.
      await run(`$('artifactSort').value='name';$('artifactSort').dispatchEvent(new Event('change'));refreshArtifacts()`);
      assert.deepEqual(await run(`[...$('artifacts').querySelectorAll('[data-artifact]')].map(row=>row.dataset.artifact)`),await run(`(async()=>{return (await api('/api/projects/${data.projects[0].id}/artifacts?sort=name')).map(row=>row.id);})()`));
      // Keep B open while a new A outcome appears; only the folder count changes.
      await openFolder(1);
      const extra=await run(`api('/__folder_fixture/file?project_id=${data.projects[0].id}&title='+encodeURIComponent('后台新成果'),{method:'POST'})`);
      await until(`Number($('artifactFolders').querySelector('[data-artifact-project="${data.projects[0].id}"] [data-folder-artifact-count]').textContent)===3`);
      assert.deepEqual(await fileIds(),[data.files[2].id]);
      const task=await run(`api('/__folder_fixture/task?project_id=${data.projects[1].id}',{method:'POST'});`);
      await until(`$('jobs').textContent.includes('已暂停') && $('artifactFolderSummary').textContent.includes('1 项未完成')`);
      await openFolder(0);assert.equal(await run(`$('jobs').querySelectorAll('.job-card').length`),0);
      await run(`document.querySelector('[data-rename-artifact="${extra.id}"]').click();const form=document.querySelector('[data-artifact-rename-form="${extra.id}"]');form.querySelector('input').value='成果页内重命名';form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));`);
      await until(`$('artifacts').textContent.includes('成果页内重命名')`);
      assert.ok(await run(`document.querySelector('[data-artifact="${extra.id}"] a[download]').getAttribute('download').includes('成果页内重命名')`));
      await run(`document.querySelector('[data-delete-artifact="${extra.id}"]').click();document.querySelector('[data-delete-artifact="${extra.id}"]').click()`);
      await until(`!document.querySelector('[data-artifact="${extra.id}"]') && Number($('artifactFolders').querySelector('[data-artifact-project="${data.projects[0].id}"] [data-folder-artifact-count]').textContent)===2`);
      await openFolder(1);assert.deepEqual(await fileIds(),[data.files[2].id]);
      await run(`document.querySelector('[data-delete-job="${task.id}"]').click();document.querySelector('[data-delete-job="${task.id}"]').click()`);
      await until(`!document.querySelector('[data-delete-job="${task.id}"]') && !$('artifactFolderSummary').textContent.includes('未完成')`);
      assert.equal(await run(`(async()=>{return (await api('/api/jobs/${task.id}')).status;})()`),'cancelled');
      await run('prepareDesktopExit()');fs.writeFileSync(savedPath,JSON.stringify({lastProject:data.projects[1].id}));
    }else{
      const saved=JSON.parse(fs.readFileSync(savedPath,'utf8'));
      assert.equal(await run('state.project.id'),saved.lastProject);assert.deepEqual(await fileIds(),[data.files[2].id]);
      await openFolder(0);assert.equal(await run(`$('prompt').value`),'成果文件夹切换前的学习草稿');
      await snapshot('成果文件夹重启恢复');
      win.setSize(1060,820);await snapshot('成果文件夹小窗口');
      assert.ok(await run('document.documentElement.scrollWidth<=innerWidth+2'));
      win.setSize(560,720);await snapshot('成果文件夹窄窗口');
      assert.ok(await run('document.documentElement.scrollWidth<=innerWidth+2'));
      assert.equal(await run(`getComputedStyle(document.querySelector('.artifact-library')).gridTemplateColumns.split(' ').length`),1);
      assert.equal((await run(`api('/__folder_fixture/stats')`)).calls,0);
      win.setSize(1480,960);await run(`showView('study')`);
      await run(`$('generationContent').value='exercises';$('generationContent').dispatchEvent(new Event('change'));$('prompt').value='请只出一道因果推断题，不要答案。';$('prompt').dispatchEvent(new Event('input'))`);
      assert.equal(await run(`$('outputFormat').disabled`),true);
      assert.equal(await run(`$('exerciseFormatWrap').hidden`),false);
      await snapshot('只出题生成选项');
      await run(`$('generate').click()`);
      await until(`!state.busy && (async()=>{const jobs=await api('/api/projects/${data.projects[0].id}/jobs');return jobs.some(x=>x.kind==='generate'&&x.only_exercises&&x.status==='completed');})()`);
      const quiz=await run(`(async()=>{const rows=await api('/api/projects/${data.projects[0].id}/artifacts');return rows.find(x=>x.kind==='exercise');})()`);
      assert.equal(quiz.format,'docx');assert.equal(quiz.origin.conversation_id,data.chats[0]);
      assert.equal(await run(`(async()=>{return (await api('/api/projects/${data.projects[0].id}/artifacts')).filter(x=>x.kind==='explanation').length;})()`),2);
      assert.ok(!await run(`$('messages').textContent.includes('PRIVATE_SOLUTION')`));
      await run(`showView('study');$('prompt').value='请给我这道题的答案与解析';$('prompt').dispatchEvent(new Event('input'));$('sendMessage').click()`);
      await until(`!state.busy && $('messages').textContent.includes('答案和解析暂不开放')`);
      const stats=await run(`api('/__folder_fixture/stats')`);assert.equal(stats.calls,5);assert.equal(stats.lecture_calls,0);
      await run(`showView('artifacts');$('showJobHistory').checked=true;$('showJobHistory').dispatchEvent(new Event('change'));refreshArtifacts()`);
      await until(`$('jobs').querySelector('[data-generation-status="completed"]')!==null`);
      const finishedJob=await run(`(async()=>{return (await api('/api/projects/${data.projects[0].id}/jobs')).find(x=>x.only_exercises).id;})()`);
      assert.equal(await run(`$('jobs').querySelector('[data-generation-status="completed"] [data-generation-control]')!==null`),false);
      await run(`document.querySelector('[data-delete-job="${finishedJob}"]').click();document.querySelector('[data-delete-job="${finishedJob}"]').click()`);
      await until(`!document.querySelector('[data-delete-job="${finishedJob}"]')`);
      assert.ok(await run(`document.querySelector('[data-artifact="${quiz.id}"]')!==null`));
      await run(`$('deleteConversation').click();$('deleteConversation').click()`);
      await until(`state.conversation!=='${data.chats[0]}' && !conversationUI.restoring`);
      await run(`refreshArtifacts()`);
      assert.ok(await run(`$('artifacts').textContent.includes('哲学与社会科学对话（已删除）')`));
      await snapshot('来源对话已删除成果保留');
      assert.deepEqual(errors,[]);
      fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({success:true,folders_inside_outputs:true,counts_follow_updates:true,project_files_and_tasks_isolated:true,folder_search:true,empty_folder:true,sort_rename_download_delete:true,old_response_dropped:true,chat_draft_preserved:true,actual_backend_restart:true,narrow_layout:true,source_chat_label_and_link:true,deleted_chat_origin_preserved:true,cancel_pending_task:true,delete_finished_record_keeps_files:true,only_exercises_skips_lecture:true,private_answers_hidden:true,json_repair:true,mock_model_calls:stats.calls,no_real_model_calls:true},null,2));
    }
    assert.deepEqual(errors,[]);app.exit(0);
  }catch(error){await snapshot('failure-'+phase);console.error(error);fs.writeFileSync(path.join(root,'failure-'+phase+'.txt'),error.stack+'\n'+errors.join('\n'));app.exit(1);}
});
