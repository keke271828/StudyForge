const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const casePath=process.env.STUDYFORGE_FEEDBACK_UI_CASE_PATH,input=JSON.parse(fs.readFileSync(casePath,'utf8')),root=path.dirname(casePath);
app.setPath('userData',path.join(root,'electron-quality'));app.disableHardwareAcceleration();
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
    await run(`await wait(()=>state.project?.id===input.project_id&&state.settings&&state.sources.length);await refreshStudyModels();await ensureReading();`);
    let before=calls();
    const metadata=await run(`
      showView('artifacts');await wait(()=>$('artifacts').querySelectorAll('.lesson-quality').length===2);
      const artifacts=await api('/api/projects/'+input.project_id+'/artifacts');
      if(artifacts.some(x=>x.kind==='explanation'&&x.metadata.lesson_quality.warning_count))throw new Error('真实引句被误标');
      const panel=$('artifacts').querySelector('.lesson-quality');panel.open=true;
      if(!panel.textContent.includes('解析复用1份')||!panel.textContent.includes('不证明论断'))throw new Error('缓存或核对范围说明缺失');
      if(panel.scrollWidth>panel.clientWidth+2)throw new Error('质量面板溢出');
      return {cache_visible:true,valid_quote:true,scope_visible:true,no_overflow:true};
    `);
    const controls=calls()-before;before=calls();
    const result=await run(`
      await openLessonFeedback(input.submit_id);const cid=state.conversation;
      const old=(await api('/api/projects/'+input.project_id+'/jobs')).map(x=>x.id);
      $('prompt').value='请生成界面核对样例';$('withExercises').checked=false;$('generate').click();let job;
      await wait(async()=>{job=(await api('/api/projects/'+input.project_id+'/jobs')).find(x=>x.kind==='generate'&&!old.includes(x.id));return job?.status==='completed'&&!state.busy;});
      showView('artifacts');await wait(()=>$('artifacts').querySelectorAll('.lesson-quality').length===3);
      const artifacts=await api('/api/projects/'+input.project_id+'/artifacts');
      const bad=artifacts.find(x=>x.metadata?.generation_job_id===job.id);
      if(bad.metadata.lesson_quality.warning_count!==1||bad.metadata.lesson_quality.matched_quotes!==0||bad.metadata.lesson_quality.extra_model_requests!==0)throw new Error('错误引句未标注或增加模型核查');
      if(state.conversation!==cid||(await api('/api/projects/'+input.project_id+'/exercises')).length)throw new Error('换了导师或自动出题');
      const card=[...$('artifacts').children].find(x=>x.textContent.includes('1项待核对'));
      card.querySelector('.lesson-quality').open=true;card.scrollIntoView({block:'center',behavior:'instant'});await new Promise(r=>setTimeout(r,180));
      const response=await fetch('/api/artifacts/'+bad.id+'/download'),bytes=new Uint8Array(await response.arrayBuffer());
      if(!response.ok||bytes[0]!==80||bytes[1]!==75||!response.headers.get('content-disposition')?.includes('.docx'))throw new Error('DOCX不可下载');
      return {wrong_quote_flagged:true,same_tutor:true,no_exercises:true,only_requested_docx:artifacts.every(x=>x.format==='docx'),docx_downloaded:true,document_id:bad.id};
    `);
    const screenshot=path.join(root,'讲解来源核对.png');fs.writeFileSync(screenshot,(await win.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG());
    if(errors.length)throw new Error(errors.join('; '));
    console.log(JSON.stringify({ok:true,metadata,result,controls_cloud_requests:controls,generation_cloud_requests:calls()-before,screenshot,console_errors:errors}));
    win.destroy();app.quit();
  }catch(error){
    console.error(error);try{console.error(await run(`return JSON.stringify({toast:$('toast').textContent,busy:state.busy,artifacts:$('artifacts').textContent.slice(-1800),jobs:await api('/api/projects/'+state.project.id+'/jobs')});`));}catch(_){ }
    win.destroy();app.exit(1);
  }
});
