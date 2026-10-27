/* Optional fixed scaffolds. Only an explicit click records a request. */
(()=>{
  'use strict';
  const labels={terminology:'术语与概念',prerequisites:'需要先学的知识',motivation:'为什么这样设式或构造',method_selection:'怎样选择解题方法',argumentation:'证明的步骤',implementation:'计算或代码实现',unknown:'还不确定卡点'};
  const node=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
  function append(host,worksheet,question,adapter){
    if(!host||worksheet.status!=='assigned'||worksheet.homework||worksheet.questions[0]?.language)return;
    const usage=new Map(),cache=new Map();let sequence=0,busy=false;
    for(const entry of worksheet.practice?.hint_usage||[]){if(entry.question_index===question.index&&labels[entry.kind])usage.set(entry.kind,Math.max(usage.get(entry.kind)||0,entry.level));}
    const panel=node('details',undefined,'practice-scaffold');panel.dataset.practiceHint=question.index;panel.dataset.setId=worksheet.id;
    const summary=node('summary','通用思考提示'),body=node('div',undefined,'practice-scaffold-body');
    const label=node('label','你卡在哪一方面？'),select=node('select');select.setAttribute('aria-label','第'+(question.index+1)+'题提示方向');
    for(const [key,text]of Object.entries(labels)){const option=node('option',text);option.value=key;select.append(option);}
    select.value=[...usage.entries()].sort((a,b)=>b[1]-a[1])[0]?.[0]||'unknown';label.append(select);
    const actions=node('div',undefined,'practice-scaffold-actions'),next=node('button'),previous=node('div',undefined,'practice-scaffold-previous');next.type='button';
    const status=node('p','','practice-scaffold-status');status.setAttribute('role','status');
    const hint=node('p','','practice-scaffold-text');hint.hidden=true;
    const note=node('p','这些是帮助你继续思考的通用提示，不含本题答案。只有点开提示才记录使用情况；查看提示不会直接扣分。','practice-scaffold-note');
    const alive=()=>panel.isConnected&&(!adapter.active||adapter.active());
    function paint(){
      const level=usage.get(select.value)||0;summary.textContent='通用思考提示'+(usage.size?' · 已记录使用':'');
      next.textContent=level<3?'展开第 '+(level+1)+' 条提示':'再看第 3 条提示';next.disabled=busy;previous.replaceChildren();
      for(let n=1;n<=level;n++){const button=node('button','查看第 '+n+' 条提示');button.type='button';button.disabled=busy;button.onclick=()=>show(n);previous.append(button);}
    }
    async function show(level){
      if(busy||!alive())return;
      const kind=select.value,key=kind+':'+level,token=++sequence,saved=cache.get(key);
      if(saved){hint.textContent=saved;hint.hidden=false;status.textContent='已记录请求过第 '+level+' 条提示；可回到答题框继续尝试。';return;}
      busy=true;status.textContent='正在读取通用提示…';paint();
      try{
        const result=await adapter.api('/api/exercises/'+worksheet.id+'/hint',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question_index:question.index,kind,level})});
        cache.set(key,result.hint);usage.set(kind,Math.max(usage.get(kind)||0,result.level));
        worksheet.practice??={};worksheet.practice.hint_usage=(worksheet.practice.hint_usage||[]).filter(x=>x.question_index!==question.index||x.kind!==kind);
        worksheet.practice.hint_usage.push({question_index:question.index,kind,level:usage.get(kind)});
        if(!alive()||token!==sequence||select.value!==kind)return;
        hint.textContent=result.hint;hint.hidden=false;status.textContent='已记录请求过第 '+result.level+' 条提示；可回到答题框继续尝试。';
      }catch(error){if(alive()&&token===sequence&&select.value===kind)status.textContent=error.message;}
      finally{busy=false;if(alive())paint();}
    }
    next.onclick=()=>show(Math.min(3,(usage.get(select.value)||0)+1));
    select.onchange=()=>{sequence++;hint.hidden=true;status.textContent='切换方向不记录使用；展开提示时才记录。';paint();};
    actions.append(next,previous);body.append(label,actions,status,hint,note);panel.append(summary,body);host.append(panel);paint();return panel;
  }
  window.studyforgePracticeHints={append};
})();
