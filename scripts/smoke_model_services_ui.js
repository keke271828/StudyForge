const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_PERMISSION_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_PERMISSION_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],checks={},sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(code){try{return await win.webContents.executeJavaScript(`(async()=>{return (${code});})()`,true);}catch(error){throw Error(error.message+'\nCode: '+code);}}
async function until(code){for(let n=0;n<350;n++){if(await run(`Boolean(${code})`))return;await sleep(50);}throw Error('Timeout: '+code);}
async function click(selector){await run(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});el.scrollIntoView({block:'center'});return true;})()`);await sleep(180);const point=await run(`(()=>{const el=document.querySelector(${JSON.stringify(selector)}),r=el.getBoundingClientRect(),x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2);if(!el.contains(document.elementFromPoint(x,y)))throw Error('button covered '+${JSON.stringify(selector)});return{x,y};})()`);win.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});await sleep(25);win.webContents.sendInputEvent({type:'mouseUp',...point,button:'left',clickCount:1});await sleep(120);}
async function snapshot(name){win.webContents.invalidate();await sleep(180);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function data(){return run(`api('/__model_service_test__/state')`);}
async function fill(fields){await run(`(()=>{const fields=${JSON.stringify(fields)};for(const [id,value] of Object.entries(fields))$(id).value=value;return true;})()`);}
async function send(text){await fill({prompt:text});await click('#sendMessage');await until('!isChatBusy()');}
async function add(protocol){
  await click(protocol==='gemini'?'#addGeminiService':'#addCompatibleService');
  await fill({serviceName:protocol==='gemini'?'我的 Gemini':'自选兼容服务',serviceBase:protocol==='gemini'?'https://fixture.example/v1beta':'https://fixture.example/v1',serviceDefaultModel:protocol==='gemini'?'gemini-fixture-flash':'alpha-model',serviceModels:protocol==='gemini'?'gemini-fixture-pro':'beta-model',serviceKey:'fixture-ui-key'});
  await click('#saveService');await until(`!serviceFormBusy&&state.modelServices.some(row=>row.protocol===${JSON.stringify(protocol)})`);
  assert.equal(await run(`$('serviceKey').value`),'');assert.equal(await run(`$('serviceList').textContent.includes('fixture-ui-key')`),false);
  return run(`state.modelServices.find(row=>row.protocol===${JSON.stringify(protocol)}).id`);
}
app.whenReady().then(async()=>{
  try{
    win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
    win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring');
    await click('#manageModelServices');await until(`!$('serviceEditor').hidden&&studioSettingsSection==='models'`);
    const compatible=await add('openai');await snapshot('第三方服务管理');
    await click('#useService');await until(`$('provider').value===${JSON.stringify(compatible)}&&$('studyModel').querySelector('option[value="beta-model"]')`);
    await run(`(()=>{$('studyModel').value='beta-model';$('studyModel').dispatchEvent(new Event('change'));return true;})()`);
    await run('modelPreferenceSave');await run('flushConversation()');assert.equal(await run('currentModel()'),'beta-model');
    await send('请解释共同原因。');assert.equal((await data()).requests.at(-1).model,'beta-model');checks.compatible_model_actually_used=true;
    await snapshot('工作台选择第三方模型');
    await win.reload();await until(`state.ready&&!conversationUI.restoring&&$('provider').value===${JSON.stringify(compatible)}&&currentModel()==='beta-model'`);checks.restart_restores_provider_and_model=true;
    await click('#manageModelServices');const gemini=await add('gemini');await click('#useService');await until(`$('provider').value===${JSON.stringify(gemini)}&&$('studyModel').querySelector('option[value="gemini-fixture-pro"]')`);
    await run(`(()=>{$('studyModel').value='gemini-fixture-pro';$('studyModel').dispatchEvent(new Event('change'));return true;})()`);await run('modelPreferenceSave');await run('flushConversation()');
    await fill({prompt:'审批写入测试：请修改指定文件。'});await click('#sendMessage');await until(`$('agentApprovalRequests')&&!$('agentApprovalRequests').hidden`);
    await sleep(500);assert.equal((await data()).file,'审批前原内容');assert.equal(await run('isChatBusy()'),true);await snapshot('Gemini等待文件审批');
    await click('.approval-actions .primary');await until('!isChatBusy()');assert.equal((await data()).file,'审批后已保存');checks.gemini_native_tools_approval_resumes=true;
    await run(`(()=>{const dt=new DataTransfer();dt.items.add(new File(['相关不等于因果。尾部论据：实验也有外部效度限制。'],'第三方学习资料.txt',{type:'text/plain'}));document.getElementById('view-study').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:dt}));return true;})()`);
    await until('state.selected.size>0&&state.reading?.status===\'completed\'');checks.gemini_reads_full_original=true;
    await run(`(()=>{$('withExercises').checked=false;$('outputFormat').value='docx';return true;})()`);
    await click('#generate');await until(`(await api('/__model_service_test__/state')).artifacts.some(row=>row.kind==='explanation')`);
    const result=await data(),artifact=result.artifacts.find(row=>row.kind==='explanation');assert.equal(artifact.format,'docx');assert.equal(JSON.parse(artifact.metadata_json).dialogue_provider,gemini);assert.equal(JSON.parse(artifact.metadata_json).dialogue_model,'gemini-fixture-pro');
    assert.ok(result.requests.filter(row=>row.protocol==='gemini'&&row.source_read).length>=2);assert.ok(result.requests.some(row=>row.has_signature&&row.tool_result));checks.gemini_docx_generation_uses_same_model=true;
    const file=await run(`(await fetch('/api/artifacts/${artifact.id}/download')).arrayBuffer().then(buffer=>Array.from(new Uint8Array(buffer).slice(0,2)))`);assert.deepEqual(file,[80,75]);
    await snapshot('Gemini完成Word讲解');
    await run(`api('/api/conversations/'+state.conversation,jsonOptions('PUT',{project_id:state.project.id,source_ids:[]}))`);await run(`selectConversation(state.conversation)`);
    await click('#manageModelServices');await click('#addGeminiAccount');assert.equal(await run(`$('serviceApiFields').hidden`),true);assert.equal(await run(`$('geminiAccountActions').hidden`),false);assert.equal(await run(`$('serviceLogin').disabled`),true);checks.gemini_account_entry_available=true;
    await snapshot('Gemini账号入口');
    await fill({serviceModels:'auto\npro\nflash\ncli-quota-fixture'});
    await click('#saveService');await until(`!serviceFormBusy&&state.modelServices.some(row=>row.protocol==='gemini_cli')`);
    const account=await run(`state.modelServices.find(row=>row.protocol==='gemini_cli').id`);
    await click('#useService');await until(`$('provider').value===${JSON.stringify(account)}&&!conversationUI.restoring`);
    await fill({prompt:'账号流式验收：讲清楚概念与公式。'});await click('#sendMessage');
    await until(`isChatBusy()&&$('messages').textContent.includes('账号实时讲解')`);
    const early=await data();assert.equal(early.cli_requests.at(-1).phase,'started');
    assert.equal(await run(`$('messages').textContent.includes('tool_calls')`),false);await snapshot('Gemini账号逐步显示正文');
    await until('!isChatBusy()');checks.gemini_account_streams_before_completion=true;
    await fill({prompt:'账号审批测试：修改指定文件。'});await click('#sendMessage');await until(`$('agentApprovalRequests')&&!$('agentApprovalRequests').hidden`);
    assert.equal((await data()).file,'审批后已保存');assert.equal(await run('isChatBusy()'),true);
    await click('.approval-actions .primary');await until('!isChatBusy()');assert.equal((await data()).file,'账号审批后已保存');checks.gemini_account_tools_resume_after_approval=true;
    await fill({prompt:'账号取消测试：生成较长回复。'});await click('#sendMessage');await until(`isChatBusy()&&$('messages').textContent.includes('取消测试正在逐步生成正文')`);
    await click('#sendMessage');await until('!isChatBusy()');await sleep(100);
    const heartbeat=(await data()).cli_heartbeat;await sleep(200);assert.equal((await data()).cli_heartbeat,heartbeat);checks.gemini_account_cancel_stops_child=true;
    await click('#manageModelServices');await fill({serviceDefaultModel:'cli-quota-fixture'});await click('#saveService');await until('!serviceFormBusy');
    await run(`testService(${JSON.stringify(account)}).catch(()=>null)`);
    assert.equal(await run(`$('serviceFeedback').textContent.includes('额度')`),true);
    assert.equal(await run(`$('serviceFeedback').textContent.includes('PRIVATE_CREDENTIAL')`),false);checks.gemini_account_errors_are_actionable=true;
    assert.equal(result.paid_model_calls,0);assert.deepEqual(errors,[]);assert.ok(!result.jobs.some(row=>row.status==='failed'));
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({ok:true,checks,simulated_requests:result.requests.length,paid_model_calls:0,errors,artifact_path:artifact.path},null,2));win.destroy();app.exit(0);
  }catch(error){await snapshot('failure').catch(()=>{});fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,checks,errors,state:await data().catch(()=>null)},null,2));console.error(error.stack);app.exit(1);}
});
