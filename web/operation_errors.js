/* Shared presentation only. Never retry, alter a grade, or persist learning data. */
((root,factory)=>{const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;else root.studyforgeOperationErrors=api;})(typeof window==='undefined'?globalThis:window,root=>{
  'use strict';
  const remembered=new Map(),MAX=8,LIMIT=16000;
  function rawText(value){
    if(value&&typeof value==='object'&&typeof value.message==='string')return value.message;
    if(typeof value==='string')return value;
    try{return JSON.stringify(value)||'没有收到具体错误信息';}catch{return '错误信息无法完整读取';}
  }
  function redact(value){
    return String(value).replace(/(\bauthorization\s*["']?\s*[:=]\s*["']?)(?:Bearer\s+|Basic\s+)?(?:\[(?:密钥)?已隐藏\]|[^\s"'<>,}\]]+)/gi,'$1[已隐藏]')
      .replace(/\bBearer\s+(?:\[(?:密钥)?已隐藏\]|[^\s"'<>,}\]]+)/gi,'Bearer [已隐藏]')
      .replace(/\b(?:sk-[A-Za-z0-9_-]{10,}|AIza[A-Za-z0-9_-]{15,})\b/g,'[密钥已隐藏]')
      .replace(/((?:api[_-]?key|access[_-]?token|refresh[_-]?token|pairing[_-]?code|secret|authorization)\s*["']?\s*[:=]\s*["']?)(?:\[(?:密钥)?已隐藏\]|[^\s"'&,}\]]+)/gi,'$1[已隐藏]')
      .replace(/([?#&](?:pair|token|key|code|auth|password)=)[^&#\s]+/gi,'$1[已隐藏]')
      .replace(/(https?:\/\/)[^\s/@:]+:[^\s/@]+@/gi,'$1[登录信息已隐藏]@');
  }
  function describe(error,context={}){
    const clean=redact(rawText(error)),raw=clean.length>LIMIT?clean.slice(0,LIMIT)+'\n[错误信息较长，只显示前 '+LIMIT+' 字]':clean;
    const status=Number(context.status??error?.status)||null,path=String(context.path??error?.requestPath??'').split('?')[0];
    let kind='unknown',title='这次操作没有完成',message='',steps=[];
    // An explicit application instruction takes precedence over a generic HTTP status.
    if(/完整提交前|提交.*前.*(?:答案|解析)|不开放.*答案|先.*提交.*(?:作业|答案)/.test(raw)){
      kind='answers_locked';title='提交作业后才能查看解析';message='这份题单的参考答案还没有开放。';
      steps=['先完成并提交这份题单；不会的题可以写下卡住的位置。','提交后再查看答案解析和导师批改。'];
    }else if(/只读|等待.*审批|需要.*审批|未获.*授权|没有.*(?:读取|写入|修改|删除)权限/.test(raw)){
      kind='permission';title='这项操作需要相应权限';message='请先查看具体操作和当前文件权限。';
      steps=['需要审批时，在审批卡上选择允许或拒绝，任务会按你的选择继续。','只读模式不能修改文件；确实需要修改时，再调整聊天框中的权限。'];
    }else if(/习题.*(?:审查|检查|修订).*?(?:未通过|实质问题)|编程作业题意有待核实|独立解题未通过/.test(raw)){
      kind='exercise_check';title='这套题还没有通过检查';message='题目暂未发布，下面保留了具体检查问题。';
      steps=['先查看错误详情，确认是哪道题或哪项条件有问题。','可以调整出题要求后重新生成；不要把未通过检查的题目当作已核实的作业。'];
    }else if(status===429||/Too Many Requests|rate.?limit|responseTooManyFailedAttempts|\b(?:HTTP|status)\s*[:=]?\s*429\b|httpStatusCode["']?\s*:\s*429/i.test(raw)){
      kind='rate_limit';title='AI 服务暂时限制了请求';message='服务当前没有接受这次请求，不代表资料或作答出错。';
      steps=['先等待服务允许再次请求；如果有明确的等待时间，按服务提示操作。','减少同一服务同时处理的任务，避免连续点击重试。','稍后从原任务或原对话重试；这里不会自动发送新请求。'];
    }else if(/insufficient_quota|quota.?exceeded|余额不足|额度.*(?:不足|耗尽)|credit balance/i.test(raw)){
      kind='quota';title='AI 服务的可用额度不足';message='请到所选模型服务中查看额度或账户状态。';
      steps=['确认工作台当前使用哪个 AI 服务和模型。','到该服务查看可用额度，或手动换成另一个已配置的服务后再试。'];
    }else if(context.transport==='local'||/无法连接电脑|Failed to fetch|NetworkError when attempting to fetch|Load failed/i.test(raw)){
      kind='local_connection';title='暂时连不上电脑上的学习服务';message='页面还在，但这次没有连到处理任务的电脑服务。';
      steps=['确认电脑已开机、没有睡眠，StudyForge 仍在运行或托盘中。','手机请使用电脑“连接手机”中显示的当前地址；跨网络时检查两端 Tailscale。','恢复连接后重新打开页面，先查看原任务进度，避免重复生成。'];
    }else if(/ConnectError|ConnectTimeout|ReadTimeout|ECONNREFUSED|ETIMEDOUT|TLS|certificate verify failed/i.test(raw)){
      kind='service_connection';title='连接模型或资料网站时失败';message='仅凭这条错误还不能确定是网络、服务地址还是证书问题。';
      steps=[path.includes('/import')?'先在浏览器确认该网址能打开；需要登录或验证时，可尝试“浏览器读取”。':'到“设置与联动 → 模型与语音”检测所选 AI 的连接，并核对服务地址。','如果其他任务仍能正常完成，先保留原任务和错误信息，稍后再试。'];
    }else if(/无法排版公式|公式.*(?:排版失败|无法排版)/.test(raw)){
      kind='formula';title='有一条公式无法排版';message='文件尚未成功导出，请在错误详情中查看具体公式。';
      steps=['可以在原对话指出这条公式，请导师核对写法后再导出。','急需阅读时，可以选择另一种输出格式；格式改变不代表公式已经核对正确。'];
    }else if(/JSONDecodeError|Expecting value|Unexpected token.*JSON|Invalid.*escape|JSON.*(?:不完整|无法解析|格式错误)/i.test(raw)){
      kind='response_format';title='返回内容的格式不完整或不符合要求';message='这次结果还不能交付，不应把它当作已经完成。';
      steps=['先查看原任务是否正在自动重试，避免重复发起相同任务。','任务已失败时，页面有“继续”或“重试”入口就使用它；没有入口时，回原对话保留资料和要求，再发起一次。','反复出现时，请保留错误详情和当前服务、模型名称。'];
    }else if(status===401&&context.mobileSession){
      kind='pairing';title='这台手机需要重新连接';message=/[\u4e00-\u9fff]/.test(raw)?raw.slice(0,220):'手机的连接状态已失效。';
      steps=['在电脑顶部打开“连接手机”，确认服务已开启。','用当前网址和配对码重新连接，在电脑上批准这台设备。'];
    }else if(status===403&&/[\u4e00-\u9fff]/.test(raw)&&!path.includes('/import')){
      kind='application_rule';title='这项操作暂时未被允许';message=raw.slice(0,220);
      steps=['先按这条提示检查需要满足的条件，再继续操作。','如果提示与实际情况不符，保留错误详情供排查，避免反复提交同样的请求。'];
    }else if(status===401||/invalid.?api.?key|unauthorized|authentication failed/i.test(raw)){
      kind='authentication';title='登录或访问凭证未通过';message=/[\u4e00-\u9fff]/.test(raw)?raw.slice(0,220):'所选服务没有接受当前的登录状态或 API 密钥。';
      steps=['检查所选服务是否需要重新登录，或重新填写服务商提供的 API 密钥。','不要把密钥粘贴到聊天或问题反馈中。'];
    }else if(status===403||status===412||/403 Forbidden|412 Precondition Failed/i.test(raw)){
      kind='access_denied';title='网站或服务拒绝了这次访问';message=/[\u4e00-\u9fff]/.test(raw)?raw.slice(0,220):'网址存在，也可能因为登录、验证或访问规则而无法读取。';
      steps=['如果是在导入网址，先在浏览器确认能够阅读完整内容，再尝试“浏览器读取”。','如果是模型服务，请检查账户是否有权使用所选模型。'];
    }else if(status===422){
      kind='input';title='有一项填写内容需要调整';message='这次提交未被接受，请检查当前表单。';
      steps=['检查必填项、页码范围、网址或模型名称，按输入框旁的说明修改。','具体字段保留在错误详情里；修改后再提交。'];
    }else{
      message=/[\u4e00-\u9fff]/.test(raw)?raw.slice(0,220):'暂时无法确定具体原因，可以展开错误原文供排查。';
      steps=['先按当前页面的提示检查填写内容和任务状态。','仍无法完成时，反馈你点击的按钮、所用服务和下方错误信息。'];
    }
    return {kind,title,message,steps,raw,status,path};
  }
  function capture(error,context={}){
    if(error?.name==='AbortError')return error;
    const result=error instanceof Error&&Object.isExtensible(error)?error:new Error(rawText(error));
    if(context.status!=null)result.status=context.status;
    if(context.path)result.requestPath=context.path;
    const info=!Object.keys(context).length&&result.operationInfo?result.operationInfo:describe(result,context);result.operationInfo=info;
    const key=redact(rawText(result)).slice(0,LIMIT);remembered.delete(key);remembered.set(key,info);
    while(remembered.size>MAX)remembered.delete(remembered.keys().next().value);
    return result;
  }
  const infoFor=value=>value?.steps&&value?.raw?value:value?.operationInfo||remembered.get(redact(rawText(value)).slice(0,LIMIT))||describe(value);
  const summary=value=>{const info=infoFor(value);return info.kind==='unknown'&&/[\u4e00-\u9fff]/.test(info.raw)?info.message.replace(/^(?:RuntimeError|TypeError|ValueError|Error):\s*/,''):info.title;};
  let dialog,body,title,opener;
  const node=(tag,text,cls)=>{const el=root.document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
  function ensure(){
    if(dialog)return;
    dialog=node('dialog',null,'operation-error-dialog');dialog.id='operationErrorDialog';dialog.setAttribute('aria-labelledby','operationErrorTitle');
    const header=node('header');title=node('h2','这次操作没有完成');title.id='operationErrorTitle';const close=node('button','关闭');close.type='button';close.onclick=()=>dialog.close();header.append(title,close);
    body=node('div',null,'operation-error-body');dialog.append(header,body);root.document.body.append(dialog);
    dialog.addEventListener('close',()=>{if(opener?.isConnected)opener.focus({preventScroll:true});opener=null;});
  }
  async function copy(pre,status){
    const text=pre.textContent;
    try{if(typeof root.copyText==='function')await root.copyText(text);else if(root.navigator?.clipboard?.writeText)await root.navigator.clipboard.writeText(text);else throw Error('No clipboard');status.textContent='错误信息已复制，可在反馈问题时使用。';}
    catch{const selection=root.getSelection(),range=root.document.createRange();range.selectNodeContents(pre);selection.removeAllRanges();selection.addRange(range);status.textContent='浏览器没有允许自动复制。已选中错误信息，请按 Ctrl+C，或在手机长按复制。';}
  }
  function open(value){
    const info=value?.steps?value:infoFor(value);ensure();opener=root.document.activeElement;title.textContent=info.title;body.replaceChildren();
    body.append(node('p',info.message));const list=node('ol');for(const step of info.steps)list.append(node('li',step));body.append(list);
    const detail=node('details',null,'operation-error-raw'),label=node('summary','错误原文（排查时使用）'),pre=node('pre',info.raw),button=node('button','复制错误信息'),status=node('p','','operation-copy-status');
    pre.tabIndex=0;button.type='button';button.onclick=()=>copy(pre,status);status.setAttribute('role','status');detail.append(label,pre,button,status);body.append(detail);
    body.append(node('p','这里仅提供处理说明，不会重试任务、修改文件或发送资料。','operation-error-note'));
    if(!dialog.open)dialog.showModal();return dialog;
  }
  function attach(host,error){
    if(!host||!error)return;
    const button=node('button','查看处理办法与错误详情','operation-error-action');button.type='button';
    button.onclick=()=>open(error);host.append(button);return button;
  }
  function decorateToast(host,text){
    if(!host)return;
    host.querySelectorAll('.operation-error-action').forEach(e=>e.remove());
    const info=remembered.get(redact(rawText(text)).slice(0,LIMIT));if(!info)return;
    const message=host.querySelector('.toast-message');if(message)message.textContent=summary(info);else host.textContent=summary(info);
    const button=attach(host,info),close=host.querySelector('.toast-close');if(close)close.before(button);
    button.onclick=()=>{open(info);if(typeof root.dismissToast==='function')root.dismissToast();else{if(host.hidePopover&&host.matches(':popover-open'))host.hidePopover();host.hidden=true;}};
  }
  return {describe,redact,capture,summary,open,attach,decorateToast};
});
