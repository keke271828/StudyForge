/* The same controls and request accounting on desktop and paired phone. */
(() => {
  'use strict';
  const anchor=document.getElementById('bookSearch');if(!anchor)return;
  const state={ready:false,dirty:false,saving:false,loading:false,revision:0};
  const box=document.createElement('details');box.id='bookPolicyBox';box.className='book-semantic-box book-policy-box';
  box.innerHTML='<summary>后台阅读安排 <span id="bookPolicyBadge">检查中</span></summary><form id="bookPolicyForm"><label class="book-policy-check"><input id="bookWindowEnabled" type="checkbox">只在指定时间后台阅读</label><div class="book-policy-times"><label>开始<input id="bookWindowStart" type="time" value="00:00" required></label><label>结束<input id="bookWindowEnd" type="time" value="00:00" required></label></div><div id="bookWindowDays" class="book-policy-days" role="group" aria-label="可阅读的星期"></div><p class="small-note">按电脑上的时间设置。开始和结束相同表示全天；例如周一 22:00 到 02:00，会读到周二凌晨。</p><label>后台阅读每天最多用多少 token？（填 0 表示不限）<input id="bookDailyTokens" type="number" min="0" max="50000000" step="1" value="0" required></label><p class="small-note">token 是 AI 计算文字用量的单位，输入和输出都算。达到上限会保留进度，通常次日继续；聊天、生成文档和找目录不受这个后台阅读限额影响。</p><button id="bookPolicySave" type="submit" disabled>保存阅读安排</button></form><p id="bookPolicyStatus" class="small-note" role="status"></p><progress id="bookPolicyUsage" max="100" value="0" hidden></progress><details class="book-policy-history"><summary>最近请求与用量</summary><div id="bookPolicyHistory"></div></details>';
  const controls=document.getElementById('bookShelfControls');
  if(controls)controls.append(box);else anchor.before(box);
  const $p=id=>box.querySelector('#'+id),form=$p('bookPolicyForm');
  const days=$p('bookWindowDays');['一','二','三','四','五','六','日'].forEach((day,index)=>{
    const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=index;input.checked=true;input.setAttribute('aria-label','星期'+day);label.append(input,document.createTextNode(day));days.append(label);
  });
  const number=value=>Number(value||0).toLocaleString('zh-CN');
  function toggleWindow(){const disabled=!state.ready||!$p('bookWindowEnabled').checked;for(const input of [...box.querySelectorAll('input[type=time]'),...days.querySelectorAll('input')])input.disabled=disabled;for(const id of ['bookWindowEnabled','bookDailyTokens'])$p(id).disabled=!state.ready;}
  form.addEventListener('input',()=>{state.dirty=true;state.revision++;toggleWindow();});
  function render(value,replace=false){
    const {settings:s,usage:u}=value;state.ready=true;
    if(replace||!state.dirty){$p('bookWindowEnabled').checked=s.window_enabled;$p('bookWindowStart').value=s.start;$p('bookWindowEnd').value=s.end;$p('bookDailyTokens').value=s.daily_tokens;for(const day of days.querySelectorAll('input'))day.checked=s.weekdays.includes(Number(day.value));toggleWindow();}
    $p('bookPolicySave').disabled=state.saving;
    $p('bookPolicyBadge').textContent=value.wait?(value.wait.kind==='window'?'等待时段':'等待额度'):s.window_enabled||s.daily_tokens?'已设限制':'不限';
    $p('bookPolicyStatus').textContent='今日 '+value.day+' · 服务商统计 '+number(u.reported)+' token · 软件估算 '+number(u.estimated)+' · 进行中预计用量 '+number(u.reserved)+'。'+(s.daily_tokens?'预算剩余 '+number(value.remaining)+'。':'每日预算未限制。')+(u.uncertain?' 有 '+u.uncertain+' 次中断或未确认请求，暂按预计用量计算。':'')+(value.wait?value.wait.message+'。':'')+(value.wait?.next_at?' 下次可阅读时间：'+new Date(value.wait.next_at).toLocaleString()+'。':'');
    const progress=$p('bookPolicyUsage');progress.hidden=!s.daily_tokens;progress.value=s.daily_tokens?Math.min(100,(u.charged+u.reserved)/s.daily_tokens*100):0;
    const list=$p('bookPolicyHistory');list.replaceChildren();
    for(const request of value.recent){const item=document.createElement('p');item.textContent=(request.book_title||'已删除书籍的用量记录')+' · '+(request.model||request.provider)+' · '+(request.status==='inflight'?'预留 '+number(request.reserved_tokens):request.reported_tokens!==null?'服务商统计 '+number(request.reported_tokens):'估算 '+number(request.charged_tokens))+' token · '+new Date(request.started_at).toLocaleString();list.append(item);}
    if(!value.recent.length)list.textContent='还没有后台阅读用量。直接使用以前保存的阅读结果，不会再请求 AI。';
  }
  async function refresh(){
    if(typeof mobile!=='undefined'&&!mobile.authenticated)return;
    if(state.loading||state.saving)return;state.loading=true;const revision=state.revision;
    try{const value=await api('/api/library/policy');if(revision===state.revision)render(value);}
    catch(error){$p('bookPolicyStatus').textContent='读取安排失败：'+error.message;}
    finally{state.loading=false;}
  }
  form.onsubmit=async event=>{
    event.preventDefault();if(!state.ready||state.saving)return;
    const weekdays=[...days.querySelectorAll('input:checked')].map(input=>Number(input.value));
    if(!weekdays.length)return toast('至少保留一个可以阅读的星期。');
    state.saving=true;$p('bookPolicySave').disabled=true;const revision=++state.revision;
    const value={window_enabled:$p('bookWindowEnabled').checked,start:$p('bookWindowStart').value,end:$p('bookWindowEnd').value,weekdays,daily_tokens:Number($p('bookDailyTokens').value)};
    try{const result=await api('/api/library/policy',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});const unchanged=revision===state.revision;if(unchanged)state.dirty=false;render(result,unchanged);toast(unchanged?'已保存；后台从下一步按新安排运行。':'已保存此前设置；当前新修改尚未保存。');}
    catch(error){$p('bookPolicyStatus').textContent='保存失败：'+error.message;}
    finally{state.saving=false;$p('bookPolicySave').disabled=!state.ready;}
  };
  window.libraryPolicyRefresh=refresh;
  window.libraryPolicyOpen=()=>{box.open=true;box.scrollIntoView({block:'nearest'});refresh();};
  box.addEventListener('toggle',()=>{if(box.open)refresh();});toggleWindow();refresh();
})();
