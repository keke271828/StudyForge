/* Extend the existing native feedback workflow, retaining its isolation checks. */
const fsRunner=require('node:fs'),pathRunner=require('node:path');
let suite=fsRunner.readFileSync(pathRunner.join(__dirname,'smoke_lesson_passage_ui.js'),'utf8');
suite=suite.replaceAll("querySelector('[data-passage-quote]').textContent","querySelector('[data-passage-quote]').dataset.rawText");
const marker='  assert(!errors.length,JSON.stringify(errors));';
if(!suite.includes(marker))throw Error('Passage base acceptance changed');
const extra=String.raw`
  const mapping=await require('./check_source_selection_ui.js')(pc);
  fs.writeFileSync(path.join(folder,'source-mapping-checks.json'),JSON.stringify(mapping,null,2));
  pass('Shared production mapping retains exact source positions through Markdown, equations, code, Unicode and inert markup');
  const widget=await require('./check_lesson_passage_math_widget.js')(pc);
  fs.writeFileSync(path.join(folder,'widget-checks.json'),JSON.stringify(widget,null,2));
  pass('Production passage widget passes '+widget.cases.length+' bounded selection, mode, version and stale-read checks');
  async function openMath(win,id,phoneMode){
    if(phoneMode)await run(win,"studyforgeMobileLessonFeedback.open('"+id+"')");
    else await run(win,"openLessonFeedback('"+id+"')");
    const root=phoneMode?"document.getElementById('lessonFeedbackDialog')":cardCode(id);
    if(phoneMode)fs.writeFileSync(path.join(folder,'phone-math-open.json'),JSON.stringify(await run(win,"({title:$('lessonFeedbackTitle').textContent,chat:mobile.chat?.id,open:$('lessonFeedbackDialog').open,options:[...$('lessonFeedbackFocus').options].map(x=>({text:x.textContent,value:x.value}))})"),null,2));
    await until(win,"[...("+root+").querySelector('"+(phoneMode?'#lessonFeedbackFocus':'[data-feedback-focus]')+"').options].some(o=>o.textContent.endsWith('公式与构造'))");
    await run(win,"(()=>{const c="+root+",s=c.querySelector('"+(phoneMode?'#lessonFeedbackFocus':'[data-feedback-focus]')+"');s.closest('details').open=true;s.value=[...s.options].find(o=>o.textContent.endsWith('公式与构造')).value;s.dispatchEvent(new Event('change',{bubbles:true}));c.querySelector('[data-passage-open]').click()})()");
    await until(win,"("+root+").querySelector('[data-passage-preview] .katex')&&!("+root+").querySelector('[data-passage-use]').disabled");
    assert.equal(await run(win,"("+root+").querySelector('[data-passage-text]').value"),data.math_section_text.replace(/\r\n/g,'\n'));
    assert.equal(await run(win,"("+root+").querySelector('[data-passage-next]').disabled"),true);
    assert.equal(await run(win,"("+root+").querySelector('[data-passage-source-label]').hidden"),true);
    assert(!await run(win,"Boolean(("+root+").querySelector('[data-passage-preview] img'))"));
    // Select a tiny rendered piece: the stored citation must include all LaTeX.
    await run(win,"(()=>{const c="+root+",math=c.querySelector('[data-passage-preview] .katex-html'),node=math.querySelector('.mord')||math,r=document.createRange();r.selectNodeContents(node);getSelection().removeAllRanges();getSelection().addRange(r);c.querySelector('[data-passage-use]').click()})()");
    const selected=phoneMode?await run(win,"safeRead('sfMobileLesson:draft:'+mobile.project.id+':"+id+"',{}).focus_selection"):
      await run(win,"("+root+").querySelector('[data-feedback-passage]').passageControl.value()");
    assert.deepEqual(selected,data.math_selection);
    assert(await run(win,"Boolean(("+root+").querySelector('[data-passage-quote] .katex'))"));
    await run(win,"("+root+").querySelector('[data-passage-chosen]').scrollIntoView({block:'center',behavior:'instant'})");
    return root;
  }
  const mid=data.math_questionnaire.id,mathRoot=await openMath(pc,mid,false);
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,2);
  await shot(pc,'电脑端补讲原句公式');
  await run(pc,"(()=>{const c="+mathRoot+";c.querySelector('[data-passage-source]').click();c.querySelector('[name=difficulty][value=motivation]').click();c.querySelector('[name=other_text]').value='我只卡在所选公式为什么这样构造。';c.querySelector('[name=other_text]').dispatchEvent(new Event('input'));c.querySelector('[data-submit-feedback]').click()})()");
  await until(pc,"api('/api/projects/"+data.project_id+"/lesson-feedback').then(rows=>rows.find(x=>x.id==='"+mid+"')?.reply_status==='completed')");
  const afterMath=(await run(pc,"api('/__library_test__/calls')")).calls;
  assert.equal(afterMath.length,3);assert(afterMath[2].messages[0].content.includes(data.math_selection.text));
  assert(afterMath[2].messages[0].content.includes('不是学生作答'));
  pass('Desktop joins a two-window short proof without splitting its equation; native followup receives the full original formula as historical AI context, not a student answer');
  const mpid=data.math_phone_questionnaire.id;await run(phone,"theme('dark')");phone.setSize(320,844);
  const phoneRoot=await openMath(phone,mpid,true);
  assert(await run(phone,"(()=>{const p=document.querySelector('#lessonFeedbackPassage [data-passage-prev]').getBoundingClientRect(),u=document.querySelector('#lessonFeedbackPassage [data-passage-use]').getBoundingClientRect();return u.width>p.width*1.5&&u.height<60})()"));
  await shot(phone,'手机端补讲原句公式');
  assert(await run(phone,"document.documentElement.scrollWidth<=innerWidth"));
  await phone.reload();await until(phone,'mobile.authenticated&&mobile.chat');await run(phone,"studyforgeMobileLessonFeedback.open('"+mpid+"')");
  const restored=await run(phone,"safeRead('sfMobileLesson:draft:'+mobile.project.id+':"+mpid+"',{}).focus_selection");assert.deepEqual(restored,data.math_selection);
  assert(await run(phone,"Boolean(document.querySelector('#lessonFeedbackPassage [data-passage-quote] .katex'))"));
  assert.equal((await run(pc,"api('/__library_test__/calls')")).calls.length,3);
  assert.equal((await run(pc,"api('/api/profile')")).length,0);
  assert.equal((await run(pc,"api('/api/projects/"+data.project_id+"/exercises')")).length,0);
  pass('Paired 320px dark phone selects the same formula, restores the exact citation with math after refresh, and starts no unrequested model or exercise task');
  fs.writeFileSync(path.join(folder,'math-final.json'),JSON.stringify({model_requests:3,external_model_requests:0,exact_formula:data.math_selection,mapping_cases:mapping.cases.length},null,2));
`;
suite=suite.replace(marker,extra+marker).replace('model_requests:2,external_model_requests:0','model_requests:3,external_model_requests:0');
eval(suite);
