const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const casePath=process.env.STUDYFORGE_FEEDBACK_UI_CASE_PATH,input=JSON.parse(fs.readFileSync(casePath,'utf8')),root=path.dirname(casePath);
app.setPath('userData',path.join(root,'electron-formats'));app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
  const win=new BrowserWindow({show:false,width:1440,height:1150,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,offscreen:true,backgroundThrottling:false}});
  const errors=[],calls=()=>JSON.parse(fs.readFileSync(path.join(root,'cloud_requests.json'),'utf8')).requests;
  win.webContents.on('console-message',(_event,level,text)=>{if(level===3&&!text.includes('404'))errors.push(text);});
  const run=code=>win.webContents.executeJavaScript(`(async()=>{
    const input=${JSON.stringify(input)};
    const wait=async predicate=>{for(let i=0;i<180;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw new Error('UI wait timed out');};
    ${code}
  })()`);
  try{
    await win.loadURL(input.url);
    await run(`await wait(()=>state.project?.id===input.project_id&&state.settings&&state.sources.length);await refreshStudyModels();await openLessonFeedback(input.submit_id);`);
    const before=calls();
    const result=await run(`
      const cid=state.conversation,rows=[];
      for(const format of ['apkg','pptx','zip','ipynb']){
        showView('chat');$('outputFormat').value=format;$('withExercises').checked=false;$('prompt').value='使用当前资料和要求；代码包请用JavaScript。';
        const previous=new Set((await api('/api/projects/'+input.project_id+'/jobs')).map(x=>x.id));$('generate').click();let job;
        await wait(async()=>{job=(await api('/api/projects/'+input.project_id+'/jobs')).find(x=>!previous.has(x.id)&&x.kind==='generate');return job&&['failed','completed'].includes(job.status)&&!state.busy;});
        if(job.status!=='completed')throw new Error(format+': '+job.error);
        const artifacts=await api('/api/projects/'+input.project_id+'/artifacts'),artifact=artifacts.find(x=>x.metadata?.generation_job_id===job.id);
        if(!artifact||artifact.format!==format||artifact.metadata.conversation_id!==cid)throw new Error('Format or mentor changed');
        const delivery=artifact.metadata.delivery;
        if(delivery.executed||delivery.format_model_requests!==(['apkg','zip'].includes(format)?1:0))throw new Error('Fabricated execution or request count');
        const response=await fetch('/api/artifacts/'+artifact.id+'/download'),bytes=new Uint8Array(await response.arrayBuffer());
        if(!response.ok||bytes.length<100)throw new Error('Download failed');
        rows.push({format,downloaded:true,executed:false,format_model_requests:delivery.format_model_requests});
      }
      if((await api('/api/projects/'+input.project_id+'/exercises')).length)throw new Error('Unexpected exercises');
      showView('artifacts');await wait(()=>$('artifacts').querySelectorAll('.delivery-check').length===6);
      for(const panel of $('artifacts').querySelectorAll('.delivery-check')){panel.open=true;if(panel.scrollWidth>panel.clientWidth+2)throw new Error('Panel overflow');}
      if(!$('artifacts').textContent.includes('JavaScript语法通过')||!$('artifacts').textContent.includes('代码单元未执行'))throw new Error('Validation status missing');
      return {rows,same_tutor:true,no_extra_artifacts:(await api('/api/projects/'+input.project_id+'/artifacts')).length===6,no_exercises:true,status_visible:true,no_overflow:true};
    `);
    const screenshot=path.join(root,'多格式成果验证.png');fs.writeFileSync(screenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    if(errors.length)throw new Error(errors.join('; '));
    console.log(JSON.stringify({ok:true,result,generation_cloud_requests:calls()-before,screenshot,console_errors:errors}));
    win.destroy();app.quit();
  }catch(error){console.error(error);try{console.error(await run(`return JSON.stringify({toast:$('toast').textContent,jobs:await api('/api/projects/'+state.project.id+'/jobs')});`));}catch(_){}win.destroy();app.exit(1);}
});
