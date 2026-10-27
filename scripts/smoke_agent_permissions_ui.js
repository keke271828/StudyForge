const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_PERMISSION_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_PERMISSION_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const run=async code=>{try{return await win.webContents.executeJavaScript(code.startsWith('(await ')?`(async()=>(${code}))()`:code,true);}catch(error){throw Error(error.message+'\nCode: '+code+'\nRenderer: '+JSON.stringify(errors));}};
async function until(code){for(let n=0;n<180;n++){if(await run(`(async()=>Boolean(${code}))()`))return;await sleep(50);}throw Error('Timeout: '+code);}
async function state(){return run(`api('/__permission_test__/state')`);}
async function mode(value){await run(`$('agentPermissionMode').value=${JSON.stringify(value)};$('agentPermissionMode').dispatchEvent(new Event('change'));`);await until('!agentPermissionPending');assert.equal(await run(`(await api('/api/settings')).agent_permission_mode`),value);}
async function start(text){return run(`api('/__permission_test__/operation',jsonOptions('POST',{text:${JSON.stringify(text)}}))`);}
async function click(selector){const r=await run(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});el.scrollIntoView({block:'nearest'});const r=el.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);win.webContents.sendInputEvent({type:'mouseDown',...r,button:'left',clickCount:1});win.webContents.sendInputEvent({type:'mouseUp',...r,button:'left',clickCount:1});}
app.whenReady().then(async()=>{
  try{
    win=new BrowserWindow({show:false,width:1480,height:1000,webPreferences:{sandbox:true,contextIsolation:true,offscreen:true,backgroundThrottling:false}});
    win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
    assert.equal(await run(`$('agentPermissionMode').value`),'read_only');
    await start('must not write');await until(`(await api('/__permission_test__/state')).operations['0']?.error`);assert.equal((await state()).content,null);
    await mode('approval');await start('approved once');await until(`$('agentApprovalRequests')?.querySelector('.agent-approval-card')`);assert.equal((await state()).content,null);
    win.setSize(1080,700);await sleep(200);
    assert.equal(await run(`(()=>{const button=$('agentApprovalRequests').querySelector('.primary'),r=button.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&$('sendMessage').getBoundingClientRect().bottom<=innerHeight;})()`),true,'Approvals and composer must remain usable in the minimum desktop window');
    win.setSize(1480,1000);await sleep(150);
    await run(`selectConversation(${JSON.stringify(input.second)})`);assert.equal(await run(`$('agentApprovalRequests')?.hidden??true`),true);
    await run(`selectConversation(${JSON.stringify(input.chat)})`);await until(`$('agentApprovalRequests')&&!$('agentApprovalRequests').hidden`);
    await win.reload();await until('state.ready&&!conversationUI.restoring&&$("agentApprovalRequests")&&!$("agentApprovalRequests").hidden');
    fs.writeFileSync(path.join(root,'审批卡片.png'),(await win.webContents.capturePage()).toPNG());
    await click('.approval-actions .primary');await until(`(await api('/__permission_test__/state')).content==='approved once'`);
    await start('denied write');await until(`$('agentApprovalRequests')&&!$('agentApprovalRequests').hidden`);await click('.approval-actions button:not(.primary)');await until(`(await api('/__permission_test__/state')).operations['2']?.error`);assert.equal((await state()).content,'approved once');
    await mode('full_access');await start('full access wrote');await until(`(await api('/__permission_test__/state')).content==='full access wrote'`);await until(`$('agentApprovalRequests')?.hidden??true`);
    await win.reload();await until('state.ready&&!conversationUI.restoring');assert.equal(await run(`$('agentPermissionMode').value`),'full_access');
    await run(`showView('settings');showSettingsSection('tools')`);await until(`$('videoImportMode')`);
    await run(`$('videoImportMode').value='subtitles_first';$('videoImportMode').dispatchEvent(new Event('change'));`);await until(`!$('videoImportMode').disabled`);
    assert.equal(await run(`(await api('/api/settings')).video_import_mode`),'subtitles_first');
    assert.equal((await state()).model_calls,0);assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:true,read_only_blocks:true,approval_waits:true,chat_scope_isolated:true,reload_restores:true,approve_writes:true,deny_preserves:true,full_access_writes:true,subtitle_setting_saved:true,model_calls:0,errors},null,2));
    win.destroy();app.exit(0);
  }catch(error){fs.writeFileSync(path.join(root,'failure.txt'),error.stack);console.error(error);app.exit(1);}
});
