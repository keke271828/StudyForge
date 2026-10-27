/* Actual desktop + paired phone: stable controls, delayed reads and approval races. */
const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {X509Certificate}=require('node:crypto');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-refresh'));app.disableHardwareAcceleration();
const checks=[],errors=[],windows=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=(window,code)=>window.webContents.executeJavaScript(code);
async function until(window,code){for(let i=0;i<350;i++){if(await run(window,code))return;await sleep(100);}throw Error('UI wait failed: '+code);}
function pass(message){checks.push(message);fs.appendFileSync(path.join(folder,'ui-log.txt'),message+'\n');}
function watch(window){window.webContents.on('console-message',event=>{if(event.level==='error'&&!/401|404|ERR_ABORTED/.test(event.message))errors.push(event.message);});}
async function shot(window,name){if(!window.webContents.debugger.isAttached())window.webContents.debugger.attach('1.3');const result=await window.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(result.data,'base64'));}
app.whenReady().then(async()=>{
 const pc=new BrowserWindow({show:false,width:1440,height:950,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(pc);watch(pc);
 const rpc=path=>run(pc,`api(${JSON.stringify('/__workspace_test__/'+path)},{method:'POST'})`),stats=()=>run(pc,"api('/__workspace_test__/state')");
 try{
  await pc.loadURL(data.desktop_url);await until(pc,"state.ready&&state.conversation&&!conversationUI.restoring");
  await run(pc,"showView('artifacts')");await until(pc,`document.querySelector('[data-artifact="${data.artifact_ids[0]}"]')`);
  const sizes=await run(pc,`(async()=>{const summary=await api('/api/jobs/${data.task_ids[0]}?view=progress'),detail=await api('/api/jobs/${data.task_ids[0]}');return {summary:JSON.stringify(summary).length,detail:JSON.stringify(detail).length,can_pause:summary.can_pause};})()`);
  assert(sizes.summary<6000&&sizes.detail>1_000_000&&sizes.can_pause);pass('Desktop receives a compact live task view while the unchanged full task detail remains available');
  const phone=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});windows.push(phone);watch(phone);
  const ca=new X509Certificate(fs.readFileSync(data.certificate));phone.webContents.session.setCertificateVerifyProc((request,callback)=>{let ok=false;try{ok=request.hostname==='127.0.0.1'&&new X509Certificate(request.certificate.data).verify(ca.publicKey);}catch{}callback(ok?0:-3);});
  const name='刷新验收手机 '+Date.now(),pair=await run(pc,`api('/api/mobile/pairing',{method:'POST',headers:{'x-studyforge-desktop-token':'${data.token}'}})`);
  await phone.loadURL(data.mobile_url+'/#pair='+pair.pairing_code);await until(phone,"$('pairScreen')&&!$('pairScreen').hidden");await run(phone,`$('deviceName').value=${JSON.stringify(name)};$('pairForm').requestSubmit()`);
  await until(pc,`api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}).then(s=>s.devices.some(d=>d.status==='pending'&&d.name===${JSON.stringify(name)}))`);
  await run(pc,`(async()=>{const s=await api('/api/mobile/status',{headers:{'x-studyforge-desktop-token':'${data.token}'}}),device=s.devices.find(d=>d.status==='pending'&&d.name===${JSON.stringify(name)});await api('/api/mobile/devices/'+device.id+'/approve',{method:'POST',headers:{'Content-Type':'application/json','x-studyforge-desktop-token':'${data.token}'},body:JSON.stringify({approved:true})});})()`);
  await until(phone,"mobile.authenticated&&mobile.chat&&mobile.sources.length>=42");await run(phone,"clearInterval(refreshTimer)");await run(phone,"refreshProject({poll:true})");
  await run(phone,`$('openMaterials').click();window.sourceNode=$('sourceList').querySelector('input');sourceNode.focus({preventScroll:true});window.sourceSheet=$('materialsDialog').querySelector('.sheet-body');sourceSheet.scrollTop=180;window.listMutations=0;window.listObserver=new MutationObserver(rows=>listMutations+=rows.filter(row=>row.type==='childList').length);listObserver.observe($('sourceList'),{childList:true,subtree:true});`);
  await run(phone,"refreshProject({poll:true})");await sleep(100);
  assert(await run(phone,"$('sourceList').querySelector('input')===sourceNode&&document.activeElement===sourceNode&&sourceSheet.scrollTop===180&&listMutations===0"));
  pass('Unchanged material polling preserves the real checkbox, focus and scroll without rebuilding the list');
  await run(phone,"$('materialsDialog').querySelector('[data-close]').click();$('openArtifacts').click();window.artifactNode=$('artifactList').firstElementChild;window.downloadNode=artifactNode.querySelector('a');downloadNode.focus();");
  await run(phone,"refreshProject({poll:true})");assert(await run(phone,"$('artifactList').firstElementChild===artifactNode&&document.activeElement===downloadNode"));
  pass('Unchanged artifact polling preserves the download controls and their focus');
  const feedbackSelector=`[data-lesson-feedback-artifact="${data.artifact_ids[0]}"]`;
  await run(phone,`window.feedbackButton=document.querySelector('${feedbackSelector}');`);await rpc('feedback');await run(phone,"window.studyforgeMobileLessonFeedback.refresh()");
  assert(await run(phone,`document.querySelector('${feedbackSelector}')===feedbackButton&&feedbackButton.textContent==='查看补讲'`));pass('Changed feedback status updates its existing button instead of freezing it or rebuilding the artifact card');
  await run(phone,"$('artifactsDialog').querySelector('[data-close]').click()");
  const start=await rpc('hold/sources');
  await run(phone,"window.parallelRefresh=Promise.all(Array.from({length:30},()=>refreshProject({poll:true})));true");
  await until(pc,`api('/__workspace_test__/state').then(s=>s.mobile_sources>${start.mobile_sources})`);assert.equal((await stats()).mobile_sources-start.mobile_sources,1);
  await rpc('release/sources');await run(phone,"parallelRefresh");pass('Thirty concurrent phone polling requests share one real metadata request');
  const sorting=await rpc('hold/sort');await run(phone,"$('artifactSort').value='newest';window.oldSort=refreshProject({poll:true});true");
  await until(pc,`api('/__workspace_test__/state').then(s=>s.mobile_artifacts>${sorting.mobile_artifacts})`);
  await run(phone,"$('artifactSort').value='name';refreshProject()");assert(await run(phone,`mobile.artifacts[0].id==='${data.artifact_ids[0]}'`));
  await rpc('release/sort');await run(phone,"oldSort");assert(await run(phone,`mobile.artifacts[0].id==='${data.artifact_ids[0]}'&&$('artifactSort').value==='name'`));
  pass('A delayed response from the old sort cannot overwrite the newer sort selection');
  await run(phone,`window.studyforgeMobileHomework.openSet('${data.worksheet_id}')`);await until(phone,"$('homeworkAnswerForm')&&!$('homeworkAnswerForm').hidden");
  await run(phone,"window.answerNode=$('homeworkQuestions').querySelector('textarea');answerNode.value='我能复述符号，还要说明量的意义。';answerNode.dispatchEvent(new Event('input'));answerNode.focus();answerNode.setSelectionRange(3,8);window.answerScroll=$('homeworkDialog').querySelector('.sheet-body');answerScroll.scrollTop=40;");
  await run(phone,"refreshProject({poll:true})");assert(await run(phone,"$('homeworkQuestions').querySelector('textarea')===answerNode&&document.activeElement===answerNode&&answerNode.selectionStart===3&&answerNode.selectionEnd===8&&answerNode.value.includes('量的意义')"));
  assert(!(await run(phone,`api('/api/exercises/${data.worksheet_id}').then(row=>JSON.stringify(row).includes('HIDDEN_REFERENCE_BEFORE_SUBMISSION'))`)));
  await shot(phone,'phone-answer-draft');pass('Phone assignment refresh preserves the answer, exact cursor selection and original input node; solutions remain hidden');
  await run(phone,"$('homeworkDialog').querySelector('[data-close]').click()");await rpc('arm');await rpc('hold/pause');await run(phone,"refreshProject({poll:true})");await run(phone,"$('openTasks').click()");
  const a=`[data-task-id="${data.task_ids[0]}"]`,b=`[data-task-id="${data.task_ids[1]}"]`;
  await run(phone,`window.otherTask=document.querySelector('${b}');window.otherTaskButton=otherTask.querySelector('button');document.querySelector('${a} button').click();`);
  await until(pc,"api('/__workspace_test__/state').then(s=>s.pauses===1)");await rpc('progress');await run(phone,"otherTaskButton.focus();refreshProject({poll:true})");
  assert(await run(phone,`document.querySelector('${a} button').disabled&&document.querySelector('${b}')===otherTask&&document.activeElement===otherTaskButton`));
  await run(phone,`document.querySelector('${a} button').click()`);assert.equal((await stats()).pauses,1);
  await rpc('release/pause');await until(phone,`document.querySelector('${a} button')?.textContent==='继续'&&!document.querySelector('${a} button').disabled`);
  pass('A changing task keeps its pending action disabled while another task retains focus; pause is submitted once and the real paused state appears');
  await run(phone,"$('tasksDialog').querySelector('[data-close]').click()");await rpc('arm');await run(phone,"refreshProject({poll:true})");const approvalStart=await rpc('hold/approval_get');
  await run(phone,"window.oldApproval=approvals();true");await until(pc,`api('/__workspace_test__/state').then(s=>s.mobile_approval_gets>${approvalStart.mobile_approval_gets})`);
  await run(phone,`selectChat('${data.second_conversation_id}')`);await rpc('release/approval_get');await run(phone,"oldApproval");
  assert(await run(phone,"!$('approvalDialog').open&&!$('approvalList').children.length"));pass('A delayed approval from the previous conversation is discarded after switching chats');
  await run(phone,`selectChat('${data.conversation_id}')`);await run(phone,"approvals()");await until(phone,"$('approvalDialog').open");
  await run(phone,"window.approvalNode=$('approvalList').firstElementChild;window.approvalAllow=approvalNode.querySelector('button');approvalAllow.focus();");await run(phone,"approvals()");
  assert(await run(phone,"$('approvalList').firstElementChild===approvalNode&&document.activeElement===approvalAllow"));
  await rpc('hold/approval_post');await run(phone,"approvalAllow.click()");await until(pc,"api('/__workspace_test__/state').then(s=>s.approval_posts===1)");await run(phone,"approvals()");
  assert(await run(phone,"[...$('approvalList').querySelectorAll('button')].every(button=>button.disabled)"));await run(phone,"$('approvalList').querySelector('button').click()");assert.equal((await stats()).approval_posts,1);
  await rpc('release/approval_post');await until(phone,"!$('approvalDialog').open");assert.equal((await stats()).approval,'approved');
  pass('Both approval choices stay disabled until the native approval API confirms; periodic reads cannot produce a duplicate decision');
  const download=await run(phone,`fetch('/api/artifacts/${data.artifact_ids[0]}/download').then(async r=>({status:r.status,bytes:[...new Uint8Array(await r.arrayBuffer())].slice(0,2)}))`);assert.equal(download.status,200);assert.deepEqual(download.bytes,[80,75]);pass('The paired phone still downloads the actual Word document');
  await run(phone,"$('openArtifacts').click()");await shot(phone,'phone-stable-artifacts');await shot(pc,'desktop-workspace-tasks');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,console_errors:errors,task_response_sizes:sizes,external_model_requests:0},null,2));windows.forEach(window=>window.destroy());app.exit(0);
 }catch(error){fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack||String(error),checks,console_errors:errors},null,2));for(const [i,window]of windows.entries())if(window.webContents.getURL())await shot(window,'failed-'+i);windows.forEach(window=>window.destroy());app.exit(1);}
});
