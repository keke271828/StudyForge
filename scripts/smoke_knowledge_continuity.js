const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-knowledge-continuity'));app.disableHardwareAcceleration();
const checks=[],errors=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));let pc;
const run=code=>pc.webContents.executeJavaScript(code);
async function until(code){for(let i=0;i<700;i++){if(await run(code))return;await sleep(60);}throw Error('Wait failed: '+code);}
async function shot(name){pc.webContents.debugger.attach('1.3');const r=await pc.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});pc.webContents.debugger.detach();fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
app.whenReady().then(async()=>{
 try{
  pc=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  pc.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});
  await pc.loadURL(data.desktop_url);await until(`state.ready&&!conversationUI.restoring&&state.conversation==='${data.conversation_id}'`);
  await run("$('showKnowledge').click()");await until("$('knowledgeDialog').open&&!$('buildKnowledge').disabled");
  assert.equal(await run('knowledgeState.jobId'),null);assert(await run("$('knowledgeTaskControl').hidden"));
  checks.push('Opening chat A does not adopt chat B paused structure task for the same reading and model');
  await run("$('buildKnowledge').click()");await until("knowledgeState.row?.structure&&!knowledgeState.busy&&!$('buildKnowledge').disabled");
  assert(await run("Boolean(document.querySelector('.knowledge-quote .katex'))&&Boolean(document.querySelector('[data-knowledge-reason] .katex'))&&Boolean(document.querySelector('[data-knowledge-boundary] .katex'))&&!window.knowledgeUnsafe&&!$('knowledgeDetail').querySelector('script')"));
  await shot('math-structure');
  checks.push('A real structure worker creates source-matched concepts; quotes, relation reasoning and boundaries render math without executing supplied script text');
  await run("document.querySelector('[data-knowledge-source]').click()");await until("$('knowledgeSourceExcerpt').querySelector('details pre')");
  assert(await run("Boolean($('knowledgeSourceExcerpt').querySelector('.katex'))&&$('knowledgeSourceExcerpt').querySelector('pre').textContent.includes('$F=ma$')"));await shot('math-original');
  checks.push('The original source opens with readable formulas and an unchanged raw-text view, without another model request');
  const before=await run("api('/__knowledge_ui__/state')");assert.equal(before.model_calls,1);assert.equal(before.read_jobs,0);
  await run("$('buildKnowledge').click()");await until("knowledgeState.row?.structure&&!knowledgeState.busy&&!$('buildKnowledge').disabled");
  const rebuilt=await run("api('/__knowledge_ui__/state')");assert.equal(rebuilt.model_calls,2);assert.equal(rebuilt.read_jobs,0);assert.equal(rebuilt.maps,2);
  checks.push('Explicit rebuild makes exactly one more structure request and no additional reading task');
  await run("$('prompt').value='保留我已有的问题，不要出题。';document.querySelector('[data-knowledge-teach]').click()");await until("!$('knowledgeDialog').open");await sleep(100);
  assert(await run("$('prompt').value.includes('保留我已有的问题')&&$('prompt').value.includes('合力与加速度')"));
  assert.equal((await run("api('/__knowledge_ui__/state')")).model_calls,2);
  await run(`selectConversation('${data.second_chat}')`);await run("showView('study');$('showKnowledge').click()");
  await until(`knowledgeState.jobId==='${data.paused_knowledge}'&&!$('knowledgeTaskControl').hidden`);
  assert(await run("$('buildKnowledge').disabled&&$('knowledgeTaskControl').textContent==='继续整理'&&$('knowledgeTaskControl').offsetHeight>0"));await shot('own-paused-task');
  await run("$('knowledgeTaskControl').click()");await until(`api('/api/jobs/${data.paused_knowledge}?view=progress').then(j=>j.status==='completed')`);
  await until("!taskUI.watching.size&&knowledgeState.row?.structure&&!$('buildKnowledge').disabled");
  const final=await run("api('/__knowledge_ui__/state')");assert.equal(final.model_calls,2);assert.equal(final.read_jobs,0);assert.equal(final.mastery,0);assert.equal(final.messages,0);assert.equal(final.exercises,0);
  checks.push('Returning a concept preserves the draft without sending a chat; chat B resumes its own paused task and reuses unchanged structure, without mastery scores or exercises');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'flow.json'),JSON.stringify(final,null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_model_requests:2,external_model_requests:0,console_errors:errors},null,2));pc.destroy();app.exit(0);
 }catch(error){if(pc&&!pc.isDestroyed())await shot('failed');fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));if(pc&&!pc.isDestroyed())pc.destroy();app.exit(1);}
});
