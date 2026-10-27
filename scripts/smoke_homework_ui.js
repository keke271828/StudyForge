const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(process.env.STUDYFORGE_HOMEWORK_CASE,'utf8')),root=path.dirname(process.env.STUDYFORGE_HOMEWORK_CASE);
app.setPath('userData',path.join(root,'electron-profile'));app.disableHardwareAcceleration();
let win;const errors=[],gradingContrast=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function luminance(rgb){return rgb.slice(0,3).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);}
async function run(code){return win.webContents.executeJavaScript(code);}
async function until(code){for(let i=0;i<350;i++){if(await run(code))return;await sleep(80);}throw Error('Timeout: '+code);}
async function inspect(){return run(`api('/__homework_test__/state')`);}
async function snapshot(name){await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');win.webContents.invalidate();await sleep(350);fs.writeFileSync(path.join(root,name+'.png'),(await win.webContents.capturePage()).toPNG());}
app.whenReady().then(async()=>{
  win=new BrowserWindow({show:false,width:1480,height:1050,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,offscreen:true}});
  win.webContents.on('console-message',event=>{if(event.level==='error'||event.level===3)errors.push(event.message);});
  try{
    await win.loadURL(input.url);await until('state.ready&&state.conversation&&!conversationUI.restoring&&state.settings');
    await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.project}'),{conversationId:'${input.chat}'})`);
    if(input.phase===1){
      assert.equal(await run(`(async()=>JSON.stringify(await api('/api/exercises/${input.worksheet}')).includes('REFERENCE_GAUSS'))()`),false);
      await run(`$('submitHomework').click()`);await until(`$('homeworkSet').options.length===2`);
      await run(`$('homeworkSet').value='${input.worksheet}';$('homeworkSet').dispatchEvent(new Event('change'));const fields=$('homeworkQuestions').querySelectorAll('textarea');fields[0].value='不知道电通量是什么';fields[1].value='2+3=4';$('homeworkComplete').checked=true;$('homeworkSubmit').click()`);
      await until(`$('homeworkResult').querySelector('a')`);
      let state=await inspect();assert.equal(state.attempts.length,1);const attempt=state.attempts[0];
      assert.ok(attempt.solution_artifact);assert.equal(attempt.feedback_artifact,null);assert.equal(state.submissions.length,0);
      assert.equal(state.artifacts.length,1);assert.ok(state.artifacts[0].paragraphs.includes('REFERENCE_GAUSS'));
      assert.ok(await run(`(async()=>{const r=await fetch('${attempt.solution_artifact.download_url}');const b=new Uint8Array(await r.arrayBuffer());return r.ok&&b[0]===80&&b[1]===75;})()`),'Downloaded file must be actual DOCX');
      await snapshot('提交后立即下载原题解析');
      await run(`$('closeHomework').click();$('prompt').value='我想理解变量的含义';$('sendMessage').click()`);
      await until(`!isChatBusy('${input.chat}')&&$('messages').textContent.includes('独立作业批改')`);
      state=await inspect();assert.equal(state.submissions.length,0,'Tutor chat should finish while grading remains blocked');
      await run(`api('/__homework_test__/release',{method:'POST'})`);
      await until(`$('messages').querySelector('[data-homework-questionnaire]')`);
      state=await inspect();assert.equal(state.attempts[0].status,'awaiting_causes');assert.equal(state.artifacts.length,1,'Cannot export grading before questionnaire');
      assert.equal(state.submissions.length,1);
      await run(`const draft=$('messages').querySelector('[data-homework-questionnaire] textarea');draft.value='未提交的临时思路';draft.dispatchEvent(new Event('input',{bubbles:true}));refreshConversationMessages();selectConversation('${input.second}')`);
      await until(`(async()=>{const a=(await api('/__homework_test__/state')).attempts[0];return a.cause_draft?.[0]?.text==='未提交的临时思路';})()`);
      assert.equal(await run(`$('messages').querySelectorAll('[data-homework-questionnaire]').length`),0);
      await run(`selectConversation('${input.chat}')`);
      assert.equal(await run(`$('messages').querySelector('[data-homework-questionnaire] textarea').value`),'未提交的临时思路');
      await run(`$('messages').querySelector('[data-homework-questionnaire]').scrollIntoView({block:'end'})`);
      await snapshot('错因问卷暂停批改并保留输入');
      await run(`const exitDraft=$('messages').querySelector('[data-homework-questionnaire] textarea');exitDraft.dispatchEvent(new Event('input',{bubbles:true}));prepareDesktopExit()`);
      fs.writeFileSync(path.join(root,'phase1.json'),JSON.stringify({attempt:attempt.id,job:attempt.job_id,grade_calls:state.calls.filter(c=>c.kind==='grade').length},null,2));
    }else{
      const saved=JSON.parse(fs.readFileSync(path.join(root,'phase1.json'),'utf8'));
      await until(`$('messages').querySelector('[data-homework-questionnaire]')`);
      assert.equal(await run(`$('messages').querySelector('[data-homework-questionnaire] textarea').value`),'未提交的临时思路','Questionnaire draft must survive backend restart');
      let state=await inspect();assert.equal(state.attempts[0].status,'awaiting_causes');assert.equal(state.artifacts.length,1);
      await run(`const form=$('messages').querySelector('[data-homework-questionnaire] form');form.querySelector('input[value="terminology"]').checked=true;form.querySelector('textarea').value='我把通量当作电场，不清楚面积出现在哪里';form.requestSubmit()`);
      await until(`(async()=>{const a=(await api('/__homework_test__/state')).attempts.find(x=>x.id==='${saved.attempt}');if(a.status==='failed')throw Error(a.error);return a.status==='completed';})()`);
      await until(`$('messages').textContent.includes('批改与错题讲解已完成')`);
      state=await inspect();assert.equal(state.submissions.length,1);assert.equal(state.calls.filter(c=>c.kind==='grade').length,saved.grade_calls,'Restart and questionnaire must not grade twice');
      const grade=state.artifacts.find(a=>a.kind==='grading');assert.ok(grade.paragraphs.includes('错因分析')&&grade.paragraphs.includes('针对性讲解'));
      assert.ok(grade.paragraphs.includes('把通量直接当作电场'));assert.ok(grade.paragraphs.includes('4−3=1'));
      assert.equal(await run(`$('messages').querySelectorAll('[data-homework-questionnaire]').length`),0);
      await run(`showView('exercises')`);await until(`$('exercises').querySelector('[data-open-set="${input.worksheet}"]')`);
      await run(`$('exercises').querySelector('[data-open-set="${input.worksheet}"]').click()`);
      await until(`$('set-${input.worksheet}').querySelector('.grading-feedback .katex')`);
      assert.ok(await run(`$('set-${input.worksheet}').querySelector('.grading-feedback strong').textContent.includes('封闭面通量')`),'Grading feedback must render Markdown too');
      for(const theme of ['paper','night']){
        await run(`saveStudioPreferences({ui_theme:'${theme}'})`);
        for(const [panel,text] of [['.grading-feedback','p'],['.practice-feynman','summary'],['.practice-feynman','label'],['.practice-diagnosis','strong'],['.practice-diagnosis','p'],['.practice-diagnosis','.small-note']]){
          const colors=await run(`(()=>{const box=$('set-${input.worksheet}').querySelector('${panel}'),p=box.querySelector('${text}');return {background:getComputedStyle(box).backgroundColor,text:getComputedStyle(p).color};})()`);
          const rgb=value=>value.match(/[\d.]+/g).map(Number),a=luminance(rgb(colors.background)),b=luminance(rgb(colors.text)),contrast=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
          assert.ok(contrast>=4.5,'Teaching text must be readable in '+theme+' '+panel+' '+text+': '+contrast);
          gradingContrast.push({theme,panel,text_selector:text,contrast:Number(contrast.toFixed(2)),...colors});
        }
        await run(`$('set-${input.worksheet}').querySelector('.grading-feedback').scrollIntoView({block:'center'})`);
        await snapshot('批改讲解公式与Markdown-'+theme);
      }
      await run(`saveStudioPreferences({ui_theme:'paper'})`);
      await run(`showView('study')`);
      await run(`$('submitHomework').click()`);await until(`$('homeworkSet').options.length===1`);
      assert.equal(await run(`$('homeworkSet').value`),input.program);
      await run(`const transfer=new DataTransfer();transfer.items.add(new File([new Uint8Array([47,47,32,214,208,206,196,10,...new TextEncoder().encode('function add(a,b){return a-b;}')])],'作业.js',{type:'text/plain'}));$('homeworkAnswerFile').files=transfer.files;$('homeworkExtract').click()`);
      await until(`$('homeworkQuestions').querySelector('textarea').value.includes('中文')`);
      assert.equal(await run(`$('homeworkQuestions').querySelector('textarea').value.includes('\ufffd')`),false);
      await run(`$('homeworkComplete').checked=true;$('homeworkSubmit').click()`);
      await until(`(async()=>{const a=(await api('/__homework_test__/state')).attempts.find(x=>x.exercise_set_id==='${input.program}');if(a?.status==='failed')throw Error(a.error);return a?.status==='completed';})()`);
      state=await inspect();const code=state.attempts.find(a=>a.exercise_set_id===input.program);assert.equal(code.score,null);assert.equal(code.provisional,true);
      assert.ok(state.artifacts.find(a=>a.id===code.feedback_artifact.id).paragraphs.includes('没有最终分数'));
      await until(`!homeworkState.busy&&$('homeworkHistory').querySelectorAll('a').length===4`);
      await run(`refreshArtifacts();$('homeworkHistory').scrollIntoView({block:'end'})`);await snapshot('两份文档与JavaScript作业反馈');
      await run(`$('closeHomework').click()`);
      const recheck=await run(`api('/__homework_test__/review-worksheet',{method:'POST'})`);
      await run(`$('submitHomework').click()`);await until(`$('homeworkSet').value==='${recheck.id}'`);
      await run(`$('homeworkQuestions').querySelector('textarea').value='从2依次加三个1，得到3、4、5，所以2+3=5。';$('homeworkComplete').checked=true;$('homeworkSubmit').click()`);
      await until(`(async()=>{const a=(await api('/__homework_test__/state')).attempts.find(x=>x.exercise_set_id==='${recheck.id}');if(a?.status==='failed')throw Error(a.error);return a?.status==='awaiting_grade_review';})()`);
      await until(`$('homeworkHistory').textContent.includes('重新复核原作答')`);
      state=await inspect();const pending=state.attempts.find(a=>a.exercise_set_id===recheck.id);
      assert.equal(pending.score,null);assert.ok(pending.grading_verification_required);assert.equal(pending.waiting_for_causes,false);
      assert.ok(state.artifacts.find(a=>a.id===pending.feedback_artifact.id).paragraphs.includes('暂不定分'));
      const countBefore=state.submissions.length;await snapshot('评分待核实与重新复核入口');
      await run(`api('/__homework_test__/clear-review-doubt',{method:'POST'})`);
      await run(`$('homeworkHistory').querySelector('[data-homework-retry="${pending.id}"]').click()`);
      await until(`(async()=>{const a=(await api('/__homework_test__/state')).attempts.find(x=>x.id==='${pending.id}');if(a?.status==='failed')throw Error(a.error);return a?.status==='completed'&&a.score===100;})()`);
      state=await inspect();assert.equal(state.submissions.length,countBefore,'Recheck must update the same submission');
      assert.equal(state.attempts.find(a=>a.id===pending.id).grading_verification_required,false);
      await until(`!$('homeworkHistory').textContent.includes('重新复核原作答')`);
      await snapshot('实际按钮重新复核得到确定成绩');
      await run(`$('closeHomework').click();selectConversation('${input.second}')`);
      assert.equal(await run(`$('homeworkNotice').hidden`),true,'Other chat must not display this chat submission');
      await run(`selectProject(navigationUI.projects.find(p=>p.id==='${input.other}'))`);
      assert.equal((await run(`api('/api/projects/${input.other}/artifacts')`)).length,0);
      assert.equal((await run(`api('/api/projects/${input.other}/homework')`)).length,0);
      assert.deepEqual(errors,[]);
      fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({phase1:true,phase2:true,immediate_docx:true,grading_blocked_before_questionnaire:true,
        tutor_chat_during_grading:true,questionnaire_in_original_chat:true,questionnaire_restored_after_restart:true,questionnaire_draft_restored:true,
        resume_did_not_regrade:true,personalized_gauss_teaching:true,arithmetic_error_teaching:true,javascript_submission:true,
        provisional_without_docker:true,chinese_code_file_encoding:true,grading_doubt_not_student_error:true,
        recheck_button_executed:true,recheck_no_duplicate_submission:true,grading_markdown_and_math:true,grading_contrast:gradingContrast,separate_documents:state.artifacts.length,project_isolation:true,errors},null,2));
    }
    assert.deepEqual(errors,[]);app.exit(0);
  }catch(error){const state=await run(`({ready:state.ready,project:state.project?.id,chat:state.conversation,restoring:conversationUI.restoring,buttonDisabled:$('submitHomework')?.disabled,dialogOpen:$('homeworkDialog')?.open,options:$('homeworkSet')?.innerHTML,toast:$('toast')?.textContent})`).catch(()=>null);await snapshot('failure').catch(()=>{});fs.writeFileSync(path.join(root,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,errors,state},null,2));console.error(error);app.exit(1);}
});
