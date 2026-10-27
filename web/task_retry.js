/* Shared retry status and explicit, deduplicated recovery of saved project tasks. */
(() => {
  const pending=new Map(),requests=new Map();
  function manual(api,row,projectId=row.project_id){
    const activeKey=projectId+':'+row.id;
    if(pending.has(activeKey))return pending.get(activeKey);
    const key=activeKey+':'+(row.updated_at||'');
    if(!requests.has(key)){requests.set(key,crypto.randomUUID().replaceAll('-',''));while(requests.size>40)requests.delete(requests.keys().next().value);}
    const operation=api('/api/jobs/'+encodeURIComponent(row.id)+'/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:projectId,request_id:requests.get(key)})}).finally(()=>pending.delete(activeKey));
    pending.set(activeKey,operation);return operation;
  }
  function summary(row, now = Date.now()) {
    const retry = row?.retry;
    if (!retry?.enabled) return '';
    const count = Number(retry.retry_count) || 0, limit = Number(retry.limit_count) || 5;
    if (retry.state === 'waiting') {
      const paused = ['paused','pausing'].includes(row.status);
      const seconds = retry.next_at ? Math.max(0, Math.ceil((Date.parse(retry.next_at)-now)/1000)) : 0;
      return `自动重试 ${count}/${limit} · ${paused ? '已暂停，继续后重试' : seconds > 0 ? `约 ${seconds} 秒后重试` : '排队等待 AI'} · 已完成步骤保留`;
    }
    if (retry.state === 'exhausted') return `自动重试 ${count}/${limit} 次仍未完成 · 请查看任务上的错误提示后再试`;
    if (retry.state === 'blocked') return `停止自动重试 · ${retry.reason || '需要处理错误原因'}`;
    if (count && row.status === 'completed') return `经过 ${count} 次自动重试完成`;
    if (count && ['running','queued'].includes(row.status)) return `第 ${count}/${limit} 次自动重试正在执行`;
    return '';
  }
  window.studyforgeTaskRetry = {summary,manual};
})();
