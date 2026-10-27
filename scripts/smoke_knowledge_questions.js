const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.join(__dirname,'../build',process.argv[2]),data=JSON.parse(fs.readFileSync(path.join(folder,'case.json'),'utf8'));
app.setPath('userData',path.join(folder,'electron-knowledge-questions'));app.disableHardwareAcceleration();
let pc;const checks=[],errors=[],sleep=ms=>new Promise(r=>setTimeout(r,ms)),run=code=>pc.webContents.executeJavaScript(code);
async function until(code){for(let i=0;i<700;i++){if(await run(code))return;await sleep(60);}throw Error('Wait failed: '+code);}
async function shot(name){pc.webContents.debugger.attach('1.3');const r=await pc.webContents.debugger.sendCommand('Page.captureScreenshot',{format:'png'});pc.webContents.debugger.detach();fs.writeFileSync(path.join(folder,name+'.png'),Buffer.from(r.data,'base64'));}
app.whenReady().then(async()=>{
 try{
  pc=new BrowserWindow({show:false,width:1440,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
  pc.webContents.on('console-message',e=>{if((e.level==='error'||e.level===3)&&!/401|404|ERR_ABORTED/.test(e.message))errors.push(e.message);});
  await pc.loadURL(data.desktop_url);await until(`state.ready&&!conversationUI.restoring&&state.conversation==='${data.conversation_id}'`);
  await run("$('showKnowledge').click()");await until("$('knowledgeDialog').open&&!$('buildKnowledge').disabled");await run("$('buildKnowledge').click()");
  await until("knowledgeState.row?.structure&&!knowledgeState.busy&&!$('buildKnowledge').disabled");
  await run("$('knowledgeNodes').querySelectorAll('[data-knowledge-node]')[1].click()");
  assert(await run("document.querySelector('.knowledge-boundary strong').textContent==='论证的条件与边界：'&&document.querySelector('[data-knowledge-relation]').offsetHeight>0"));
  await run("document.querySelector('[data-knowledge-relation]').scrollIntoView({block:'nearest'})");await sleep(80);
  assert(await run("(()=>{const b=document.querySelector('[data-knowledge-relation]').getBoundingClientRect(),c=$('knowledgeContent').getBoundingClientRect();return b.top>=c.top&&b.bottom<=c.bottom;})()"));await shot('relation-question');
  const original='  我想保留原文术语，先讲清楚，不要出题。\n';
  await run(`$('prompt').value=${JSON.stringify(original)};document.querySelector('[data-knowledge-relation]').click()`);await until("!$('knowledgeDialog').open");await sleep(80);
  const draft=await run("$('prompt').value");assert(draft.startsWith(original)&&draft.includes('关键转化为什么想到')&&draft.includes('公式与条件.txt')&&draft.includes('$m>0$'));
  await run('flushConversation()');let result=await run("api('/__questions_ui__/state')");assert.equal(result.model_calls,1);assert.equal(result.tutor_requests.length,0);assert.equal(result.messages,0);
  checks.push('A visible relationship action uses the support-specific question and exact source conditions, preserves the original draft, and makes no tutor request');await shot('saved-question-draft');
  await run("$('showKnowledge').click()");await until("$('knowledgeDialog').open&&!$('buildKnowledge').disabled");await run("document.querySelector('[data-knowledge-relation]').click()");await sleep(80);
  assert.equal(await run("$('prompt').value"),draft);
  await run(`selectConversation('${data.second_chat}')`);assert.equal(await run("$('prompt').value"),'');
  await run(`selectConversation('${data.conversation_id}')`);assert.equal(await run("$('prompt').value"),draft);
  result=await run("api('/__questions_ui__/state')");assert.equal(result.model_calls,1);assert.equal(result.mastery,0);assert.equal(result.exercises,0);
  checks.push('Repeating the same selection does not duplicate its question; switching chats saves and restores only the originating draft');
  await run("$('sendMessage').click()");await until(`!liveChats.has('${data.conversation_id}')&&$('messages').textContent.includes('两边同除以')`);
  result=await run("api('/__questions_ui__/state')");assert.equal(result.tutor_requests.length,1);assert.equal(result.model_calls,2);assert.equal(result.exercises,0);assert.equal(result.mastery,0);
  const packet=result.tutor_requests[0],content=JSON.stringify(packet.messages);assert.equal(packet.model,'deepseek-flash');assert(content.includes('关键转化为什么想到')&&content.includes('待核对的图谱线索')&&content.includes('当质量 $m>0$ 不变时'));
  assert(content.includes('AI_REFERENCE_ONLY'));assert(!JSON.stringify(result.profile_candidates).includes('AI_REFERENCE_ONLY'));
  assert(await run("Boolean($('messages').querySelector('.katex'))"));await shot('tutor-followup');
  checks.push('Only the actual Send button calls the original chat tutor; it receives the targeted question and original source, returns formatted math, and does not generate a worksheet or mastery score');
  checks.push('Readable quoted graph references are retained for teaching but excluded from student profile evidence by the existing quotation filter');
  assert(!errors.length,JSON.stringify(errors));fs.writeFileSync(path.join(folder,'flow.json'),JSON.stringify(result,null,2));
  fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:true,checks,controlled_structure_requests:1,controlled_tutor_requests:1,external_model_requests:0,console_errors:errors},null,2));pc.destroy();app.exit(0);
 }catch(error){if(pc&&!pc.isDestroyed())await shot('failed');fs.writeFileSync(path.join(folder,'ui-report.json'),JSON.stringify({passed:false,error:error.stack,checks,console_errors:errors},null,2));if(pc&&!pc.isDestroyed())pc.destroy();app.exit(1);}
});
