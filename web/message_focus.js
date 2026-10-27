/* Explicit AI passage references. Reading/selecting is local; send asks tutor. */
(() => {
 'use strict';
 const phone=typeof mobile!=='undefined',scope=()=>phone?{project:mobile.project?.id,chat:mobile.chat?.id}:{project:state.project?.id,chat:state.conversation};
 const key=s=>'sfMessageReference:'+s.project+':'+s.chat;
 const load=s=>{try{return JSON.parse(localStorage.getItem(key(s)))||null;}catch{return null;}};
 const store=(s,value)=>{try{if(value)localStorage.setItem(key(s),JSON.stringify(value));else localStorage.removeItem(key(s));}catch{toast('引用草稿无法保存，请检查浏览器存储。');}};
 const same=(a,b)=>a.project===b.project&&a.chat===b.chat;
 const dialog=document.createElement('dialog');dialog.id='messageFocusDialog';dialog.className='message-focus-dialog';dialog.setAttribute('aria-labelledby','messageFocusTitle');
 dialog.innerHTML='<header><div><span>选一句话，问清楚</span><h2 id="messageFocusTitle">选中导师原话再提问</h2></div><button type="button" data-focus-close aria-label="关闭原句选择">✕</button></header><p>先选中不懂的那句话，点“使用选中原句”，再回输入框写下问题并发送。只打开这个窗口不会请求 AI。</p><div class="message-focus-view-tools" role="group" aria-label="回答显示方式"><button type="button" data-focus-rendered aria-pressed="true">正常阅读（显示公式）</button><button type="button" data-focus-source aria-pressed="false">查看排版原文（Markdown）</button><small>选到公式或代码时，会保留它的完整内容，避免只引用半个公式。</small></div><p data-focus-range></p><div data-focus-preview class="message-focus-reading" tabindex="0" role="document" aria-label="导师回答，支持选取原句与完整公式"></div><textarea hidden readonly rows="9" spellcheck="false" aria-label="导师回答原文，可选取具体原句" data-focus-text></textarea><div class="message-focus-paging"><button type="button" data-focus-prev>上一段</button><button type="button" data-focus-next>下一段</button><label>跳到第几个字<input type="number" min="1" value="1" data-focus-offset></label><button type="button" data-focus-jump>前往</button></div><p data-focus-status role="status"></p><footer><button type="button" data-focus-whole>引用整条回答</button><button type="button" class="primary" data-focus-select>使用选中原句</button></footer>';
 document.body.append(dialog);const find=n=>dialog.querySelector('[data-focus-'+n+']');
 const banner=document.createElement('div');banner.className='message-focus-banner';banner.hidden=true;banner.setAttribute('aria-label','本次追问引用');
 const title=document.createElement('strong');title.textContent='选中导师原话再提问';const preview=document.createElement('blockquote');
 const actions=document.createElement('div'),change=document.createElement('button'),clear=document.createElement('button');change.type=clear.type='button';change.textContent='查看／修改';clear.textContent='取消引用';actions.append(change,clear);banner.append(title,preview,actions);$('prompt').before(banner);
 let currentScope='',currentStamp='',target=null,windowData=null,revision=0,viewMode='rendered';
 function mode(value){viewMode=value;find('preview').hidden=value!=='rendered';find('text').hidden=value!=='source';find('rendered').setAttribute('aria-pressed',String(value==='rendered'));find('source').setAttribute('aria-pressed',String(value==='source'));window.getSelection()?.removeAllRanges();}
 function changed(force=false){const s=scope(),id=key(s),value=load(s),stamp=JSON.stringify(value);if(!force&&id===currentScope&&stamp===currentStamp)return;
  if(id!==currentScope&&dialog.open){revision++;dialog.close();target=null;windowData=null;}
  currentScope=id;currentStamp=stamp;banner.hidden=!value;if(value)renderLessonText(preview,value.preview);
 }
 function attach(node){const row=node.exportMessage;if(!row)return;
  if(row.role==='user'&&row.reply_reference&&!node.querySelector('.message-focus-history')){
   const ref=row.reply_reference,box=document.createElement('details');box.className='message-focus-history';const label=document.createElement('summary');label.textContent='本条问题引用了导师原句';const quote=document.createElement('blockquote');renderLessonText(quote,ref.selection?.text||ref.excerpt);box.append(label,quote);node.querySelector('.message-content,.plain-text')?.before(box);return;
  }
  if(row.role!=='assistant'||!row.content.trim()||row.content.trimEnd().endsWith('[本次回复已停止，以上内容尚未完成。]')||node.querySelector('[data-followup-message]'))return;
  let buttons=node.querySelector('.message-save-actions');if(!buttons){buttons=document.createElement('div');buttons.className='message-save-actions';node.append(buttons);}
  const button=document.createElement('button');button.type='button';button.dataset.followupMessage=row.id;button.textContent='针对这段追问';button.title='选择这条回答的具体原句，再写自己的疑问';button.onclick=()=>open(row);buttons.prepend(button);
 }
 async function read(offset=0){if(!target)return;const picked=target,token=++revision;find('status').textContent='正在读取已保存的回答，不调用 AI…';
  try{const query=new URLSearchParams({project_id:picked.projectId,conversation_id:picked.conversationId,offset:String(offset)});let data=await api('/api/messages/'+encodeURIComponent(picked.id)+'/passage?'+query);
   if(offset===0&&data.total<=7000&&data.next_offset!==null){query.set('offset',String(data.next_offset));const tail=await api('/api/messages/'+encodeURIComponent(picked.id)+'/passage?'+query);if(tail.content_sha256!==data.content_sha256||tail.offset!==data.end||tail.total!==data.total)throw Error('这条回答已更新。请关闭后重新打开，再选原句；你写的问题会保留。');data={...data,text:data.text+tail.text,end:tail.end,next_offset:tail.next_offset};}
   if(token!==revision||target!==picked||!same(scope(),{project:picked.projectId,chat:picked.conversationId}))return;
   windowData=data;find('text').value=data.text;studyforgeSourceSelection.render(find('preview'),data.text);find('range').textContent=`第 ${data.offset+1}–${data.end} 字符，共 ${data.total} 字符。这是导师之前的回答，可能有错；引用它是为了方便提问。`;
   find('offset').value=data.offset+1;find('offset').max=data.total;find('prev').disabled=data.previous_offset===null;find('next').disabled=data.next_offset===null;find('whole').disabled=data.total>7000;
   find('status').textContent=data.total>7000?'回答较长，请只选不懂的那一段，最多 3000 字符。':'可以引用整条回答，也可以只选一段（最多 3000 字符）。选好后，回输入框写下问题并发送。';
  }catch(error){if(token===revision)find('status').textContent=error.message;}
 }
 function open(row){if(!same(scope(),{project:row.projectId,chat:row.conversationId}))return toast('请先切回这条回答所属的对话。');target=row;windowData=null;find('text').value='';find('preview').replaceChildren();mode('rendered');find('whole').disabled=true;if(!dialog.open)dialog.showModal();read(0);}
 function use(selection){if(!target||!windowData||!same(scope(),{project:target.projectId,chat:target.conversationId}))return;
  const s=scope(),reference={message_id:target.id,content_sha256:windowData.content_sha256,selection,preview:selection?.text||windowData.text.slice(0,360)};
  store(s,reference);dialog.close();changed(true);$('prompt').focus();toast('原句已选好。现在写下你不懂什么，再点“发送”。');
 }
 find('select').onclick=()=>{if(!windowData)return;let start,end,text;
  if(viewMode==='rendered'){try{({start,end,text}=studyforgeSourceSelection.selection(find('preview')));}catch(error){find('status').textContent=error.message;return;}}
  else{const area=find('text');function boundary(n){let raw=0,shown=0;while(shown<n&&raw<windowData.text.length){raw+=windowData.text[raw]==='\r'&&windowData.text[raw+1]==='\n'?2:1;shown++;}return raw;}start=boundary(area.selectionStart);end=boundary(area.selectionEnd);text=windowData.text.slice(start,end);}
  if(!text.trim()||Array.from(text).length>3000){find('status').textContent='请先在原文中选取 1–3000 个字符。';return;}
  use({start:windowData.offset+Array.from(windowData.text.slice(0,start)).length,end:windowData.offset+Array.from(windowData.text.slice(0,end)).length,text});
 };
 find('whole').onclick=()=>{if(windowData&&windowData.total<=7000)use(null);};
 find('rendered').onclick=()=>mode('rendered');find('source').onclick=()=>mode('source');
 find('prev').onclick=()=>{if(windowData?.previous_offset!==null&&windowData)read(windowData.previous_offset);};find('next').onclick=()=>{if(windowData?.next_offset!==null&&windowData)read(windowData.next_offset);};
 find('jump').onclick=()=>{const n=Number(find('offset').value);if(!Number.isSafeInteger(n)||n<1||n>(windowData?.total||0)){find('status').textContent='请填写回答范围内的位置。';return;}read(n-1);};
 find('offset').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();e.stopPropagation();find('jump').click();}};
 find('close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{revision++;});
 clear.onclick=()=>{store(scope(),null);changed(true);};change.onclick=()=>{const s=scope(),ref=load(s);if(ref)open({id:ref.message_id,projectId:s.project,conversationId:s.chat});};
 window.studyforgeMessageFocus={attach,changed,
  capture(project,chat){const ref=load({project,chat});return ref?{message_id:ref.message_id,content_sha256:ref.content_sha256,selection:ref.selection}:null;},
  sent(request){const s={project:request.project_id,chat:request.conversation_id},old=load(s),ref=request.reply_reference;
   if(old&&ref&&old.message_id===ref.message_id&&old.content_sha256===ref.content_sha256&&JSON.stringify(old.selection)===JSON.stringify(ref.selection))store(s,null);changed();}
 };
 document.querySelectorAll('[data-export-message]').forEach(attach);changed();
})();
