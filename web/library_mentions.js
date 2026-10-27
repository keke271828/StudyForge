/* Directory references in the composer. No model calls or implicit reading. */
(() => {
  'use strict';
  const phone = typeof mobile !== 'undefined';
  const prompt = document.getElementById('prompt');
  if (!prompt || !window.libraryReferenceOwner) return;
  const owner = () => window.libraryReferenceOwner();
  const same = expected => expected?.chat === owner().chat && expected?.project === owner().project;
  const states = {read:'AI已整理',unread:'尚未阅读',range_pending:'请确认页码'};
  const picker = {open:false,owner:null,trigger:null,rows:[],active:0,epoch:0,timer:null,busy:false,suppressed:null};
  const button = document.createElement('button');
  button.id='bookMentionButton';button.type='button';button.className=phone?'icon-button book-mention-button':'book-mention-button';
  button.textContent=phone?'@':'@ 书库';button.title='直接引用书籍章节';button.setAttribute('aria-label','搜索并引用书库节点');
  (phone?document.querySelector('.composer-tools'):document.querySelector('.composer-actions')).prepend(button);
  const chips=document.createElement('div');chips.id='bookComposerReferences';chips.className='book-composer-references';chips.hidden=true;
  prompt.after(chips);
  const panel=document.createElement('section');panel.id='bookMentionPicker';panel.className='book-mention-picker';
  panel.setAttribute('popover','manual');panel.setAttribute('aria-label','选择书库节点');panel.hidden=true;
  panel.innerHTML='<header><strong>引用书籍章节</strong><button type="button" data-mention-close aria-label="关闭节点选择器">✕</button></header><input id="bookMentionQuery" type="search" maxlength="160" placeholder="书名、章、节；可组合搜索" aria-label="搜索书名与目录路径"><div class="book-mention-options"><label>书籍<select id="bookMentionBook"><option value="">全部书籍</option></select></label><label>用途<select id="bookMentionPurpose"><option value="reference">参考背景</option><option value="primary">重点讲解对象</option></select></label></div><p id="bookMentionStatus" role="status"></p><div id="bookMentionResults" role="listbox" aria-label="书库目录候选"></div><footer>↑↓ 选择 · Enter 确认 · Esc 关闭<br>引用随本对话保存；移除下方标签即可取消。只查目录，不通读正文。</footer>';
  document.body.append(panel);
  const query=panel.querySelector('#bookMentionQuery'),book=panel.querySelector('#bookMentionBook'),purpose=panel.querySelector('#bookMentionPurpose');
  const status=panel.querySelector('#bookMentionStatus'),results=panel.querySelector('#bookMentionResults');
  function position(){
    if(!picker.open)return;
    const viewport=window.visualViewport, left=viewport?.offsetLeft||0,top=viewport?.offsetTop||0;
    const width=viewport?.width||innerWidth,height=viewport?.height||innerHeight,anchor=prompt.getBoundingClientRect();
    panel.style.width=Math.min(560,width-24)+'px';panel.style.maxHeight=Math.max(140,height-24)+'px';
    const rect=panel.getBoundingClientRect();
    panel.style.left=Math.max(left+12,Math.min(anchor.left,left+width-rect.width-12))+'px';
    panel.style.top=Math.max(top+12,Math.min(anchor.top-rect.height-8,top+height-rect.height-12))+'px';
  }
  function close(){
    picker.open=false;picker.epoch++;clearTimeout(picker.timer);
    if(panel.matches(':popover-open'))panel.hidePopover();panel.hidden=true;
    prompt.removeAttribute('aria-activedescendant');prompt.setAttribute('aria-expanded','false');
    query.removeAttribute('aria-activedescendant');button.setAttribute('aria-expanded','false');
  }
  function findTrigger(){
    const end=prompt.selectionStart;if(end!==prompt.selectionEnd)return null;
    const text=prompt.value.slice(0,end);
    if((text.match(/```/g)||[]).length%2)return null;
    const match=text.match(/(?:^|[\s（(])@([^\n@]{0,100})$/);
    if(!match)return null;
    const start=end-match[1].length-1;
    return {start,end,text:prompt.value.slice(start,end),query:match[1]};
  }
  function open(trigger=null,focusQuery=false){
    const target=owner();if(!target.chat)return toast('先打开一个学习对话，再引用书库节点。');
    if(!picker.open){picker.owner={...target};book.value='';purpose.value='reference';}
    picker.open=true;picker.trigger=trigger;query.value=trigger?.query||'';
    panel.hidden=false;if(!panel.matches(':popover-open'))panel.showPopover();
    prompt.setAttribute('aria-expanded','true');prompt.setAttribute('aria-controls',panel.id);button.setAttribute('aria-expanded','true');
    position();search();if(focusQuery)query.focus();
  }
  function updateInput(event){
    if(event?.isComposing||picker.busy)return;
    const trigger=findTrigger();
    if(!trigger){picker.suppressed=null;if(picker.trigger)close();return;}
    if(trigger.text===picker.suppressed)return;
    picker.suppressed=null;
    if(!picker.open)open(trigger);
    else{picker.trigger=trigger;query.value=trigger.query;search();}
  }
  function search(){
    clearTimeout(picker.timer);const epoch=++picker.epoch;
    picker.rows=[];results.replaceChildren();status.textContent='查找目录中…';
    picker.timer=setTimeout(async()=>{
      try{
        const value=await api('/api/library/nodes/suggest?'+new URLSearchParams({query:query.value,limit:'12',...(book.value?{book_id:book.value}:{})}));
        if(!picker.open||epoch!==picker.epoch||!same(picker.owner))return;
        const selectedBook=book.value;book.replaceChildren(new Option('全部书籍',''));
        for(const b of value.books)book.append(new Option(b.title,b.id));book.value=selectedBook;
        picker.rows=value.nodes;picker.active=0;renderRows();
        status.textContent=value.nodes.length?(value.has_more?'还有更多目录，请加上书名或章节关键词。':'已读章节可直接引用；未读章节先安排阅读。'):'没有匹配的目录。可换书名、章节标题，或到全局书库查正文。';
        if(window.studyforgeBookLibrary.pref.mode==='off')status.textContent+=' 选中已读章节后，本对话会改为手动引用。';
        position();
      }catch(error){if(picker.open&&epoch===picker.epoch){status.textContent=error.message;position();}}
    },180);
  }
  function renderRows(){
    results.replaceChildren();picker.rows.forEach((node,index)=>{
      const row=document.createElement('button');row.type='button';row.id='bookMentionOption'+index;row.dataset.mentionNode=node.node_id;
      row.className='book-mention-row';row.setAttribute('role','option');row.setAttribute('aria-selected',String(index===picker.active));
      const title=document.createElement('strong'),label=document.createElement('span'),detail=document.createElement('small');
      title.textContent=node.title;label.textContent=node.book_title+' · '+node.path;
      detail.textContent=states[node.state]+(node.start_page?' · PDF '+node.start_page+'–'+node.end_page:'')+' · '+(node.state==='read'?'选择并引用':'定位并安排阅读');
      row.append(title,label,detail);row.onclick=()=>choose(node);results.append(row);
    });highlight();
  }
  function highlight(){
    const rows=[...results.children];rows.forEach((row,i)=>row.setAttribute('aria-selected',String(i===picker.active)));
    const id=rows[picker.active]?.id;if(id){prompt.setAttribute('aria-activedescendant',id);query.setAttribute('aria-activedescendant',id);}
  }
  async function choose(node){
    if(picker.busy||!same(picker.owner))return;
    const target={...picker.owner},trigger=picker.trigger;
    if(node.state!=='read'){
      close();await window.libraryOpen(node.book_id,node.node_id).catch(error=>toast(error.message));
      return toast('这一章节未完成阅读。请核对范围，再主动安排阅读；不会自动开始。');
    }
    picker.busy=true;results.querySelectorAll('button').forEach(row=>row.disabled=true);
    status.textContent='保存本对话引用…';
    try{
      await window.libraryAddReference(node,purpose.value,target);
      if(!same(target))return;
      // Explicitly choosing a source also restores this chat's material switch.
      if(phone){if(!$('useMaterials').checked){$('useMaterials').checked=true;$('useMaterials').dispatchEvent(new Event('change'));}}
      else if($('chatSourceMode').value==='none'){$('chatSourceMode').value='selected';$('chatSourceMode').dispatchEvent(new Event('change'));}
      if(trigger&&prompt.value.slice(trigger.start,trigger.end)===trigger.text){
        prompt.setRangeText('',trigger.start,trigger.end,'end');prompt.dispatchEvent(new Event('input',{bubbles:true}));
      }
      close();prompt.focus();toast('已引用 '+node.title+'；下方标签随本对话保存。');
    }catch(error){if(same(target)){status.textContent=error.message;await window.libraryConversationChanged(target.chat,target.project);renderRows();position();}}
    finally{picker.busy=false;}
  }
  function keydown(event){
    if(!picker.open||event.isComposing||event.keyCode===229)return;
    if(event.key==='Escape'){
      event.preventDefault();event.stopImmediatePropagation();picker.suppressed=picker.trigger?.text||null;close();prompt.focus();return;
    }
    if(['ArrowDown','ArrowUp'].includes(event.key)&&picker.rows.length){
      event.preventDefault();event.stopImmediatePropagation();
      picker.active=(picker.active+(event.key==='ArrowDown'?1:-1)+picker.rows.length)%picker.rows.length;
      highlight();results.children[picker.active]?.scrollIntoView({block:'nearest'});return;
    }
    if(event.key==='Enter'&&!event.shiftKey&&!event.ctrlKey&&!event.metaKey){
      event.preventDefault();event.stopImmediatePropagation();
      if(picker.rows[picker.active])choose(picker.rows[picker.active]);return;
    }
  }
  function renderChips(detail){
    if(!same(detail))return;
    if(picker.open&&!same(picker.owner))close();
    chips.replaceChildren();chips.hidden=!detail.ready||!detail.pref.references.length;
    for(const ref of detail.pref.references){
      const chip=document.createElement('div');chip.className='book-composer-chip';chip.dataset.composerBookRef=ref.node_id;
      const title=document.createElement('button');title.type='button';title.className='book-composer-label';
      const name=document.createElement('span'),source=document.createElement('small');
      name.textContent='@ '+ref.title;source.textContent=ref.book_title;title.append(name,source);
      title.title=ref.book_title+' · '+states[ref.state];
      title.onclick=()=>window.libraryOpen(ref.book_id,ref.node_id).catch(error=>toast(error.message));
      const select=document.createElement('select');select.setAttribute('aria-label',ref.title+'的引用用途');
      select.append(new Option('参考背景','reference'),new Option('重点讲解','primary'));select.value=ref.purpose;
      const target={chat:detail.chat,project:detail.project};
      select.onchange=()=>window.libraryReferencePurpose(ref.node_id,select.value,target).catch(error=>toast(error.message));
      const remove=document.createElement('button');remove.type='button';remove.textContent='✕';remove.title='移除 '+ref.title+'的引用';remove.setAttribute('aria-label',remove.title);
      remove.onclick=()=>window.libraryRemoveReference(ref.node_id,target).catch(error=>toast(error.message));
      select.disabled=remove.disabled=detail.pending;chip.append(title,select,remove);chips.append(chip);
    }
  }
  button.onclick=()=>picker.open?close():open(null,true);
  panel.querySelector('[data-mention-close]').onclick=()=>{picker.suppressed=picker.trigger?.text||null;close();prompt.focus();};
  query.oninput=search;book.onchange=search;
  for(const input of [prompt,query])input.addEventListener('keydown',keydown,true);
  prompt.addEventListener('input',updateInput);prompt.addEventListener('compositionend',()=>updateInput());
  document.addEventListener('pointerdown',event=>{if(picker.open&&!panel.contains(event.target)&&event.target!==button&&event.target!==prompt)close();});
  window.addEventListener('resize',position);window.visualViewport?.addEventListener('resize',position);window.visualViewport?.addEventListener('scroll',position);
  window.addEventListener('studyforge-library-references',event=>{
    if(picker.open&&!same(picker.owner))close();renderChips(event.detail);
  });
  const ui=window.studyforgeBookLibrary;
  renderChips({chat:ui.chat,project:ui.project,pref:ui.pref,ready:ui.prefReady,pending:false});
  window.studyforgeLibraryMentionPicker=picker;
})();
