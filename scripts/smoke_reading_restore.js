const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-reading-restore'));app.disableHardwareAcceleration();
const checks=[],errors=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=code=>pc.webContents.executeJavaScript(code);let pc;
async function until(code){for(let i=0;i<800;i++){if(await run(code))return;await sleep(60);}throw Error('Wait failed: '+code);}
async function shot(name){pc.webContents.debugger.attach('1.3');const r=await pc.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});pc.webContents.debugger.detach();fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
const pass=text=>checks.push(text);
app.whenReady().then(async()=>{
 try{
  pc=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  pc.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});
  await pc.loadURL(data.desktop_url);await until('state.ready&&state.conversation&&!conversationUI.restoring');
  await run(`selectConversation('${data.conversation_id}')`);await until(`state.conversation==='${data.conversation_id}'&&!conversationUI.restoring`);
  await run("$('readMaterials').click()");await until("state.reading?.progress===37");
  const original=await run('state.reading.job_id');assert.equal((await run("api('/__reading_ui__/state')")).starts.length,1);
  await run(`selectConversation('${data.empty_chat}')`);assert.equal(await run('state.reading'),null);
  await run(`selectProject(navigationUI.projects.find(p=>p.id==='${data.other_project_id}'),{conversationId:'${data.other_conversation_id}'})`);
  assert.equal(await run('state.reading'),null);
  await run(`selectProject(navigationUI.projects.find(p=>p.id==='${data.project_id}'),{conversationId:'${data.conversation_id}'})`);
  await until(`state.reading?.job_id==='${original}'&&state.reading.progress===37`);
  assert(await run("$('readMaterials').disabled&&!$('readingTaskControl').hidden&&$('readingTaskControl').textContent==='暂停通读'"));await shot('running-restored');
  pass('Switching chats and projects restores the same running read and its controls, with no reading state shown in an empty chat or another project');
  await new Promise(resolve=>{pc.webContents.once('did-finish-load',resolve);pc.reload();});await until(`state.ready&&!conversationUI.restoring&&state.conversation==='${data.conversation_id}'&&state.reading?.job_id==='${original}'&&state.reading.progress===37`);
  assert.equal((await run("api('/__reading_ui__/state')")).starts.filter(id=>id===original).length,1);await shot('reload-progress');
  pass('A full UI reload restores progress and watches the existing worker without restarting a model request');
  await run(`selectConversation('${data.empty_chat}')`);await run("showView('exercises')");await until("state.view==='exercises'");
  await run(`watchOutcomeTask('${data.routing_job}').catch(error);void 0`);await run("api('/__reading_ui__/complete-set',{method:'POST'})");
  await until(`!taskUI.watching.has('${data.routing_job}')`);
  assert(await run(`$('set-${data.routing_set}')?.hidden===true`));await shot('other-chat-worksheet-closed');
  await run("api('/__reading_ui__/release',{method:'POST'})");await until(`api('/__reading_ui__/state').then(s=>s.jobs.find(j=>j.id==='${original}').status==='completed')`);
  assert.equal(await run('state.reading'),null);
  await run(`selectConversation('${data.conversation_id}')`);await run("showView('study')");await until("state.reading?.status==='completed'");
  assert(await run("!$('showReadingNotes').hidden&&$('showReadingNotes').offsetHeight>0"));await shot('completed-notes-restored');
  const before=await run("api('/__reading_ui__/state')");assert.equal(before.model_calls,1);assert.equal(before.readings,1);
  pass('Completing an original chat read while another chat is active cannot attach notes there; returning restores saved notes after exactly one controlled model request. Another chats worksheet stays closed');
  await run(`selectConversation('${data.restore_chat}')`);await run("showView('study')");await until(`state.reading?.job_id==='${data.paused_job}'&&state.reading.status==='paused'`);
  assert(await run("!$('readingTaskControl').hidden&&$('readingTaskControl').offsetHeight>0&&$('readingTaskControl').textContent==='继续通读'"));await shot('paused-restored');
  await new Promise(resolve=>{pc.webContents.once('did-finish-load',resolve);pc.reload();});await until(`state.ready&&!conversationUI.restoring&&state.reading?.job_id==='${data.paused_job}'&&state.reading.status==='paused'`);
  assert.equal((await run("api('/__reading_ui__/state')")).starts.length,1);
  await run("showView('study')");assert(await run("$('readingTaskControl').offsetHeight>0"));await run("$('readingTaskControl').click()");await until("state.reading?.status==='completed'");
  const final=await run("api('/__reading_ui__/state')");assert.equal(final.starts.length,2);assert.equal(final.model_calls,1);assert.equal(final.readings,1);
  assert.equal(final.mastery,0);assert.equal(final.learning_events,before.learning_events);assert.equal(final.learning_events,1);await shot('resumed-completed');
  pass('A paused task remains paused across reload until its actual Continue button is clicked, then uses the same job and reuses unchanged notes without another model call or a mastery score');
  const cache=await run('JSON.stringify([...taskUI.jobs.values()])');assert(!cache.includes('messages')&&!cache.includes('notes'));
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'flow.json'),JSON.stringify(final,null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,model_calls:final.model_calls,external_model_requests:0,task_control_cache_bytes:Buffer.byteLength(cache),console_errors:errors},null,2));pc.destroy();app.exit(0);
 }catch(error){if(pc&&!pc.isDestroyed())await shot('failed');fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));if(pc&&!pc.isDestroyed())pc.destroy();app.exit(1);}
});
