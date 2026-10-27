/* Reuse the native two-submission flow, then check the new dependent behavior. */
const runnerFs=require('node:fs'),runnerPath=require('node:path');
let suite=runnerFs.readFileSync(runnerPath.join(__dirname,'smoke_review_versions_ui.js'),'utf8');
const marker='  assert(!errors.length,JSON.stringify(errors));pass(';
if(!suite.includes(marker))throw Error('Base acceptance insertion point changed');
const extra=String.raw`
  const stale=await run(pc,"fetch('/api/exercises/"+data.version_cases[0].origin+"/repair-options').then(async r=>({status:r.status,text:await r.text()}))");
  assert.equal(stale.status,400);assert(stale.text.includes('版本'));
  const normal=await run(pc,"api('/api/exercises/"+completed[0].exercise_set_id+"/repair-options')");assert(normal.assessment_version_verified);
  const legacy=await run(pc,"api('/api/exercises/"+data.version_cases[1].origin+"/repair-options')");assert.equal(legacy.assessment_version_verified,false);assert(legacy.notice.includes('旧作答版本未核实'));
  pass('Native repair options reject a changed parent version, accept the unchanged saved review and explicitly disclose an unknown legacy baseline without another model call');
  await run(pc,"showView('profile');refreshProfile()");
  await until(pc,"document.querySelector('.profile-recent-assessments')&&document.querySelector('#view-profile').textContent.includes('同题版本未核实')");
  assert(await run(pc,"document.querySelector('#view-profile').textContent.includes('同题版本已核实')"));
  await shot(pc,'desktop-profile-version-boundary');
  pass('The actual profile cards distinguish verified and unknown same-question versions while preserving both scores and review counts');
  await run(pc,"selectProject(state.project,{conversationId:'"+data.rate_test_chat+"'})");
  await until(pc,"state.conversation==='"+data.rate_test_chat+"'&&!conversationUI.restoring");
  await run(pc,"showView('study');$('prompt').value='请结合高斯定律和相关与因果的近期复习记录，说明哪些结论仍需要核对。';$('prompt').dispatchEvent(new Event('input'));$('sendMessage').click()");
  await until(pc,"api('/__followup_test__/state').then(s=>s.turns.length===1&&!s.active_chats.length)");
  await until(pc,"!isChatBusy()");
  assert(await run(pc,"![...$('messages').querySelectorAll('.reply-status')].some(x=>!x.hidden&&x.textContent.trim())&&$('prompt').value.includes('近期复习记录')"));
  assert(await run(pc,"$('toast').textContent.includes('HTTP 429')&&!$('toast').textContent.includes('codexErrorInfo')"));
  await shot(pc,'desktop-codex-rate-limit');
  pass('A native Codex turn ending in structured HTTP 429 clears waiting indicators, shows Chinese recovery advice and restores the original question');
  await run(pc,"$('sendMessage').click()");
  await until(pc,"api('/__followup_test__/state').then(s=>s.turns.length===2&&!s.active_chats.length)");
  await until(pc,"!isChatBusy()&&$('messages').textContent.includes('受控重试已完成')");
  const followup=await run(pc,"api('/__followup_test__/state')");assert(followup.turns.every(t=>t.verified_notice&&t.unknown_notice));
  fs.writeFileSync(path.join(folder,'followup-state.json'),JSON.stringify(followup,null,2));
  pass('The same conversation can retry successfully after the controlled rate error; tutor inputs include both version boundaries and no additional score is created');
`;
suite=suite.replace(marker,extra+marker).replace('controlled_model_calls:state.calls.length,real_model_requests:0',
 'controlled_model_calls:state.calls.length+followup.turns.length,tutor_turns:followup.turns.length,real_model_requests:0');
eval(suite);
