/* Use the actual chat send button and real mouse approval clicks. */
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_PERMISSION_CASE,'utf8'));
const root=path.dirname(process.env.STUDYFORGE_PERMISSION_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],checks={},sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=code=>win.webContents.executeJavaScript(code,true);
async function until(code){for(let n=0;n<220;n++){if(await run(`(async()=>Boolean(${code}))()`))return;await sleep(50);}throw Error('Timeout: '+code);}
const state=()=>run(`api('/__chat_approval_test__/state')`);
async function send(text){await run(`$('prompt').value=${JSON.stringify(text)};$('sendMessage').click();`);await until('isChatBusy()');}
async function pending(){await until(`liveChats.get(state.conversation)?.waitingApproval&&$('agentApprovalRequests')?.querySelector('.approval-actions .primary')`);}
async function finish(){await until('!isChatBusy()');await until(`!$('agentApprovalRequests')||$('agentApprovalRequests').hidden`);}
async function click(allow=true){const selector=allow?'.approval-actions .primary':'.approval-actions button:not(.primary)';
  const point=await run(`(()=>{const node=document.querySelector(${JSON.stringify(selector)});node.scrollIntoView({block:'nearest'});const r=node.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(hit!==node&&!node.contains(hit))throw Error('Approval button is covered');return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
  win.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});win.webContents.sendInputEvent({type:'mouseUp',...point,button:'left',clickCount:1});
}
async function snapshot(name){win.webContents.invalidate();await sleep(120);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
async function otherChatWhilePending(returnTo){
  await run(`selectConversation(${JSON.stringify(input.other)})`);assert.equal(await run(`$('agentApprovalRequests')?.hidden??true`),true);
  await send('请简短解释什么是概念。');await finish();
  assert.equal((await state()).active_chats.includes(returnTo),true,'Pending chat must remain alive while another chat replies');
  await run(`selectConversation(${JSON.stringify(returnTo)})`);await pending();
}
app.whenReady().then(async()=>{
  try{
    win=new BrowserWindow({show:false,width:1480,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
    win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
    assert.equal(await run(`$('agentPermissionMode').value`),'approval');
    await send('批准测试，请将指定内容写入测试文件。');await pending();await sleep(1800);
    let data=await state();assert.equal(data.files.target,'原内容');assert.equal(data.messages[input.chat].filter(m=>m.role==='assistant').length,0);
    assert.equal(data.calls.filter(c=>c.provider==='deepseek').length,1);assert.equal(await run('isChatBusy()'),true);
    assert.equal(await run(`$('conversationWorkStatus').textContent.includes('等待你审批')`),true);await snapshot('聊天保持悬置');
    await otherChatWhilePending(input.chat);await click();await finish();data=await state();
    assert.equal(data.files.target,'批准后自动完成');assert.equal(data.messages[input.chat].filter(m=>m.role==='user').length,1);
    assert.equal(data.messages[input.chat].filter(m=>m.role==='assistant').length,1);checks.deepseek_approve_resumes_original=true;
    await send('拒绝测试，请修改测试文件。');await pending();await sleep(500);await click(false);await finish();data=await state();
    assert.equal(data.files.target,'批准后自动完成');assert.ok(data.messages[input.chat].at(-1).content.includes('你拒绝了'));checks.deny_preserves_file=true;
    await send('连续审批测试，请依次写入两个指定文件。');await pending();await click();
    await until(`(await api('/__chat_approval_test__/state')).files.first==='第一步完成'`);await pending();await sleep(500);data=await state();
    assert.equal(data.files.second,null);assert.equal(await run('isChatBusy()'),true);await click();await finish();
    assert.equal((await state()).files.second,'第二步完成');checks.each_operation_requires_its_own_decision=true;
    await run(`selectConversation(${JSON.stringify(input.codex)})`);await until(`state.conversation===${JSON.stringify(input.codex)}&&!conversationUI.restoring`);
    await send('Codex批准测试，请将指定内容写入测试文件。');await pending();await sleep(2000);data=await state();
    assert.equal(data.files.codex,'Codex原内容');assert.equal(data.codex_tool_replies.length,0);assert.equal(data.messages[input.codex].filter(m=>m.role==='assistant').length,0);
    assert.equal(await run('isChatBusy()'),true);await snapshot('Codex等待超过模拟超时仍悬置');
    await otherChatWhilePending(input.codex);await click();await finish();data=await state();
    assert.equal(data.files.codex,'Codex批准后自动完成');assert.equal(data.codex_tool_replies.length,1);assert.equal(data.codex_tool_replies[0].success,true);
    checks.codex_wait_does_not_use_model_timeout=true;checks.codex_approve_resumes_original=true;
    await send('Codex拒绝测试，请修改测试文件。');await pending();await click(false);await finish();data=await state();
    assert.equal(data.files.codex,'Codex批准后自动完成');assert.equal(data.codex_tool_replies.at(-1).success,false);checks.codex_deny_preserves_file=true;
    checks.pending_chat_survives_switch_and_restores=true;checks.other_chat_can_reply_with_concurrency_one=true;
    assert.equal(data.paid_model_calls,0);assert.deepEqual(errors,[]);await snapshot('审批后原回复完成');
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({ok:true,checks,simulated_provider_requests:data.calls.length,paid_model_calls:0,errors},null,2));win.destroy();app.exit(0);
  }catch(error){await snapshot('failure').catch(()=>{});fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,checks,errors,state:await state().catch(()=>null)},null,2));console.error(error.stack);app.exit(1);}
});
