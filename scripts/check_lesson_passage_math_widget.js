/* Production widget under bounded local transports; no model or real data. */
module.exports=async function(win){return win.webContents.executeJavaScript('('+async function(){
 const checks=[],hosts=[],tick=()=>new Promise(r=>setTimeout(r,10));
 function assert(value,message){if(!value)throw Error(message);}
 function make(text,change=()=>{},transport){
  const h=document.createElement('div');document.body.append(h);hosts.push(h);
  let section='s';const calls=[],api=transport||(async url=>{
   const n=Number(new URL(url,location.origin).searchParams.get('offset'));calls.push(n);
   return {section_id:'s',document_sha256:'fixed',offset:n,end:Math.min(n+4000,Array.from(text).length),total:Array.from(text).length,
     text:Array.from(text).slice(n,n+4000).join(''),previous_offset:n?Math.max(0,n-4000):null,next_offset:n+4000<Array.from(text).length?n+4000:null};
  });
  const control=studyforgeLessonPassage.create(h,{getId:()=> 'local',getSection:()=>section,api,onChange:change});control.setSection(section);
  return {h,control,calls,set(value){section=value;control.setSection(value);},find:n=>h.querySelector('[data-passage-'+n+']')};
 }
 try{
  const raw='😀重复原句。\r\n\r\n**重复原句。**\r\n\r\n'+String.raw`\(x^2+y^2\)`+'\r\n\r\n```js\nconst x=2;\n```';
  let changes=0;const a=make(raw,()=>changes++);a.find('open').click();await tick();
  assert(a.find('source-label').hidden&&!a.find('preview').hidden,'Reading must be the default');
  const repeat=[...a.h.querySelectorAll('[data-source-fragment]')].filter(e=>e.textContent==='重复原句。').at(-1);
  const range=document.createRange();range.selectNodeContents(repeat);getSelection().removeAllRanges();getSelection().addRange(range);a.find('use').click();
  const chosen=a.control.value();assert(chosen.start===Array.from(raw.slice(0,raw.lastIndexOf('重复原句。'))).length&&chosen.text==='重复原句。','Repeated sentence must bind to the selected occurrence');
  checks.push('rendered repeated text preserves the selected occurrence and Unicode coordinates');
  const math=a.h.querySelector('[data-passage-preview] .katex-html'),part=math.querySelector('.mord')||math;
  range.selectNodeContents(part);getSelection().removeAllRanges();getSelection().addRange(range);a.find('use').click();
  assert(a.control.value().text===String.raw`\(x^2+y^2\)`&&a.find('quote').querySelector('.katex'),'An equation fragment must cite its complete source');checks.push('formula and quote preview preserve complete raw math');
  a.find('source').click();assert(!a.find('source-label').hidden&&a.find('preview').hidden,'Source switch');
  const area=a.find('text'),first=area.value.indexOf('重复原句。');area.setSelectionRange(first,first+'重复原句。'.length);a.find('use').click();
  assert(a.control.value().start===1&&a.control.value().text==='重复原句。','Source mode counts one emoji, not two UTF16 units');checks.push('source mode remains exact beside emoji and CRLF');
  const saved=a.control.value();a.find('rendered').click();assert(JSON.stringify(a.control.value())===JSON.stringify(saved),'A view switch cannot discard a citation');
  a.find('clear').click();assert(a.control.value()===null&&changes===4,'Only explicit selections and clear notify drafts');checks.push('switching views preserves a chosen citation; clear affects only the optional quote');
  const table=make('| A | B |\n|---|---|\n| uncertain | cell |');table.find('open').click();await tick();
  const td=table.h.querySelector('td');range.selectNodeContents(td);getSelection().removeAllRanges();getSelection().addRange(range);table.find('use').click();
  assert(table.control.value()===null&&table.find('status').textContent.includes('原文'),'Unmappable table must require source mode');checks.push('ambiguous table selections fail closed with source-mode instructions');
  const short=make('正文。'.repeat(1500));short.find('open').click();await tick();await tick();
  assert(short.calls.join(',')==='0,4000'&&short.find('next').disabled,'Short proofs require no more than two bounded reads');checks.push('short sections join only two adjacent windows');
  const long=make('正文。'.repeat(3000));long.find('open').click();await tick();
  assert(long.calls.join(',')==='0'&&!long.find('next').disabled,'Long chapters must stay paged');checks.push('long chapters stay bounded without fetching the full section');
  long.find('preview').scrollTop=150;long.find('next').click();await tick();
  assert(long.find('preview').scrollTop===0,'A new reading window must start at its beginning');checks.push('paging opens the beginning of the new window');
  let resolve;const stale=make('',()=>{},()=>new Promise(r=>resolve=r));stale.find('open').click();
  assert(stale.find('use').disabled&&stale.find('jump').disabled,'Pending reads cannot use a stale selection');stale.set('new');
  resolve({text:'OLD_RESPONSE',offset:0,end:12,total:12,previous_offset:null,next_offset:null});await tick();
  assert(stale.find('reader').hidden&&!stale.find('preview').textContent.includes('OLD_RESPONSE'),'Late old responses must not repaint a new section');checks.push('pending controls and section changes protect against stale reads');
  let revisionCalls=0;const conflict=make('',()=>{},async()=>++revisionCalls===1?{section_id:'s',document_sha256:'old',offset:0,end:4000,total:4100,text:'a'.repeat(4000),previous_offset:null,next_offset:4000}:{section_id:'s',document_sha256:'new',offset:4000,end:4100,total:4100,text:'b'.repeat(100),previous_offset:0,next_offset:null});
  conflict.find('open').click();await tick();
  assert(conflict.find('use').disabled&&conflict.find('reader').hidden&&conflict.find('status').textContent.includes('不同版本'),'Different versions must never be joined');checks.push('document revision changes cannot be merged');
  return {passed:true,cases:checks,external_model_requests:0};
 }finally{getSelection()?.removeAllRanges();hosts.forEach(h=>h.remove());}
}.toString()+')()');};
