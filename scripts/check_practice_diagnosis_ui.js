module.exports=async win=>win.webContents.executeJavaScript('('+function(){
 const checks=[],host=document.createElement('div');document.body.append(host);
 const set={id:'local',questions:[{index:0,topic:'符号'}],status:'graded'},quote='<b>这是学生作答</b>，'+String.raw`\(x=1\)`;
 const diagnosis={index:0,label:'原因待定位',status:'暂定诊断',reason:'**方法依据**：'+String.raw`\(x^2=1\)`+'\n\n<img src="https://invalid.example/picture" onerror="window.__diagnosisUnsafe=true">',quote,next_step:'先核对'+String.raw`\(x\ne0\)`+'的适用条件。'};
 const grade={scores:[80],diagnostics:[diagnosis]};
 function assert(ok,text){if(!ok)throw Error(text);checks.push(text);}
 function paint(s,g){host.innerHTML=practiceAfterSubmission(s,{grade:g});renderPracticeDiagnostics(host,g);}
 try{
  paint(set,grade);assert(host.querySelectorAll('.katex').length===2,'teacher prose renders both math fields');
  assert(host.querySelector('[data-diagnosis-field=reason] strong')?.textContent==='方法依据','Markdown emphasis renders in the teacher explanation');
  assert(host.querySelector('blockquote').textContent===quote&&!host.querySelector('blockquote b'),'student quotation remains literal');
  assert(!host.querySelector('img,script,iframe,form')&&!window.__diagnosisUnsafe,'untrusted teacher markup remains inert');
  const code='```python\nif a < b:\n    return "$x$", a * b\n```';
  paint(set,{...grade,diagnostics:[{...diagnosis,reason:code}]});
  assert(host.querySelector('pre code')?.textContent.includes('return "$x$", a * b')&&!host.querySelector('pre .katex'),'teacher code fences preserve operators and literal dollar signs');
  paint(set,grade);
  assert(Boolean(host.querySelector('[data-practice-tutor]'))&&!host.querySelector('[data-homework-read]'),'legacy records retain their existing follow-up control');
  paint({...set,homework:{id:'native',repair_available:false}},grade);
  assert(Boolean(host.querySelector('[data-homework-read="native"]'))&&!host.querySelector('[data-practice-tutor]'),'native records select the precise submitted-work reader');
  paint(set,{...grade,scores:[100]});assert(!host.querySelector('[data-practice-diagnosis]'),'full credit does not display an invented error diagnosis');
  paint(set,{...grade,grading_verification_required:true});assert(!host.querySelector('[data-practice-diagnosis]'),'unverified grades withhold diagnostic content');
  paint(set,{...grade,diagnostics:{invalid:'old data'}});assert(!host.querySelector('[data-practice-diagnosis]'),'malformed historical diagnostics do not crash the exercise page');
  return {passed:true,cases:checks};
 }finally{host.remove();}
}.toString()+')()');
