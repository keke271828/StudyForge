const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_PARALLEL_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_PARALLEL_CASE);
const stored=path.join(root,'ui-state.json'),report=path.join(root,'result.json');
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let i=0;i<350;i++){if(await run(code))return;await sleep(80);}throw Error('Timeout: '+code);}
async function inspect(){return run(`api('/__parallel_test__/state')`);}
async function snapshot(name,view){
  if(view)assert.equal(await run('state.view'),view,'Capture must show the intended workspace');
  await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');await sleep(100);
  if(view)assert.ok(await run(`$('view-${view}').classList.contains('active')`));
  fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());
}
async function latestJob(before){await until(`(async()=>{return (await api('/__parallel_test__/state')).jobs.filter(j=>j.kind==='generate').length>${before};})()`);return (await inspect()).jobs.filter(j=>j.kind==='generate').at(-1).id;}
async function complete(id){await until(`(async()=>{const j=await api('/api/jobs/${id}');if(j.status==='failed')throw Error(j.error);return j.status==='completed';})()`);}
function overlap(a,b){return Math.max(a.start,b.start)<Math.min(a.end,b.end);}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1480,height:1000,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
    if(input.phase===1){
      await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.project}'),{conversationId:'${input.chat}'})`);
      assert.equal(await run('state.selected.size'),0);
      await run(`setSourceSelected('${input.sources[0]}',true);setSourceSelected('${input.sources[1]}',true);ensureReading()`);
      await until(`state.reading?.status==='completed'`);
      await run(`$('generationContent').value='both';$('generationContent').dispatchEvent(new Event('change'));$('generationParallel').checked=false;$('prompt').value='顺序验收甲';$('generate').click()`);
      const serial=await latestJob(0);await complete(serial);
      let calls=(await inspect()).calls.filter(c=>c.job_id===serial),chapters=calls.filter(c=>c.kind==='lecture'),worksheet=calls.find(c=>c.kind==='worksheet');
      assert.equal(chapters.length,2);assert.ok(chapters[1].start>=chapters[0].end,'Off: chapters must be sequential');
      assert.ok(worksheet.start>=Math.max(...calls.filter(c=>c.kind!=='worksheet').map(c=>c.end)),'Off: worksheet must follow lecture');
      await run(`showView('study');$('generationParallel').checked=true;$('generationParallel').dispatchEvent(new Event('change'));$('prompt').value='并行验收甲';$('generate').click()`);
      const parallel=await latestJob(1);
      await until(`!generationLaunches.has('${input.chat}')`);
      await until(`(async()=>{return (await api('/__parallel_test__/state')).calls.some(c=>c.job_id==='${parallel}'&&c.kind==='lecture'&&!c.end);})()`);
      assert.equal(await run(`$('sendMessage').disabled`),false,'A document must not disable chat');
      assert.equal(await run(`$('generate').disabled`),false,'A document must not disable independent generation');
      await snapshot('工作台并行开关与独立聊天','study');
      await run(`$('chatSourceMode').value='none';$('prompt').value='后加指令不改旧任务';$('sendMessage').click()`);
      await until(`isChatBusy('${input.chat}')`);
      await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.other}'),{conversationId:'${input.other_chat}'})`);
      assert.equal(await run('state.project.id'),input.other,'Switch while streaming must work');
      await run(`$('prompt').value='乙对话唯一问题';$('sendMessage').click()`);
      await until(`isChatBusy('${input.other_chat}')`);
      await until(`!isChatBusy('${input.chat}')&&!isChatBusy('${input.other_chat}')`);
      assert.equal(await run(`$('messages').textContent.includes('后加指令不改旧任务')`),false,'Foreign reply leaked into new chat');
      assert.equal(await run(`$('messages').textContent.includes('乙对话唯一问题')`),true);
      await complete(parallel);
      calls=(await inspect()).calls.filter(c=>c.job_id===parallel);chapters=calls.filter(c=>c.kind==='lecture');worksheet=calls.find(c=>c.kind==='worksheet');
      assert.equal(chapters.length,2);assert.ok(overlap(chapters[0],chapters[1]),'On: independent chapters must actually overlap');
      assert.ok(chapters.some(c=>overlap(c,worksheet)),'On: worksheet must actually overlap lecture');
      assert.ok(calls.every(c=>!c.later_instruction&&!c.foreign_marker),'Started job changed its dialogue snapshot');
      let info=await inspect();assert.ok(info.maximum<=2&&info.maximum===2,'Actual HTTP cap must be two');
      const otherArtifacts=info.artifacts.filter(a=>a.project_id===input.other);assert.equal(otherArtifacts.length,0,'Artifacts changed ownership');
      const savedSources=JSON.parse(info.conversations.find(c=>c.id===input.chat).source_ids_json);assert.deepEqual(savedSources.sort(),[...input.sources].sort(),'Unrelated chat removed source selection');
      await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.project}'),{conversationId:'${input.chat}'})`);
      assert.equal(await run(`$('messages').textContent.includes('后加指令不改旧任务')`),true);
      await run(`$('prompt').value='第三个独立成果';$('generate').click()`);const third=await latestJob(2);
      await run(`$('prompt').value='第四个独立成果';$('generate').click()`);const fourth=await latestJob(3);
      await until(`(async()=>{const x=await api('/api/scheduling?project_id=${input.project}');return x.resources.model.queued>0;})()`);
      await run(`changeTask('${fourth}','pause')`);
      await until(`(async()=>{return (await api('/api/jobs/${fourth}')).status==='paused';})()`);
      const fourthBefore=(await inspect()).calls.filter(c=>c.job_id===fourth).length;
      await run(`showView('artifacts');refreshArtifacts()`);await snapshot('并行任务与暂停队列','artifacts');
      await complete(third);await sleep(450);
      assert.equal((await inspect()).calls.filter(c=>c.job_id===fourth).length,fourthBefore,'Paused queued job started model work');
      await run(`changeTask('${fourth}','resume')`);await complete(fourth);
      const artifacts=(await inspect()).artifacts;
      for(const artifact of artifacts.filter(a=>a.kind==='exercise')){
        const detail=await run(`api('/api/exercises/'+${JSON.stringify(JSON.parse(artifact.metadata_json).exercise_set_id)})`);
        assert.ok(!JSON.stringify(detail).includes('私有答案验收标记'),'Private solution was published');
      }
      await run(`showView('settings');showSettingsSection('generation')`);
      await run(`(async()=>{
        const original=api,old=await original('/api/settings');let release;
        api=(url,options)=>url==='/api/settings'&&(!options||!options.method)?new Promise(resolve=>{release=()=>resolve(old);}):original(url,options);
        try{
          const stale=refreshSettings();
          $('taskParallelEnabled').checked=true;$('modelConcurrency').value='3';$('defaultGenerationParallel').checked=true;
          await saveSchedulingSettings();release();await stale;
        }finally{api=original;}
      })()`);
      await run(`refreshSchedulingStatus();$('executionTimeline').closest('details').open=true;$('taskParallelEnabled').closest('.scheduling-card').scrollIntoView({block:'start'})`);
      await snapshot('并发设置与真实时间记录','settings');
      assert.equal(await run(`$('modelConcurrency').value`),'3');
      assert.equal(await run(`state.settings.model_concurrency`),3);
      assert.ok(await run(`$('executionTimeline').children.length>0`));
      const spans=await run(`api('/api/scheduling?job_id=${parallel}')`);
      assert.ok(spans.spans.every(s=>s.started_at&&s.ended_at),'Completed model steps need actual time evidence');
      await run(`(async()=>{
        const original=schedulingSettingsSave;let release;
        schedulingSettingsSave=new Promise(resolve=>{release=resolve;});let finished=false;
        const exit=prepareDesktopExit().then(()=>{finished=true;});
        await new Promise(resolve=>setTimeout(resolve,50));if(finished)throw Error('Desktop exit skipped scheduling settings save');
        release();await exit;schedulingSettingsSave=original;
      })()`);
      fs.writeFileSync(stored,JSON.stringify({serial,parallel,third,fourth},null,2));
      fs.writeFileSync(report,JSON.stringify({phase1:true,serial_chapters_ordered:true,serial_worksheet_after_lecture:true,
        parallel_chapters_overlap:true,parallel_worksheet_overlap:true,http_maximum:info.maximum,
        switched_during_stream:true,frozen_job_context:true,source_selection_preserved:true,paused_queue_did_not_send:true,
        resumed_job_completed:true,answer_hidden:true,stale_settings_did_not_overwrite:true,artifacts:artifacts.length,errors},null,2));
    }else{
      const history=JSON.parse(fs.readFileSync(stored,'utf8')),info=await inspect();
      assert.equal(await run(`state.settings.model_concurrency`),3);
      assert.equal(await run(`$('generationParallel').checked`),true,'Internal parallel default did not survive restart');
      assert.equal(info.calls.length,JSON.parse(fs.readFileSync(path.join(root,'requests.json'),'utf8')).length);
      await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.project}'),{conversationId:'${input.chat}'})`);
      assert.equal(await run(`$('messages').textContent.includes('后加指令不改旧任务')`),true);
      await run(`showView('artifacts');refreshArtifacts()`);
      assert.ok(await run(`$('artifacts').children.length>=4`));
      await win.setSize(820,900);await snapshot('重启恢复并行任务成果','artifacts');
      const result=JSON.parse(fs.readFileSync(report,'utf8'));Object.assign(result,{phase2:true,restarted_preferences:true,restarted_chat_and_artifacts:true,errors:[...result.errors,...errors]});
      assert.deepEqual(result.errors,[]);fs.writeFileSync(report,JSON.stringify(result,null,2));
    }
    assert.deepEqual(errors,[]);app.exit(0);
  }catch(error){fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors},null,2));console.error(error);app.exit(1);}
});
