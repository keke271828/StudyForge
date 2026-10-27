/* The shelf is global; choices belong to one chat. Shared desktop/mobile UI. */
(() => {
  'use strict';
  const phone = typeof mobile !== 'undefined';
  const ui = {books:[],book:null,nodes:[],selected:new Set(),jobs:[],poll:null,polling:false,
    chat:null,project:null,pref:{mode:'auto',references:[]},save:Promise.resolve(),saves:new Map(),pendingRefs:new Map(),prefReady:false,prefRevision:0,epoch:0,detailKey:'',scope:null,readingMode:'serial',readingPriority:'background',allowRangeAI:false,submitting:false,matchedNodes:new Set(),
    searchEpoch:0,searchTimer:null,searchResults:[],nodeQuery:'',nodeFilter:'all',collapsed:new Set(),visibleNodes:new Set(),semantic:null,semanticPolling:false,semanticEpoch:0,
    arranging:false,outlineRevision:'',move:null,drag:null,undo:null,moving:false,matchHistory:[],matchRevision:0,matchRenderKey:null,review:null,reviewReturn:null,
    bookEpoch:0,openEpoch:0,shelfEpoch:0,loadedBook:null,pollBook:null,bookViews:new Map(),restoreBookScroll:null,notes:null,notesEpoch:0,readingDepth:'index',readingFocus:''};
  const esc = value => {const span=document.createElement('span');span.textContent=String(value??'');return span.innerHTML.replaceAll('"','&quot;');};
  const opts = (method,value) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  const fail = e => phone?toast(e.message):error(e);
  const current = () => phone?{chat:mobile.chat?.id,project:mobile.project?.id}:{chat:state.conversation,project:state.project?.id};
  const workbenchModel = () => phone?{provider:$('provider').value,model:$('model').value||null,effort:selectedReasoning()}:
    {provider:$('provider').value,model:currentModel(),effort:currentEffort()};
  const names = {range_pending:'请确认页码',unread:'尚未阅读',read:'AI已整理'};
  const phases = {queued:'等待空闲',running:'执行中',pausing:'正在暂停',paused:'已暂停',completed:'已完成',failed:'未完成',cancelled:'已取消'};
  const markup = `<div class="page-heading"><span class="eyebrow">SHARED KNOWLEDGE</span><h2>全局书库</h2><p>先上传教材，再选想读的章节。整理好的内容可以在不同项目里向导师提问。</p><button class="user-guide-context" type="button" data-open-user-guide="library" aria-haspopup="dialog">? 教材阅读怎么用？</button></div><div class="book-library-layout"><aside class="book-shelf"><div id="bookShelfControls" class="book-shelf-controls"><label class="book-upload">＋ 放入 PDF 教材<input id="bookUpload" type="file" accept=".pdf" multiple hidden></label><p id="bookUploadStatus" class="small-note" role="status">上传后先保存文件，不会开始阅读。下一步：点书名，再点“自动找目录并建立”。</p></div><input id="bookSearch" type="search" maxlength="1000" aria-label="搜索书名、章节与已读内容" placeholder="搜索书名、章节、术语"><div id="bookSearchResults" class="book-search-results" aria-live="polite" hidden></div><div id="bookShelf" tabindex="0" role="region" aria-label="书架列表，可滚动选择书籍"></div></aside><section id="bookDetail" class="book-detail" tabindex="0" aria-label="所选书籍的目录与阅读安排"><p>先点左侧一本书，再勾选想让 AI 阅读的章节。</p></section></div>`;
  function dialog(id,title,body){
    const host=document.createElement('dialog');host.id=id;host.className='book-dialog';
    host.innerHTML=`<header class="book-dialog-head"><h2>${esc(title)}</h2><button type="button" data-book-close aria-label="关闭">✕</button></header><div class="book-dialog-body">${body}</div>`;
    host.querySelector('[data-book-close]').onclick=()=>host.close();document.body.append(host);return host;
  }
  let mobileDialog;
  if(phone){
    mobileDialog=dialog('mobileBookLibrary','教材与阅读',markup);
    const button=document.createElement('button');button.type='button';button.textContent='全局书库 · 目录与后台阅读';
    $('optionsDialog').querySelector('.sheet-body').prepend(button);button.onclick=()=>open().catch(fail);
  }else{
    $('view-library').innerHTML=markup;
    const nav=document.createElement('button');nav.dataset.view='library';
    nav.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3V4Z M12 6v16"/></svg><span>全局书库</span>';
    document.querySelector('.studio-nav [data-view="sources"]').after(nav);nav.onclick=()=>showView('library');
  }
  const modelHost=document.createElement('div');modelHost.className='book-model-host';
  (phone?mobileDialog:$('view-library')).querySelector('.page-heading').after(modelHost);
  const readModels=window.studyforgeLibraryModels.create({host:modelHost,api,workbench:workbenchModel,notify:fail,
    catalog:id=>phone?(mobile.catalog?.provider===id?mobile.catalog:null):serviceCatalog(id)});
  const model=()=>readModels.selection();
  const scopeDialog=dialog('bookScopeDialog','确认要读的章节页码',`<form id="bookScopeForm"><p class="book-notice">请对照右侧原页，确认这一节从哪里开始、到哪里结束。这里填 PDF 阅读器显示的页数；同一页有多个小节时，可以点图片选起止位置。</p><label>章节名称<input id="bookNodeTitle" maxlength="200" required></label><div class="book-fields"><label>起始 PDF 页<input id="bookStart" type="number" min="1" required></label><label>终止 PDF 页<input id="bookEnd" type="number" min="1" required></label><label>第一页从哪里开始（页面高度百分比）<input id="bookStartY" type="number" min="0" max="99" value="0" required></label><label>最后一页读到哪里（页面高度百分比）<input id="bookEndY" type="number" min="1" max="100" value="100" required></label></div><div class="book-preview-tools"><label>预览 PDF 页<input id="bookPreviewNumber" type="number" min="1"></label><button id="bookPreviewPage" type="button">查看原页</button><label>点击原页设为<select id="bookCropEdge"><option value="start">开始位置</option><option value="end">结束位置</option></select></label></div><p id="bookCropNotice" class="small-note" role="status">点击原页只调整本章节，不读取其他章节。</p><div class="book-preview"><img id="bookPagePreview" alt="教材原页预览"><span id="bookCropLine" hidden></span></div><label class="check-line"><input id="bookScopeConfirmed" type="checkbox" required>我已确认上述 PDF 页码与页内范围</label><button class="primary" type="submit">保存并确认范围</button></form>`);
  const rangeTools=document.createElement('div');rangeTools.className='book-range-tools';
  rangeTools.innerHTML='<p id="bookRangeEvidence" class="book-notice" role="status"></p><button type="button" id="bookScopeAuto">自动定位这一章节</button>';
  $('bookScopeForm').prepend(rangeTools);
  $('bookScopeAuto').onclick=()=>{if(ui.scope?.id)startRanges([ui.scope.id],false).then(()=>scopeDialog.close()).catch(fail);};
  $('bookStartY').step='any';$('bookEndY').step='any';
  for(const [edge,label] of [['start','查看起始页'],['end','查看终止页']]){
    const button=document.createElement('button');button.id='bookPreview'+(edge==='start'?'Start':'End');button.type='button';button.textContent=label;
    button.onclick=()=>{
      $('bookPreviewNumber').value=$(edge==='start'?'bookStart':'bookEnd').value;$('bookCropEdge').value=edge;
      loadPreview().then(loaded=>{if(!loaded)return;const line=$('bookCropLine');line.style.top=$(edge==='start'?'bookStartY':'bookEndY').value+'%';line.hidden=false;}).catch(fail);
    };scopeDialog.querySelector('.book-preview-tools').append(button);
  }
  const notesDialog=dialog('bookNotesDialog','章节阅读结果','<div id="bookNotesBody"></div>');
  const notesTools=document.createElement('footer');notesTools.className='book-notes-tools';
  notesTools.innerHTML='<button id="bookNotesOriginal" type="button">查看起始原页</button><button id="bookNotesDeepen" type="button">精读这一章节</button><button id="bookNotesReference" type="button">引用到当前对话</button>';
  notesDialog.append(notesTools);
  notesDialog.addEventListener('close',()=>{if(notesDialog.open)return;ui.notesEpoch++;ui.notes?.controller.abort();ui.notes=null;$('bookNotesBody').replaceChildren();});
  $('bookNotesDeepen').onclick=()=>{
    const note=ui.notes;if(!note||ui.book?.id!==note.book)return;
    const focus=note.focus||'';notesDialog.close();ui.selected=new Set([note.id]);ui.readingDepth='deep';ui.readingFocus=focus;
    $('bookReadingDepth').value='deep';$('bookReadingFocus').value=focus;readingNotice();renderNodes();
    $('bookReadingFocus').scrollIntoView({block:'center',behavior:'auto'});$('bookReadingFocus').focus({preventScroll:true});
  };
  $('bookNotesOriginal').onclick=()=>{
    const note=ui.notes;if(!note||ui.book?.id!==note.book||!note.page)return;
    notesDialog.close();showPreviewOnly(note.page).catch(fail);
  };
  $('bookNotesReference').onclick=async()=>{
    const note=ui.notes,button=$('bookNotesReference');if(!note||ui.book?.id!==note.book)return;
    button.disabled=true;try{await addReference(note.id);}
    catch(e){fail(e);}finally{if(ui.notes===note)button.disabled=!current().chat;}
  };
  const reviewDialog=dialog('bookRangeReviewDialog','集中核对范围疑点',`<p class="book-notice">大部分页码已经自动找到。这里只列出还需要你看一眼的章节：查看原页，确认开始和结束位置，再勾选保存。</p><div class="book-review-layout"><div id="bookRangeReviewList" class="book-review-list" tabindex="0" aria-label="待核对章节，可滚动"></div><section id="bookRangeReviewEvidence" class="book-review-evidence"></section></div><p id="bookRangeReviewStatus" class="small-note" role="status"></p><footer class="book-actions"><button id="bookReviewConfirm" type="button" class="primary">确认勾选的范围</button><button id="bookReviewRead" type="button">确认后阅读这些章节</button></footer>`);
  const reviewable=n=>{
    const a=n.provenance?.auto_range;
    return !n.confirmed&&a?.crop&&a.start&&(a.next_heading||a.terminal)&&a.title===n.title&&Object.entries(a.crop).every(([k,v])=>Number(n[k])===Number(v));
  };
  async function openReview(ids,restore=null){
    await refreshCurrent();
    const rows=ui.nodes.filter(n=>ids.includes(n.id)&&!n.confirmed&&n.provenance?.auto_range);
    if(!rows.length)return toast('没有待核对的定位结果；尚未定位的章节请先自动定位。');
    const checked=new Set(rows.filter(n=>reviewable(n)&&restore?.checked?.[n.id]===n.range_revision).map(n=>n.id));
    const active=rows.some(n=>n.id===restore?.active)?restore.active:rows[0].id;
    ui.review={book:ui.book.id,rows,checked,active};
    $('bookRangeReviewList').innerHTML=rows.map(n=>`<article class="book-review-row"><label><input type="checkbox" data-review-check="${n.id}" ${checked.has(n.id)?'checked':''} ${reviewable(n)?'':'disabled'} aria-label="已核对 ${esc(n.title)}"><span>${reviewable(n)?'我已核对原页':'先补全起止位置'}</span></label><button type="button" data-review-node="${n.id}"><strong>${esc(n.title)}</strong><small>${reviewable(n)?'已有边界建议，可看原页后确认':'边界不完整，需要微调'}</small></button></article>`).join('');
    $('bookRangeReviewList').querySelectorAll('[data-review-check]').forEach(input=>input.onchange=()=>{
      input.checked?ui.review.checked.add(input.dataset.reviewCheck):ui.review.checked.delete(input.dataset.reviewCheck);reviewStatus();
    });
    $('bookRangeReviewList').querySelectorAll('[data-review-node]').forEach(button=>button.onclick=()=>showReviewEvidence(button.dataset.reviewNode));
    if(!reviewDialog.open)reviewDialog.showModal();showReviewEvidence(active);reviewStatus();
  }
  function reviewBack(){return {book:ui.review.book,ids:ui.review.rows.map(n=>n.id),active:ui.review.active,
    checked:Object.fromEntries(ui.review.rows.filter(n=>ui.review.checked.has(n.id)).map(n=>[n.id,n.range_revision]))};}
  reviewDialog.addEventListener('close',()=>{$('bookRangeReviewEvidence').replaceChildren();$('bookRangeReviewList').replaceChildren();ui.review=null;});
  function reviewStatus(){
    const count=ui.review?.checked.size||0;
    $('bookRangeReviewStatus').textContent=`共 ${ui.review?.rows.length||0} 个疑点，已核对勾选 ${count} 个。只加载当前章节的原页，避免一次打开大量图片。`;
    $('bookReviewConfirm').disabled=!count;$('bookReviewRead').disabled=!count;
  }
  function showReviewEvidence(id){
    const n=ui.review.rows.find(n=>n.id===id);ui.review.active=id;const a=n.provenance?.auto_range;
    $('bookRangeReviewList').querySelectorAll('[data-review-node]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.reviewNode===id)));
    $('bookRangeReviewEvidence').innerHTML=`<h3>${esc(n.title)}</h3><p class="book-notice">${esc(a?.reason||'尚未取得完整边界。可重新定位或手动点击原页设置范围。')}</p>${a?.crop?`<p>建议：PDF ${a.crop.start_page}–${a.crop.end_page} · 首页 ${Math.round(a.crop.start_y*1000)/10}% / 末页 ${Math.round(a.crop.end_y*1000)/10}%</p>`:''}<div class="book-review-previews"></div><button type="button" id="bookReviewAdjust">调整这一章节的起止位置…</button>`;
    const host=$('bookRangeReviewEvidence').querySelector('.book-review-previews');
    for(const [key,label] of [['start','起始标题'],['next_heading','下一标题（不包含在本章节中）']]){
      const hit=a?.[key];if(!hit)continue;
      const figure=document.createElement('figure');figure.innerHTML=`<figcaption>${label} · PDF ${hit.page}<small>${esc(hit.text)} · ${esc(hit.basis||'已观察到的标题行')}</small></figcaption><div class="book-review-image"><div><img alt="${label}原页"><span aria-hidden="true"></span></div></div>`;
      const img=figure.querySelector('img'),container=figure.querySelector('.book-review-image');
      figure.querySelector('span').style.top=(hit.top*100)+'%';
      img.onload=()=>{container.scrollTop=Math.max(0,hit.top*img.clientHeight-45);};
      const zoom=document.createElement('button');zoom.type='button';zoom.textContent='放大核对原页';
      zoom.onclick=()=>{ui.reviewReturn=reviewBack();reviewDialog.close();showPreviewOnly(hit.page).catch(fail);};
      figure.querySelector('figcaption').append(zoom);
      img.src='/api/library/books/'+ui.review.book+'/page?page='+hit.page;host.append(figure);
    }
    if(!host.children.length)host.innerHTML='<p class="small-note">还没找到可靠的起止页。请点“调整”查看原页，或重新自动查找。</p>';
    $('bookReviewAdjust').onclick=()=>{
      ui.reviewReturn=reviewBack();reviewDialog.close();editScope(id).catch(fail);
    };
  }
  async function confirmReviewed(read){
    if(!ui.review?.checked.size)return;const snapshot=ui.review;
    const ids=[...snapshot.checked],revisions=Object.fromEntries(snapshot.rows.filter(n=>snapshot.checked.has(n.id)).map(n=>[n.id,n.range_revision]));
    $('bookReviewConfirm').disabled=true;$('bookReviewRead').disabled=true;
    try{
      await api('/api/library/books/'+snapshot.book+'/ranges/confirm',opts('POST',{revisions}));
      await refreshCurrent();reviewDialog.close();
      if(read&&ui.book?.id===snapshot.book){ui.selected=new Set(ids);renderNodes();await startRead();}
      else toast(`已确认 ${ids.length} 个范围；可继续阅读，无需逐个保存。`);
    }catch(e){fail(e);reviewStatus();}
  }
  $('bookReviewConfirm').onclick=()=>confirmReviewed(false);
  $('bookReviewRead').onclick=()=>confirmReviewed(true);
  const moveDialog=dialog('bookMoveDialog','移动章、节',`<form id="bookMoveForm"><div class="book-move-fields"><p id="bookMoveTitle" class="book-notice"></p><label>移动到哪个章节下<select id="bookMoveParent"></select></label><label>在同级目录中的位置<select id="bookMoveBefore"></select></label><p id="bookMovePreview" class="book-move-preview" role="status"></p><p class="small-note">这个章节下面的小节会一起移动。原来的页码、笔记和引用会保留；移动目录不会多读其他内容。</p><p id="bookMoveStatus" class="book-move-status" role="status"></p></div><div class="book-actions"><button id="bookMoveSave" class="primary" type="submit">确认移动</button><button id="bookMoveCancel" type="button">取消</button></div></form>`);
  $('bookMoveCancel').onclick=()=>moveDialog.close();
  moveDialog.addEventListener('close',()=>{ui.move=null;});
  const refs=document.createElement('section');refs.className='book-chat-references';
  refs.innerHTML='<div class="book-reference-head"><strong>书库参考</strong><button id="openBookLibrary" type="button">选择章节</button></div><label class="book-reference-mode">使用方式<select id="bookReferenceMode"><option value="auto">自动找相关已读章节</option><option value="manual">只用手动引用</option><option value="off">关闭书库引用</option></select></label><div id="bookReferences" tabindex="0" aria-label="手动选择的书库参考，可滚动"></div><div id="bookReferenceStatus" class="small-note" role="status">自动引用仅作辅助；未读章节先征求你的选择。</div>';
  (phone?$('optionsDialog').querySelector('.sheet-body'):document.querySelector('.context-footer')).prepend(refs);

  async function open(bookId,nodeId){
    const token=++ui.openEpoch;
    if(phone){if(!mobileDialog.open)mobileDialog.showModal();}
    else showView('library');
    await refreshShelf();
    if(token!==ui.openEpoch)return;
    if(bookId)await selectBook(bookId,token);
    if(token!==ui.openEpoch)return;
    if(nodeId){
      let target=ui.nodes.find(n=>n.id===nodeId);if(!target)throw new Error('目录项已改变或被删除，请重新搜索。');
      ui.nodeQuery='';ui.nodeFilter='all';const seen=new Set();
      while(target.parent_id&&!seen.has(target.parent_id)){seen.add(target.parent_id);ui.collapsed.delete(target.parent_id);target=ui.nodes.find(n=>n.id===target.parent_id);if(!target)break;}
      ui.selected=new Set([nodeId]);renderDetail(true);$('bookDetail').querySelector(`[data-book-node="${nodeId}"]`)?.scrollIntoView({block:'center'});
    }
    startPoll();
  }
  function visible(){return phone?mobileDialog.open:state.view==='library';}
  function startPoll(){if(!ui.poll)ui.poll=setInterval(()=>{if(visible()){refreshCurrent(true).catch(fail);refreshSemantic().catch(fail);window.libraryPolicyRefresh?.();}else{clearInterval(ui.poll);ui.poll=null;}},2000);}
  async function refreshShelf(){
    readModels.load().catch(fail);
    const token=++ui.shelfEpoch,navigation=ui.openEpoch;
    const result=await api('/api/library/books');if(token!==ui.shelfEpoch)return;
    ui.books=result.books;renderShelf();
    await refreshSemantic();
    window.libraryPolicyRefresh?.();
    for(const id of ui.bookViews.keys())if(!ui.books.some(b=>b.id===id))ui.bookViews.delete(id);
    if(ui.book&&!ui.books.some(b=>b.id===ui.book.id)){ui.bookEpoch++;ui.book=null;ui.loadedBook=null;ui.nodes=[];ui.selected.clear();ui.detailKey='';}
    if(!ui.book&&ui.books.length&&navigation===ui.openEpoch)await selectBook(ui.books[0].id,navigation);
  }
  const semanticBox=document.createElement('details');semanticBox.className='book-semantic-box';
  semanticBox.innerHTML='<summary>智能检索 <span id="bookSemanticBadge">检查中</span></summary><label>检索方式（全局）<select id="bookSearchMode"><option value="hybrid">关键词＋理解提问的意思</option><option value="keyword">只找相同关键词</option></select></label><p id="bookSemanticStatus" class="small-note" role="status"></p><p class="small-note">增强搜索可以找到“说法不同、意思相近”的内容，只搜索已经读过的章节。这个小模型在电脑上运行，不会另上传书籍或聊天。</p><p class="small-note">结果会附上相关原页，方便核对定义和条件。搜索结果只是线索，重要内容请打开原页确认。</p><button id="bookSemanticDownload" type="button">下载本地模型（约 136 MB）</button><button id="bookSemanticCancel" type="button" hidden>取消下载</button>';
  $('bookShelfControls').append(semanticBox);
  async function refreshSemantic(){
    if(ui.semanticPolling)return;ui.semanticPolling=true;
    const epoch=ui.semanticEpoch;
    try{
      const s=await api('/api/library/semantic');if(epoch!==ui.semanticEpoch)return;renderSemantic(s);
    }finally{ui.semanticPolling=false;}
  }
  function renderSemantic(s){
      ui.semantic=s;
      $('bookSearchMode').value=s.enabled?'hybrid':'keyword';
      const downloading=s.download?.state==='downloading';
      $('bookSemanticBadge').textContent=!s.enabled?'关键词':downloading?'下载中':!s.model_ready?'未安装':s.indexed_pages<s.total_pages?'准备搜索':'已就绪';
      $('bookSemanticStatus').textContent=(downloading?'模型下载 '+(s.download.progress||0)+'%。':s.model_ready?`已准备好 ${s.indexed_pages}/${s.total_pages} 页的增强搜索。`+(s.enabled?'会在空闲时继续准备，不优先占用聊天资源；不用时会释放内存。':'已关闭增强搜索。现有搜索记录保留，改用关键词查找。'):'不安装也能按关键词搜索。点下载后才会获取增强搜索模型。')+(s.download?.error?' '+s.download.error:'')+(s.error?' 索引问题：'+s.error:'');
      $('bookSemanticDownload').hidden=phone||s.model_ready||downloading;
      $('bookSemanticCancel').hidden=phone||!downloading;
      if(phone&&!s.model_ready)$('bookSemanticStatus').textContent+=' 请在电脑书库完成一次模型下载。';
  }
  $('bookSearchMode').onchange=async()=>{
    const control=$('bookSearchMode');control.disabled=true;ui.semanticEpoch++;
    try{renderSemantic(await api('/api/library/semantic',opts('PUT',{enabled:control.value==='hybrid'})));searchShelf();}
    catch(e){fail(e);if(ui.semantic)renderSemantic(ui.semantic);}finally{control.disabled=false;}
  };
  $('bookSemanticDownload').onclick=async()=>{try{await api('/api/library/semantic/download',{method:'POST'});await refreshSemantic();startPoll();}catch(e){fail(e);}};
  $('bookSemanticCancel').onclick=async()=>{try{await api('/api/library/semantic/cancel-download',{method:'POST'});await refreshSemantic();}catch(e){fail(e);}};
  function renderShelf(){
    const query=$('bookSearch').value.trim().toLowerCase();
    const found=new Set(ui.searchResults.map(n=>n.book_id));
    const shelf=$('bookShelf'),scrollTop=shelf.dataset.query===query?shelf.scrollTop:0;
    const focused=shelf.contains(document.activeElement)?document.activeElement.closest('[data-book-open]')?.dataset.bookOpen:null;
    shelf.innerHTML=ui.books.filter(b=>b.title.toLowerCase().includes(query)||found.has(b.id)).map(b=>`<button class="book-shelf-item ${b.id===ui.book?.id?'active':''}" data-book-open="${b.id}" type="button"><strong>${esc(b.title)}</strong><small>${b.page_count} 页 · ${b.node_count?b.node_count+' 个目录项':'待建目录'}</small></button>`).join('')||'<p class="small-note">书架为空，或没有符合搜索的书籍。</p>';
    shelf.dataset.query=query;
    shelf.querySelectorAll('[data-book-open]').forEach(button=>{button.onclick=()=>selectBook(button.dataset.bookOpen).catch(fail);if(button.dataset.bookOpen===focused)button.focus({preventScroll:true});});
    shelf.scrollTop=scrollTop;
  }
  function rememberBookView(){
    if(!ui.book||ui.loadedBook!==ui.book.id)return;
    ui.bookViews.delete(ui.book.id);
    ui.bookViews.set(ui.book.id,{selected:[...ui.selected],collapsed:[...ui.collapsed],query:ui.nodeQuery,filter:ui.nodeFilter,
      scroll:phone?mobileDialog.scrollTop:$('bookDetail').scrollTop,depth:ui.readingDepth,focus:ui.readingFocus});
    // Keep only small browsing drafts; original pages and notes stay in their
    // existing storage, and chat references remain isolated by conversation.
    while(ui.bookViews.size>32)ui.bookViews.delete(ui.bookViews.keys().next().value);
  }
  async function selectBook(id,navigation){
    const token=navigation??++ui.openEpoch;if(token!==ui.openEpoch)return;
    const changed=ui.book?.id!==id;
    if(changed){
      rememberBookView();ui.bookEpoch++;const saved=ui.bookViews.get(id);
      ui.nodeQuery=saved?.query||'';ui.nodeFilter=saved?.filter||'all';ui.selected=new Set(saved?.selected||[]);ui.collapsed=new Set(saved?.collapsed||[]);
      ui.readingDepth=saved?.depth||'index';ui.readingFocus=saved?.focus||'';
      ui.restoreBookScroll=saved?.scroll||0;ui.loadedBook=null;ui.arranging=false;ui.undo=null;clearDrag();
      if(moveDialog.open)moveDialog.close();if(notesDialog.open)notesDialog.close();
      ui.nodes=[];ui.jobs=[];ui.detailKey='';
    }
    ui.book=ui.books.find(b=>b.id===id)||{id};renderShelf();
    if(changed)$('bookDetail').innerHTML='<p class="book-notice" role="status">正在打开 '+esc(ui.book.title||'教材')+'…</p>';
    try{await refreshCurrent();}
    catch(e){if(token!==ui.openEpoch||ui.book?.id!==id)return;
      if(ui.loadedBook!==id){$('bookDetail').innerHTML='<p class="book-notice book-error" role="status">打开教材未完成：'+esc(e.message)+'</p><button type="button" id="retryBookOpen">重试打开</button>';$('retryBookOpen').onclick=()=>selectBook(id).catch(fail);}throw e;}
  }
  function searchShelf(){
    const token=++ui.searchEpoch,query=$('bookSearch').value.trim();clearTimeout(ui.searchTimer);
    ui.searchResults=[];renderShelf();$('bookSearchResults').hidden=!query;
    if(!query){$('bookSearchResults').replaceChildren();return;}
    $('bookSearchResults').textContent='正在查找目录和已经读过的内容…';
    ui.searchTimer=setTimeout(async()=>{
      try{
        const result=await api('/api/library/search?limit=12&mode='+$('bookSearchMode').value+'&query='+encodeURIComponent(query));
        if(token!==ui.searchEpoch)return;ui.searchResults=result.nodes;renderShelf();
        const semanticNote=result.semantic_used?' · 包含语义候选，需回查原文':result.semantic_state==='busy'?' · 本地模型忙，本次使用关键词':result.requested_mode==='hybrid'?' · 暂无可用语义命中，使用关键词':'';
        $('bookSearchResults').innerHTML='<p class="small-note">'+(result.nodes.length?'找到相关章节 · 点击查看位置':'没有找到相关章节。尚未阅读的正文不在搜索范围内。')+semanticNote+(result.nodes.length===12?'（最多显示 12 项，可缩小关键词）':'')+'</p>'+result.nodes.map(n=>{
          const pages=n.matched_pages?.map(p=>p.page).join('、');
          const matched=n.match_kind==='semantic'?'意思相近的内容':n.match_kind==='hybrid'?'关键词和意思都相关':n.match_kind==='original'?'在原文中找到':n.match_kind==='visual'?'在图片阅读结果中找到':'在目录或阅读笔记中找到';
          return `<button type="button" class="book-search-result" data-book-search-node="${n.node_id}" data-book-search-book="${n.book_id}"><strong>${esc(n.title)}</strong><small>${esc(n.book_title)} · ${names[n.state]}</small><small>${esc(pages?'PDF '+pages:n.start_page?'PDF '+n.start_page+'–'+n.end_page:'尚未找到页码')} · ${matched}</small>${n.automatic_reference===false?'<small>此命中不自动加入对话，可手动选用</small>':''}</button>`;
        }).join('');
        $('bookSearchResults').querySelectorAll('[data-book-search-node]').forEach(button=>button.onclick=()=>open(button.dataset.bookSearchBook,button.dataset.bookSearchNode).catch(fail));
      }catch(e){if(token===ui.searchEpoch)$('bookSearchResults').textContent='搜索未完成：'+e.message;}
    },250);
  }
  async function refreshCurrent(pollOnly=false){
    if(!ui.book)return;const id=ui.book.id,epoch=ui.bookEpoch;
    if(ui.polling&&ui.pollBook===id){if(pollOnly)return ui.polling;await ui.polling;if(ui.book?.id!==id||epoch!==ui.bookEpoch)return;}
    const operation=(async()=>{
      let result;try{result=await api('/api/library/books/'+id);}catch(e){if(ui.book?.id!==id||epoch!==ui.bookEpoch)return;throw e;}
      if(ui.book?.id!==id||epoch!==ui.bookEpoch)return;
      ui.book=result.book;ui.nodes=result.nodes;ui.jobs=result.jobs;ui.outlineRevision=result.outline_revision;ui.loadedBook=id;
      const entry=ui.books.find(b=>b.id===id);if(entry&&entry.node_count!==ui.nodes.length){entry.node_count=ui.nodes.length;renderShelf();}
      const valid=new Set(ui.nodes.map(n=>n.id));ui.selected=new Set([...ui.selected].filter(n=>valid.has(n)));ui.collapsed=new Set([...ui.collapsed].filter(n=>valid.has(n)));
      if(ui.undo&&ui.undo.revision!==ui.outlineRevision)ui.undo=null;renderDetail();
      if(ui.restoreBookScroll!==null){const scroll=ui.restoreBookScroll;ui.restoreBookScroll=null;(phone?mobileDialog:$('bookDetail')).scrollTop=scroll;}
    })();
    ui.polling=operation;ui.pollBook=id;
    try{await operation;}finally{if(ui.polling===operation){ui.polling=null;ui.pollBook=null;}}
  }
  function tocFormMarkup(){
    return `<section class="book-toc-form"><h3>扫描教材：自动找目录</h3>
      <p class="small-note">点击后在本机查找书前部的目录页，再建立章、节列表。只做目录导航，不启动正文通读，也不调用云模型。</p>
      <div class="book-toc-auto"><button type="button" id="bookAutoToc" class="primary">自动找目录并建立</button>
      <label>最多查找前 <input id="bookTocScanLimit" type="number" min="1" max="64" value="32" aria-label="最多查找前多少 PDF 页"> 页</label></div>
      <details id="bookTocManual"><summary>手动指定目录页／校正识别结果</summary>
      <form id="bookTocForm"><p class="small-note">页码使用 PDF 文件页码。只识别你指定的目录页，一次最多 12 页。</p>
      <div class="book-fields"><label>目录所在 PDF 页<input id="bookTocPages" placeholder="例如 3-5" required></label>
      <label>书上印的页码<input id="bookPrintedFirst" type="number" min="1" value="1"></label>
      <label>它在 PDF 中是第几页（选填）<input id="bookPdfFirst" type="number" min="1" placeholder="留空，自动核对页码偏移"></label></div>
      <div class="book-actions"><button type="submit">按指定页建立目录</button><button type="button" id="bookPeek">预览原页</button></div></form></details>
      <p class="small-note">建立目录后，勾选章、节即可自动定位正文范围。只有定位不可靠的部分需要你核对。</p></section>`;
  }
  function renderDetail(force=false){
    if(!ui.book)return;
    if(ui.drag){renderJobs();return;}
    const key=JSON.stringify([ui.book.id,ui.book.title,ui.outlineRevision,ui.nodes.map(n=>[n.id,n.updated_at,n.reading?.id,n.reading?.updated_at])]);
    if(force||key!==ui.detailKey){
      const focused=document.activeElement?.id==='bookNodeQuery'?{start:document.activeElement.selectionStart,end:document.activeElement.selectionEnd}:null;
      ui.detailKey=key;const b=ui.book;
      $('bookDetail').innerHTML=`<header class="book-detail-head"><div><span class="eyebrow">${b.page_count} 页 PDF</span><h2>${esc(b.title)}</h2></div><button data-book-delete type="button" class="danger-action">删除书籍</button></header><p class="book-notice">“AI已整理”表示已生成阅读笔记。点“查看阅读结果”可对照原页；笔记可能出错，也不代表你已经学会。</p>${ui.nodes.length?'':tocFormMarkup()}<div class="book-reading-toolbar"><label>何时阅读<select id="bookReadingPriority"><option value="background">空闲时再读</option><option value="foreground">优先开始 · 可继续聊天</option></select></label><label>阅读顺序<select id="bookReadingMode"><option value="serial">按目录依次阅读</option><option value="parallel">同时阅读多个章节</option></select></label><button id="readBookNodes" type="button" class="primary">阅读所选章节</button><button id="locateBookNodes" type="button">自动查找所选章节的页码</button><button id="addBookNode" type="button">＋ 添加章节</button><span id="bookSelectedCount" class="small-note" role="status"></span></div><p id="bookReadingNotice" class="book-notice"></p><div id="bookNodes" class="book-nodes"></div><div id="bookJobs" class="book-jobs" aria-live="polite"></div>`;
      if($('bookTocForm'))$('bookTocForm').onsubmit=startToc;
      if($('bookAutoToc'))$('bookAutoToc').onclick=()=>startToc(null,true);
      if($('bookPeek'))$('bookPeek').onclick=()=>showPreviewOnly().catch(fail);
      $('addBookNode').onclick=()=>addNode().catch(fail);
      const arrange=document.createElement('button');arrange.id='arrangeBookNodes';arrange.type='button';
      arrange.onclick=()=>{ui.arranging=!ui.arranging;renderNodes();$('arrangeBookNodes').focus({preventScroll:true});};
      $('addBookNode').after(arrange);
      const undo=document.createElement('button');undo.id='undoBookMove';undo.type='button';undo.textContent='撤销上次移动';
      undo.onclick=()=>{if(ui.undo)performMove({...ui.undo},true).catch(fail);};arrange.after(undo);
      $('readBookNodes').onclick=()=>startRead().catch(fail);
      $('locateBookNodes').onclick=()=>startRanges([...ui.selected],false).catch(fail);
      const review=document.createElement('button');review.id='reviewBookRanges';review.type='button';review.textContent='检查待确认的页码';
      review.onclick=()=>openReview(ui.nodes.filter(n=>!n.confirmed).map(n=>n.id)).catch(fail);$('locateBookNodes').after(review);
      const complete=document.createElement('button');complete.id='completeBookRanges';complete.type='button';complete.textContent='查找其余章节的页码';
      complete.onclick=()=>startRanges(ui.nodes.filter(n=>!n.confirmed).map(n=>n.id),false).catch(fail);review.after(complete);
      const options=document.createElement('details');options.className='book-range-options';
      options.innerHTML='<summary>页码找不准时怎么办？</summary><label><input id="bookRangeAI" type="checkbox">页码仍找不准时，请当前 AI 协助检查（最多请求 6 次）</label><p class="small-note">通常由电脑自动查找，不额外请求 AI。勾选后可让 AI 帮忙辨认标题；仍找不准的章节会请你查看原页确认。</p>';
      $('bookReadingNotice').after(options);$('bookRangeAI').checked=ui.allowRangeAI;
      $('bookRangeAI').onchange=e=>{ui.allowRangeAI=e.target.checked;};
      $('bookReadingMode').value=ui.readingMode;
      $('bookReadingMode').onchange=e=>{ui.readingMode=e.target.value;readingNotice();};
      $('bookReadingPriority').value=ui.readingPriority;
      $('bookReadingPriority').onchange=e=>{ui.readingPriority=e.target.value;readingNotice();};
      const depth=document.createElement('label');depth.textContent='读到什么程度';
      const depthSelect=document.createElement('select');depthSelect.id='bookReadingDepth';
      depthSelect.innerHTML='<option value="index">先梳理概念和重点</option><option value="deep">详细读 · 解释概念和推导</option>';
      depth.append(depthSelect);$('readBookNodes').before(depth);depthSelect.value=ui.readingDepth;
      depthSelect.onchange=e=>{ui.readingDepth=e.target.value;readingNotice();};
      const focus=document.createElement('label');focus.id='bookReadingFocusLabel';focus.className='book-reading-focus';
      focus.innerHTML='想重点弄懂什么？（可不填）<textarea id="bookReadingFocus" rows="3" maxlength="1200" placeholder="例如：为什么要引入这个可调参数？哪些条件决定这种证明方法可用？"></textarea><small>只读你选中的章节。详细阅读通常更慢，建议先选一两个难点；以前的阅读结果会保留。</small>';
      $('bookReadingNotice').before(focus);$('bookReadingFocus').value=ui.readingFocus;
      $('bookReadingFocus').oninput=e=>{ui.readingFocus=e.target.value;};
      const readingHelp=document.createElement('details');readingHelp.className='book-range-options';
      readingHelp.innerHTML='<summary>这些阅读设置怎么选？</summary><div id="bookReadingDetails"></div>';
      $('bookReadingNotice').after(readingHelp);
      const progressLink=document.createElement('button');progressLink.type='button';progressLink.id='bookShowProgress';progressLink.hidden=true;progressLink.textContent='查看正在进行的阅读';
      progressLink.onclick=()=>{$('bookJobs').setAttribute('tabindex','-1');$('bookJobs').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});$('bookJobs').focus({preventScroll:true});};
      $('bookSelectedCount').after(progressLink);
      readingNotice();
      $('bookDetail').querySelector('[data-book-delete]').onclick=()=>removeBook().catch(fail);
      const filters=document.createElement('div');filters.className='book-node-filters';
      filters.innerHTML='<label>查找本书章节<input id="bookNodeQuery" type="search" placeholder="输入章、节标题；可用上级章节名" aria-label="筛选本书目录"></label><label>阅读状态<select id="bookNodeFilter"><option value="all">全部目录</option><option value="read">AI已整理</option><option value="unread">还没整理</option><option value="range_pending">请确认页码</option></select></label><div class="book-filter-actions"><button type="button" id="selectAllBookNodes">全选本书目录</button><button type="button" id="selectFilteredBookNodes">仅选筛选结果</button><button type="button" id="clearBookSelection">清空勾选</button><button type="button" id="clearBookFilters">清除筛选</button></div>';
      $('bookNodes').before(filters);$('bookNodeQuery').value=ui.nodeQuery;$('bookNodeFilter').value=ui.nodeFilter;
      const help=document.createElement('p');help.id='bookArrangeStatus';help.className='book-arrange-notice';help.setAttribute('role','status');$('bookNodes').before(help);
      $('bookNodeQuery').oninput=e=>{ui.nodeQuery=e.target.value;renderNodes();};
      $('bookNodeFilter').onchange=e=>{ui.nodeFilter=e.target.value;renderNodes();};
      $('clearBookFilters').onclick=()=>{ui.nodeQuery='';ui.nodeFilter='all';$('bookNodeQuery').value='';$('bookNodeFilter').value='all';renderNodes();};
      $('clearBookSelection').onclick=()=>{ui.selected.clear();renderNodes();};
      $('selectAllBookNodes').onclick=()=>{ui.selected=new Set(ui.nodes.map(n=>n.id));renderNodes();};
      $('selectFilteredBookNodes').onclick=()=>{ui.selected=new Set(ui.matchedNodes);renderNodes();};
      renderNodes();
      if(focused){$('bookNodeQuery').focus({preventScroll:true});$('bookNodeQuery').setSelectionRange(focused.start,focused.end);}
    }
    renderJobs();
  }
  function renderNodes(){
    const byId=new Map(ui.nodes.map(n=>[n.id,n])),parents=new Set(ui.nodes.map(n=>n.parent_id).filter(Boolean));
    const ancestors=n=>{const result=[],seen=new Set([n.id]);while(n.parent_id&&byId.has(n.parent_id)&&!seen.has(n.parent_id)){seen.add(n.parent_id);n=byId.get(n.parent_id);result.push(n);}return result;};
    const query=ui.nodeQuery.trim().toLowerCase(),filtered=Boolean(query||ui.nodeFilter!=='all');
    const matches=new Set(ui.nodes.filter(n=>(ui.nodeFilter==='all'||n.state===ui.nodeFilter||(ui.nodeFilter==='unread'&&n.state!=='read'))&&(!query||[n,...ancestors(n)].some(p=>p.title.toLowerCase().includes(query)))).map(n=>n.id));
    ui.matchedNodes=matches;
    const visible=new Set(matches);for(const n of ui.nodes)if(matches.has(n.id))for(const p of ancestors(n))visible.add(p.id);
    const displayed=ui.nodes.filter(n=>visible.has(n.id)&&(filtered||!ancestors(n).some(p=>ui.collapsed.has(p.id))));
    ui.visibleNodes=new Set(displayed.filter(n=>matches.has(n.id)).map(n=>n.id));
    $('bookNodes').innerHTML=displayed.map(n=>{
      const context=!matches.has(n.id),fold=parents.has(n.id)?`<button type="button" class="book-node-fold" data-book-fold="${n.id}" aria-expanded="${filtered||!ui.collapsed.has(n.id)}" aria-label="${ui.collapsed.has(n.id)?'展开':'收起'} ${esc(n.title)}" ${filtered?'disabled':''}>${!filtered&&ui.collapsed.has(n.id)?'▸':'▾'}</button>`:'';
      const drag=ui.arranging?`<button type="button" class="book-node-drag" data-book-drag="${n.id}" ${phone?'':'draggable="true"'} aria-label="移动 ${esc(n.title)}" title="拖动调整目录；点击选择归属与位置；Alt＋方向键排序">⠿</button>`:'';
      return `<article class="book-node ${n.parent_id?'book-node-child':''} ${context?'book-node-context':''}" style="--book-node-indent:${Math.min(ancestors(n).length,4)*18}px" data-book-node="${n.id}">${drag}${fold}<label class="book-node-select"><input type="checkbox" data-book-select="${n.id}" ${ui.selected.has(n.id)?'checked':''} ${context?'disabled title="用于显示目录路径，不在当前筛选范围内"':''}><span><strong>${esc(n.title)}${context?' · 目录路径':''}</strong><small>${n.printed_page?'纸面 '+n.printed_page+' · ':''}${n.start_page?'PDF '+n.start_page+'–'+n.end_page:'PDF 页待定位'} · ${n.confirmed?Math.round(n.start_y*100)+'% / '+Math.round(n.end_y*100)+'%':'需确认范围'}</small></span></label><span class="book-state ${n.state}">${names[n.state]}</span><div class="book-node-actions">${ui.arranging?`<button type="button" data-book-move="${n.id}">移动…</button>`:''}<button type="button" data-book-scope="${n.id}">查看页码和原页</button>${n.reading?`<button type="button" data-book-notes="${n.id}">查看阅读结果</button>`:''}<button type="button" data-book-reference="${n.id}">引用到当前对话</button></div></article>`;
    }).join('')||'<p class="small-note">没有符合筛选的目录项；可清除筛选或补充目录。未读正文不会自动解析。</p>';
    $('bookNodes').querySelectorAll('[data-book-fold]').forEach(button=>button.onclick=()=>{ui.collapsed.has(button.dataset.bookFold)?ui.collapsed.delete(button.dataset.bookFold):ui.collapsed.add(button.dataset.bookFold);renderNodes();$('bookNodes').querySelector('[data-book-fold="'+button.dataset.bookFold+'"]')?.focus({preventScroll:true});});
    $('bookNodes').querySelectorAll('[data-book-select]').forEach(input=>input.onchange=()=>{input.checked?ui.selected.add(input.dataset.bookSelect):ui.selected.delete(input.dataset.bookSelect);selectedCount();});
    $('bookNodes').querySelectorAll('[data-book-scope]').forEach(button=>button.onclick=()=>editScope(button.dataset.bookScope).catch(fail));
    $('bookNodes').querySelectorAll('[data-book-notes]').forEach(button=>button.onclick=()=>showNotes(button.dataset.bookNotes).catch(fail));
    $('bookNodes').querySelectorAll('[data-book-reference]').forEach(button=>button.onclick=()=>addReference(button.dataset.bookReference).catch(fail));
    bindOutline();
    selectedCount();
  }
  function nodePath(node,byId=new Map(ui.nodes.map(n=>[n.id,n]))){
    const titles=[node.title],seen=new Set([node.id]);
    while(node.parent_id&&byId.has(node.parent_id)&&!seen.has(node.parent_id)){node=byId.get(node.parent_id);seen.add(node.id);titles.unshift(node.title);}
    return titles.join(' / ');
  }
  function subtree(id){
    const children=new Map();for(const n of ui.nodes){if(!children.has(n.parent_id))children.set(n.parent_id,[]);children.get(n.parent_id).push(n.id);}
    const found=new Set(),pending=[id];while(pending.length){const next=pending.pop();if(found.has(next))continue;found.add(next);pending.push(...(children.get(next)||[]));}return found;
  }
  function siblingAfter(id){const n=ui.nodes.find(n=>n.id===id),siblings=ui.nodes.filter(x=>x.parent_id===n.parent_id);return siblings[siblings.findIndex(x=>x.id===id)+1]?.id||null;}
  function fillMovePositions(beforeId=null){
    const parent=$('bookMoveParent').value||null;
    $('bookMoveBefore').innerHTML='<option value="">排在最后</option>'+ui.nodes.filter(n=>n.parent_id===parent&&n.id!==ui.move.id).map(n=>`<option value="${n.id}">放在「${esc(n.title)}」之前</option>`).join('');
    if(beforeId&&[...$('bookMoveBefore').options].some(o=>o.value===beforeId))$('bookMoveBefore').value=beforeId;
    updateMovePreview();
  }
  function updateMovePreview(){
    const parent=ui.nodes.find(n=>n.id===$('bookMoveParent').value),before=ui.nodes.find(n=>n.id===$('bookMoveBefore').value);
    $('bookMovePreview').textContent=(parent?'归属：'+nodePath(parent)+' 的下级':'归属：顶层，作为独立章节')+'\n位置：'+(before?'放在「'+before.title+'」之前':'排在该层最后');
  }
  function fillMoveForm(parentId,beforeId){
    const excluded=subtree(ui.move.id),byId=new Map(ui.nodes.map(n=>[n.id,n])),n=byId.get(ui.move.id);
    if(!n)throw new Error('章节已删除，请重新选择目录。');
    $('bookMoveTitle').textContent='移动：'+nodePath(n)+' · '+(n.start_page?'PDF '+n.start_page+'–'+n.end_page:'尚未找到页码');
    $('bookMoveParent').innerHTML='<option value="">顶层 · 作为独立章节</option>'+ui.nodes.filter(x=>!excluded.has(x.id)).map(x=>`<option value="${x.id}">${esc(nodePath(x,byId))}</option>`).join('');
    $('bookMoveParent').value=parentId||'';if($('bookMoveParent').selectedIndex<0)$('bookMoveParent').value='';
    fillMovePositions(beforeId);
  }
  function openMove(id){
    if(ui.moving)return;const n=ui.nodes.find(n=>n.id===id);if(!n)return;
    ui.move={id,book_id:ui.book.id,revision:ui.outlineRevision};fillMoveForm(n.parent_id,siblingAfter(id));
    $('bookMoveStatus').textContent='';$('bookMoveSave').disabled=false;
    if(!moveDialog.open)moveDialog.showModal();$('bookMoveParent').focus({preventScroll:true});
  }
  $('bookMoveParent').onchange=()=>fillMovePositions();
  $('bookMoveBefore').onchange=()=>updateMovePreview();
  $('bookMoveForm').onsubmit=async event=>{
    event.preventDefault();if(!ui.move||ui.moving)return;
    const chosen={...ui.move,node_id:ui.move.id,parent_id:$('bookMoveParent').value||null,before_id:$('bookMoveBefore').value||null};
    $('bookMoveSave').disabled=true;$('bookMoveStatus').textContent='正在保存目录…';
    try{await performMove(chosen);moveDialog.close();}
    catch(e){
      if(ui.book?.id===chosen.book_id&&moveDialog.open){
        await refreshCurrent().catch(()=>{});
        if(ui.nodes.some(n=>n.id===chosen.node_id)){ui.move.revision=ui.outlineRevision;fillMoveForm(chosen.parent_id,chosen.before_id);}
        $('bookMoveStatus').textContent=e.message+'。请核对当前目录后再确认。';
      }else fail(e);
    }finally{$('bookMoveSave').disabled=false;}
  };
  async function performMove(chosen,undoing=false){
    if(ui.moving)throw new Error('上一次移动仍在保存，请稍候。');
    const bookId=chosen.book_id||ui.book.id;ui.moving=true;updateArrangeControls();
    try{
      const result=await api('/api/library/books/'+bookId+'/outline/move',opts('POST',{node_id:chosen.node_id,parent_id:chosen.parent_id,before_id:chosen.before_id,revision:chosen.revision}));
      if(ui.book?.id===bookId){
        await refreshCurrent();
        if(undoing)ui.undo=null;
        else if(result.changed)ui.undo=ui.outlineRevision===result.revision?{...result.undo,book_id:bookId,revision:result.revision}:null;
        if(chosen.parent_id)ui.collapsed.delete(chosen.parent_id);renderNodes();
        $('bookNodes').querySelector('[data-book-drag="'+chosen.node_id+'"]')?.focus({preventScroll:true});
        toast(result.changed?(undoing?'已撤销目录移动。':'目录已保存；原页、笔记和引用保留。'):'已经在这个位置。');
      }
      return result;
    }catch(e){if(ui.book?.id===bookId)await refreshCurrent().catch(()=>{});throw e;}
    finally{ui.moving=false;updateArrangeControls();}
  }
  function updateArrangeControls(){
    const button=$('arrangeBookNodes');if(!button)return;button.textContent=ui.arranging?'完成整理':'整理目录';button.setAttribute('aria-pressed',String(ui.arranging));button.disabled=ui.moving;
    $('undoBookMove').hidden=!ui.undo;$('undoBookMove').disabled=ui.moving;
    const status=$('bookArrangeStatus');status.hidden=!ui.arranging;
    if(!ui.drag)status.textContent=phone?'点击“移动…”选择章、节的归属和位置；整章移动会带上下级目录。':'拖动 ⠿：放在条目上方／下方调整顺序，放在中间设为下级。也可点“移动…”；Alt＋↑↓排序，Alt＋←上移一层。';
    $('bookNodes').querySelectorAll('[data-book-move],[data-book-drag]').forEach(button=>button.disabled=ui.moving);
  }
  function clearDropMarks(){$('bookNodes')?.querySelectorAll('.book-drop-before,.book-drop-after,.book-drop-inside').forEach(n=>n.classList.remove('book-drop-before','book-drop-after','book-drop-inside'));}
  function clearDrag(){ui.drag=null;clearDropMarks();$('bookNodes')?.querySelectorAll('.book-drag-source').forEach(n=>n.classList.remove('book-drag-source'));updateArrangeControls();}
  function dropPosition(target,event){
    if(!ui.drag||ui.drag.excluded.has(target.id))return null;
    const rect=event.currentTarget.getBoundingClientRect(),y=(event.clientY-rect.top)/rect.height;
    const where=y<.25?'before':y>.75?'after':'inside';
    const siblings=ui.nodes.filter(n=>n.parent_id===target.parent_id&&n.id!==ui.drag.id);
    return {where,node_id:ui.drag.id,book_id:ui.drag.book_id,revision:ui.drag.revision,parent_id:where==='inside'?target.id:target.parent_id,
      before_id:where==='before'?target.id:where==='after'?siblings[siblings.findIndex(n=>n.id===target.id)+1]?.id||null:null};
  }
  function bindOutline(){
    updateArrangeControls();if(!ui.arranging)return;
    $('bookNodes').querySelectorAll('[data-book-move],[data-book-drag]').forEach(button=>button.onclick=()=>openMove(button.dataset.bookMove||button.dataset.bookDrag));
    $('bookNodes').querySelectorAll('[data-book-drag]').forEach(handle=>{
      handle.onkeydown=event=>{
        if(!event.altKey||!['ArrowUp','ArrowDown','ArrowLeft'].includes(event.key)||ui.moving)return;event.preventDefault();
        const n=ui.nodes.find(n=>n.id===handle.dataset.bookDrag),siblings=ui.nodes.filter(x=>x.parent_id===n.parent_id),index=siblings.findIndex(x=>x.id===n.id);
        let parent=n.parent_id,before;
        if(event.key==='ArrowUp'){if(!index)return;before=siblings[index-1].id;}
        else if(event.key==='ArrowDown'){if(index===siblings.length-1)return;before=siblings[index+2]?.id||null;}
        else{if(!parent)return;const old=ui.nodes.find(x=>x.id===parent);before=siblingAfter(parent);parent=old.parent_id;}
        performMove({node_id:n.id,parent_id:parent,before_id:before,revision:ui.outlineRevision}).catch(fail);
      };
      if(phone)return;
      handle.ondragstart=event=>{if(ui.moving){event.preventDefault();return;}ui.drag={id:handle.dataset.bookDrag,book_id:ui.book.id,revision:ui.outlineRevision,excluded:subtree(handle.dataset.bookDrag)};event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',ui.drag.id);handle.closest('[data-book-node]').classList.add('book-drag-source');};
      handle.ondragend=()=>{clearDrag();renderDetail();};
    });
    if(phone)return;
    $('bookNodes').querySelectorAll('[data-book-node]').forEach(row=>{
      const target=ui.nodes.find(n=>n.id===row.dataset.bookNode);
      row.ondragover=event=>{const place=dropPosition(target,event);if(!place)return;event.preventDefault();event.dataTransfer.dropEffect='move';clearDropMarks();row.classList.add('book-drop-'+place.where);$('bookArrangeStatus').textContent=place.where==='inside'?'放到「'+target.title+'」下面，作为它的小节':'放在「'+target.title+'」'+(place.where==='before'?'之前':'之后')+'，保持同级';};
      row.ondragleave=event=>{if(!row.contains(event.relatedTarget))row.classList.remove('book-drop-before','book-drop-after','book-drop-inside');};
      row.ondrop=event=>{const place=dropPosition(target,event);if(!place)return;event.preventDefault();event.stopPropagation();clearDrag();performMove(place).catch(fail);};
    });
    const rootDrop=document.createElement('div');rootDrop.id='bookRootDrop';rootDrop.className='book-root-drop';rootDrop.textContent='拖到这里，作为目录最外层的最后一个章节';$('bookNodes').append(rootDrop);
    rootDrop.ondragover=event=>{if(!ui.drag)return;event.preventDefault();event.dataTransfer.dropEffect='move';clearDropMarks();rootDrop.classList.add('book-drop-inside');};
    rootDrop.ondrop=event=>{if(!ui.drag)return;event.preventDefault();const chosen={node_id:ui.drag.id,book_id:ui.drag.book_id,revision:ui.drag.revision,parent_id:null,before_id:null};clearDrag();performMove(chosen).catch(fail);};
  }
  function readingNotice(){
    readModels.refreshPreview();
    const front=ui.readingPriority==='foreground';
    if($('bookReadingFocusLabel'))$('bookReadingFocusLabel').hidden=ui.readingDepth!=='deep';
    const deep=ui.readingDepth==='deep';
    if($('readBookNodes'))$('readBookNodes').textContent=deep?'详细阅读所选章节':'开始整理所选章节';
    $('bookReadingNotice').textContent='先勾选下面的章、节，再点击“'+(deep?'详细阅读所选章节':'开始整理所选章节')+'”。'+
      (front?'任务会优先排队，你可以继续聊天或切换页面。':'任务会等聊天和文档生成空闲后再读，你可以离开这个页面。');
    $('bookReadingDetails').innerHTML=[
      '<p><strong>何时阅读：</strong>“优先开始”不等待后台阅读时段；“空闲时再读”会先让聊天、文档生成使用 AI，并遵守你设置的阅读时段。两种方式都需要软件保持运行，都可暂停和继续。</p>',
      '<p><strong>阅读顺序：</strong>依次阅读适合前后衔接的教材。同时阅读适合相对独立的章节，最多同时读两章；如果全局同时处理已关闭，仍会依次进行。</p>',
      '<p><strong>读到什么程度：</strong>“先梳理概念和重点”保存概念、适用条件和原文位置，方便以后查找。“详细读”会进一步解释推导和思路，通常需要更久。以前的阅读结果会保留。</p>',
      '<p><strong>页码和模型：</strong>软件先自动找所选章节的页码，找不准才请你确认。选了整章又选其小节时，已被整章覆盖的内容会合并，避免重复阅读。默认沿用当前对话的 AI 设置；可以展开“阅读模型”另选。每日阅读用量限制对两种方式都生效。</p>'
    ].join('');
  }
  function selectedCount(){
    if(!$('bookSelectedCount'))return;
    const hidden=[...ui.selected].filter(id=>!ui.visibleNodes.has(id)).length,tooMany=ui.selected.size>2000;
    const active=ui.jobs.filter(job=>['queued','running','pausing','paused'].includes(job.status)&&['read','ranges'].includes(job.kind));
    const busy=active.some(job=>job.payload.node_ids?.some(id=>ui.selected.has(id)));
    $('bookSelectedCount').textContent=ui.selected.size+' 个已选'+(hidden?'（其中 '+hidden+' 个被筛选或折叠，仍在选择内）':'')+
      (tooMany?' · 一次最多2000个，请少选一些':busy?' · 所选章节已有任务，请查看进度；已暂停的任务可以继续':
        ui.selected.size>200?' · 自动分批，每批最多100个；整章覆盖的小节会先合并':'');
    if($('bookShowProgress'))$('bookShowProgress').hidden=!busy;
    $('readBookNodes').disabled=ui.submitting||!ui.selected.size||tooMany||busy;
    $('locateBookNodes').disabled=ui.submitting||tooMany||busy||!ui.nodes.some(n=>ui.selected.has(n.id)&&!n.confirmed);
    if($('reviewBookRanges'))$('reviewBookRanges').disabled=!ui.nodes.some(n=>!n.confirmed&&n.provenance?.auto_range);
    if($('completeBookRanges')){const pending=new Set(ui.nodes.filter(n=>!n.confirmed).map(n=>n.id));$('completeBookRanges').disabled=ui.submitting||pending.size>2000||!pending.size||ui.jobs.some(j=>['queued','running','pausing','paused'].includes(j.status)&&['ranges','read'].includes(j.kind)&&j.payload.node_ids?.some(id=>pending.has(id)));}
    if($('clearBookSelection'))$('clearBookSelection').disabled=!ui.selected.size;
    if($('selectFilteredBookNodes'))$('selectFilteredBookNodes').disabled=!ui.matchedNodes.size;
  }
  function renderJobs(){
    const host=$('bookJobs');if(!host)return;
    const tocBusy=Boolean(ui.tocSubmitting)||ui.jobs.some(j=>j.kind==='toc'&&['queued','running','pausing','paused'].includes(j.status));
    if($('bookAutoToc'))$('bookAutoToc').disabled=tocBusy;
    if($('bookTocForm'))$('bookTocForm').querySelector('button[type="submit"]').disabled=tocBusy;
    const key=JSON.stringify([ui.nodes.length,ui.jobs.map(j=>[j.id,j.status,j.progress,j.updated_at])]);
    if(host.dataset.jobsKey===key){if($('bookSelectedCount'))selectedCount();return;}
    const expanded=new Map([...host.querySelectorAll('[data-toc-evidence]')].map(e=>[e.dataset.tocEvidence,e.open]));
    host.dataset.jobsKey=key;
    $('bookJobs').innerHTML=ui.jobs.map(job=>`<article class="book-job"><div><strong>${job.kind==='toc'?'目录识别':job.kind==='ranges'?'查找章节页码':'章节阅读'} · ${job.status==='queued'&&job.result.policy_wait?(job.result.policy_wait.kind==='window'?'等待时段':'等待额度'):job.status==='queued'&&job.payload.foreground?'正在排队，等待可用的 AI':phases[job.status]}</strong><span>${job.status==='failed'?'未完成':job.progress+'%'}</span></div><span class="book-job-priority">${job.payload.foreground?'优先阅读 · 与聊天共用 AI':'空闲时阅读 · 聊天优先'}</span><progress value="${job.progress}" max="100"></progress><p>${esc(job.result.stage||(job.payload.foreground?'已排队，等待 AI 开始':'等待聊天和文档任务空闲'))}</p>${job.result.policy_wait?.next_at?`<small>下次允许：${esc(new Date(job.result.policy_wait.next_at).toLocaleString())}</small>`:''}${job.result.workers?`<small>实际同时阅读数：${job.result.workers} · ${job.result.workers>1?'并行':'串行'}${job.result.parallel_reason?'（'+esc(job.result.parallel_reason)+'）':''}</small>`:''}${job.error?`<p class="book-error">${esc(window.studyforgeOperationErrors?.summary(job.error)||job.error)}</p>`:''}<div class="book-actions">${job.result.pending_node_ids?.length?`<button type="button" data-book-pending="${job.id}">确认 ${job.result.pending_node_ids.length} 处页码</button>`:''}${job.result.policy_wait?'<button type="button" data-book-policy-open>调整阅读安排</button>':''}${['queued','running'].includes(job.status)?`<button type="button" data-book-job="${job.id}" data-action="pause">暂停</button>`:''}${['paused','pausing','failed'].includes(job.status)?`<button type="button" data-book-job="${job.id}" data-action="resume">${job.status==='failed'?'重试未完成步骤':'继续'}</button>`:''}${['queued','running','pausing','paused'].includes(job.status)?`<button type="button" data-book-job="${job.id}" data-action="cancel">取消</button>`:''}</div></article>`).join('');
    ui.jobs.forEach((job,index)=>{if(job.error)window.studyforgeOperationErrors?.attach($('bookJobs').children[index].querySelector('.book-actions'),job.error);});
    ui.jobs.forEach((job,index)=>{if(!job.result.total_pages)return;const detail=document.createElement('small');detail.textContent=`已读页面已保存：${job.result.pages_processed||0}/${job.result.total_pages} 页；本章笔记完成后即可引用。`;$('bookJobs').children[index].querySelector('progress').after(detail);});
    ui.jobs.forEach((job,index)=>{
      const retryText=window.studyforgeTaskRetry?.summary(job);
      if(retryText){const notice=document.createElement('p');notice.className='task-retry-status book-notice';notice.setAttribute('role','status');notice.textContent=retryText;$('bookJobs').children[index].querySelector('progress').after(notice);}
      if(job.kind==='read'||job.kind==='ranges'&&(job.payload.read_after||job.payload.allow_ai)){
        const info=document.createElement('p');info.className='book-job-model';
        const p=job.payload,vision=p.vision_model||(p.provider==='deepseek'?'旧任务未保存画面模型':p.model||'服务默认');
        info.textContent=`任务模型：${p.provider==='codex'?'Codex':p.provider==='deepseek'?'DeepSeek':p.provider} / ${p.model||'服务默认'} · 推理 ${p.effort||'自动'}；扫描页核对 ${vision}`;
        $('bookJobs').children[index].querySelector('progress').before(info);
      }
      if(job.kind!=='read')return;
      const article=$('bookJobs').children[index],deep=job.payload.depth==='deep';
      if(deep)article.querySelector('strong').textContent=article.querySelector('strong').textContent.replace('章节阅读','重点精读');
      const profile=document.createElement('small');profile.className='book-job-profile';
      profile.textContent=deep?'读到什么程度：重点精读'+(job.payload.focus?' · '+job.payload.focus:' · 按原文难点整理'):'读到什么程度：梳理重点';
      article.querySelector('progress').before(profile);
    });
    ui.jobs.forEach((job,index)=>{
      const total=job.result.batches_total||job.payload.batches_total;if(!total)return;
      const detail=document.createElement('small');detail.className='book-batch-progress';detail.setAttribute('role','status');
      const count=job.result.nodes_total||job.payload.batch_node_ids?.length||job.payload.node_ids.length;
      detail.textContent=`自动分批：已保存 ${job.result.batches_completed||0}/${total} 批 · 已处理 ${job.result.nodes_completed_count||0}/${count} 个章节 · 每批最多 ${job.payload.batch_size} 个。暂停或重启后复用已保存步骤。`;
      $('bookJobs').children[index].querySelector('progress').after(detail);
    });
    ui.jobs.forEach((job,index)=>{
      const found=job.result.toc_discovery;if(!found)return;
      const detail=document.createElement('details');detail.className='book-toc-evidence';detail.dataset.tocEvidence=job.id;
      detail.open=expanded.has(job.id)?expanded.get(job.id):found.status==='review';
      const pages=found.candidate_pages||[];
      detail.innerHTML=`<summary>目录查找依据 · 检查 ${found.inspected_pages?.length||0} 页${pages.length?' · 候选 PDF '+pages.join('、'):''}</summary>
        ${(found.warnings||[]).map(w=>`<p class="book-error">${esc(w)}</p>`).join('')}
        ${(found.evidence||[]).map(e=>`<div><button type="button" data-book-toc-page="${e.page}">查看 PDF 第 ${e.page} 页</button><small>${e.recognized_entries??e.entries} 个${e.recognized_entries===undefined?'候选':''}条目 · ${e.method==='native_pdf'?'PDF 原文字':'本机 OCR'}${e.label?.length?' · '+esc(e.label.join(' / ')):''}</small><p>${esc((e.samples||[]).join('；'))}</p></div>`).join('')}
        ${!ui.nodes.length&&pages.length?`<button type="button" data-book-toc-use="${job.id}">填入候选页，手动核对后建立</button>`:''}`;
      $('bookJobs').children[index].append(detail);
    });
    $('bookJobs').querySelectorAll('[data-book-toc-page]').forEach(button=>button.onclick=()=>showPreviewOnly(Number(button.dataset.bookTocPage)).catch(fail));
    $('bookJobs').querySelectorAll('[data-book-toc-use]').forEach(button=>button.onclick=()=>{
      const found=ui.jobs.find(j=>j.id===button.dataset.bookTocUse)?.result.toc_discovery;if(!found||!$('bookTocManual'))return;
      $('bookTocManual').open=true;$('bookTocPages').value=found.candidate_pages.join(',');$('bookTocPages').focus();
    });
    $('bookJobs').querySelectorAll('[data-book-job]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api('/api/library/jobs/'+button.dataset.bookJob+'/'+button.dataset.action,{method:'POST'});await refreshCurrent();}catch(e){fail(e);button.disabled=false;}});
    $('bookJobs').querySelectorAll('[data-book-policy-open]').forEach(button=>button.onclick=()=>window.libraryPolicyOpen?.());
    $('bookJobs').querySelectorAll('[data-book-pending]').forEach(button=>button.onclick=()=>{
      const pending=ui.jobs.find(j=>j.id===button.dataset.bookPending).result.pending_node_ids.filter(id=>ui.nodes.some(n=>n.id===id&&!n.confirmed));
      if(!pending.length)return toast('这些范围已校正，可直接安排阅读。');
      openReview(pending).catch(fail);
    });
    if($('bookSelectedCount'))selectedCount();
  }
  async function startToc(event,automatic=false){
    event?.preventDefault();if(ui.tocSubmitting||!ui.book)return;
    const bookId=ui.book.id,front=ui.readingPriority==='foreground';
    const limit=Number($('bookTocScanLimit').value);
    if(automatic&&(!Number.isInteger(limit)||limit<1||limit>64)){fail(new Error('查找范围请填写 1–64 页之间的整数。'));return;}
    const offset=!automatic&&$('bookPdfFirst').value?{first_printed:Number($('bookPrintedFirst').value),first_pdf:Number($('bookPdfFirst').value)}:{};
    const payload=automatic?{auto_discover:true,scan_limit:limit,foreground:front}:{page_spec:$('bookTocPages').value.trim(),...offset,foreground:front};
    ui.tocSubmitting=true;renderJobs();
    try{await api('/api/library/books/'+bookId+'/toc',opts('POST',payload));if(ui.book?.id===bookId)await refreshCurrent();startPoll();toast(automatic?'已安排本机查找目录，可在任务卡暂停或继续。':'已安排目录识别，仅处理指定目录页。');}
    catch(e){fail(e);}finally{ui.tocSubmitting=false;if(ui.book&&$('bookJobs'))renderJobs();}
  }
  async function startRead(){
    if(!ui.selected.size||ui.submitting)return;
    if(ui.nodes.some(n=>ui.selected.has(n.id)&&!n.confirmed))return startRanges([...ui.selected],true);
    const bookId=ui.book.id,payload={node_ids:[...ui.selected],parallel:ui.readingMode==='parallel',foreground:ui.readingPriority==='foreground',depth:ui.readingDepth,focus:ui.readingDepth==='deep'?ui.readingFocus.trim():''};
    ui.submitting=true;selectedCount();
    try{Object.assign(payload,await model());await api('/api/library/books/'+bookId+'/read',opts('POST',payload));if(ui.book?.id===bookId)await refreshCurrent();startPoll();toast(payload.foreground?'阅读任务已排队，你可以继续聊天。':'已安排阅读，聊天和文档任务空闲后开始。');}
    finally{ui.submitting=false;selectedCount();}
  }
  async function startRanges(ids,readAfter){
    if(ui.submitting||!ids.length)return;
    const bookId=ui.book.id,payload={node_ids:ids,foreground:ui.readingPriority==='foreground',parallel:ui.readingMode==='parallel',read_after:readAfter,allow_ai:ui.allowRangeAI,
      depth:readAfter?ui.readingDepth:'index',focus:readAfter&&ui.readingDepth==='deep'?ui.readingFocus.trim():''};
    ui.submitting=true;selectedCount();
    try{if(readAfter||payload.allow_ai)Object.assign(payload,await model());await api('/api/library/books/'+bookId+'/ranges',opts('POST',payload));await refreshCurrent();startPoll();
      toast(readAfter?'正在自动找所选章节的页码，找到后继续阅读；不确定的部分会请你确认。':'正在查找所选章节的页码，找不准时会请你确认。不会开始阅读正文，也不改变已确认的页码。');}
    finally{ui.submitting=false;selectedCount();}
  }
  async function addNode(){
    const byId=new Map(ui.nodes.map(n=>[n.id,n]));
    const form=dialog('addBookNodeDialog','补充目录项','<form><label>标题<input maxlength="200" required></label><label>归属章节<select><option value="">顶层章节</option>'+ui.nodes.map(n=>`<option value="${n.id}">${esc(nodePath(n,byId))}</option>`).join('')+'</select></label><button type="submit">新增后定位范围</button></form>');
    form.addEventListener('close',()=>form.remove());form.showModal();
    form.querySelector('form').onsubmit=async e=>{e.preventDefault();try{const n=await api('/api/library/books/'+ui.book.id+'/nodes',opts('POST',{title:form.querySelector('input').value,parent_id:form.querySelector('select').value||null}));form.close();await refreshCurrent();await editScope(n.id);}catch(er){fail(er);}};
  }
  async function removeBook(){
    const b=ui.book;
    const confirm=dialog('deleteBookDialog','删除全局书籍',`<p>将删除书库中“${esc(b.title)}”的副本、目录和阅读缓存，所有对话中的书库引用会失效。原来导入的文件不受影响。</p><button type="button" class="danger-action" data-delete>确认删除这本书</button>`);confirm.addEventListener('close',()=>confirm.remove());confirm.showModal();
    confirm.querySelector('[data-delete]').onclick=async()=>{try{await api('/api/library/books/'+b.id,{method:'DELETE'});confirm.close();ui.book=null;ui.detailKey='';await refreshShelf();if(!ui.book)$('bookDetail').innerHTML='<p class="book-notice">书架为空。可重新放入教材。</p>';await reloadReferences();}catch(e){fail(e);}};
  }
  async function editScope(id){
    const n=ui.nodes.find(x=>x.id===id);if(!n)throw new Error('目录项已被删除，请刷新书库。');ui.scope=n;$('bookNodeTitle').value=n.title;$('bookStart').value=n.start_page||1;$('bookEnd').value=n.end_page||n.start_page||1;
    rangeTools.hidden=false;$('bookScopeAuto').disabled=Boolean(n.confirmed)||ui.submitting;
    scopeDialog.querySelector('h2').textContent='调整章节的阅读范围';
    const auto=n.provenance?.auto_range;
    const adjusted=auto&&auto.crop&&(auto.title!==n.title||Object.entries(auto.crop).some(([key,value])=>Math.abs(Number(n[key])-Number(value))>1e-6));
    $('bookRangeEvidence').textContent=auto?(adjusted?'当前范围已手动调整；以下为以前的定位证据，仅供参考。':auto.reliable?'自动定位可用':'自动定位待核对')+' · '+(auto.start?auto.start.basis+'：PDF第'+auto.start.page+'页「'+auto.start.text+'」':'起始标题未确定')+
      (auto.next_heading?'；结束于PDF第'+auto.next_heading.page+'页「'+auto.next_heading.text+'」之前':'')+(auto.reason?'。'+auto.reason:''):
      n.confirmed?'已确认范围，自动定位不会覆盖；如有误，可在下方手动校正。':'可先自动定位；核对实际标题与页内边界，不需要逐章手填PDF页码。';
    $('bookScopeForm').querySelector('button[type="submit"]').hidden=false;
    $('bookStartY').value=Number((n.start_y*100).toFixed(6));$('bookEndY').value=Number((n.end_y*100).toFixed(6));$('bookScopeConfirmed').checked=Boolean(n.confirmed);
    scopeControls(false);$('bookCropNotice').textContent='点击原页可调整本章节；范围改变后请重新确认。';
    $('bookScopeForm').hidden=false;$('bookPreviewNumber').value=n.start_page||1;$('bookCropLine').hidden=true;
    if(!scopeDialog.open)scopeDialog.showModal();await loadPreview();
  }
  async function showPreviewOnly(page=1){
    rangeTools.hidden=true;
    scopeDialog.querySelector('h2').textContent='教材原页预览';
    const n={id:null,title:'仅预览',start_page:1,end_page:1,start_y:0,end_y:1};
    ui.scope=n;$('bookScopeForm').hidden=false;$('bookNodeTitle').value=n.title;$('bookStart').value=1;$('bookEnd').value=1;$('bookStartY').value=0;$('bookEndY').value=100;
    $('bookScopeForm').querySelector('button[type="submit"]').hidden=!n.id;$('bookPreviewNumber').value=page;
    scopeControls(true);$('bookCropNotice').textContent='原页预览不会修改目录项或阅读范围。';
    if(!scopeDialog.open)scopeDialog.showModal();await loadPreview();
  }
  function scopeControls(preview){
    $('bookNodeTitle').closest('label').hidden=preview;scopeDialog.querySelector('.book-fields').hidden=preview;
    $('bookScopeConfirmed').closest('label').hidden=preview;$('bookCropEdge').closest('label').hidden=preview;
    $('bookPreviewStart').hidden=preview;$('bookPreviewEnd').hidden=preview;
    for(const id of ['bookNodeTitle','bookStart','bookEnd','bookStartY','bookEndY','bookScopeConfirmed','bookCropEdge'])$(id).disabled=preview;
  }
  let previewCancel=null;
  async function loadPreview(){
    const number=Number($('bookPreviewNumber').value);
    if(!Number.isInteger(number)||number<1||number>ui.book.page_count)throw new Error('请填写有效 PDF 页码');
    previewCancel?.();const image=$('bookPagePreview');image.dataset.ready='false';image.dataset.page='';$('bookCropLine').hidden=true;
    const url=new URL('/api/library/books/'+ui.book.id+'/page?page='+number,location.href).href;
    $('bookCropNotice').textContent='正在加载 PDF 第 '+number+' 页…';
    return new Promise((resolve,reject)=>{
      const clean=()=>{image.removeEventListener('load',loaded);image.removeEventListener('error',failed);if(previewCancel===cancel)previewCancel=null;};
      const cancel=()=>{clean();resolve(false);};
      const loaded=()=>{if(image.currentSrc!==url)return;clean();image.dataset.ready='true';image.dataset.page=number;$('bookCropNotice').textContent=ui.scope?.id?'PDF 第 '+number+' 页已加载，可点击调整边界。':'仅预览 PDF 第 '+number+' 页，不修改范围。';resolve(true);};
      const failed=()=>{clean();reject(new Error('原页加载失败，请重试。'));};
      previewCancel=cancel;image.addEventListener('load',loaded);image.addEventListener('error',failed);image.src=url;
      if(image.complete&&image.naturalWidth&&image.currentSrc===url)loaded();
    });
  }
  scopeDialog.addEventListener('close',()=>{previewCancel?.();$('bookPagePreview').dataset.ready='false';const back=ui.reviewReturn;ui.reviewReturn=null;if(back&&ui.book?.id===back.book)openReview(back.ids,back).catch(fail);});
  for(const id of ['bookStart','bookEnd','bookStartY','bookEndY'])$(id).oninput=()=>{$('bookScopeConfirmed').checked=false;};
  $('bookPreviewPage').onclick=()=>loadPreview().catch(fail);
  $('bookPagePreview').onclick=e=>{
    if(!ui.scope?.id||e.target.dataset.ready!=='true')return;
    const rect=e.target.getBoundingClientRect(),page=Number(e.target.dataset.page),edge=$('bookCropEdge').value,percent=Math.round(100*(e.clientY-rect.top)/rect.height);
    if(edge==='start'){$('bookStart').value=page;$('bookStartY').value=Math.max(0,Math.min(99,percent));}
    else{$('bookEnd').value=page;$('bookEndY').value=Math.max(1,Math.min(100,percent));}
    $('bookScopeConfirmed').checked=false;$('bookCropLine').hidden=false;$('bookCropLine').style.top=percent+'%';$('bookCropNotice').textContent=`${edge==='start'?'起点':'终点'}设为 PDF 第 ${page} 页 ${percent}% 位置，请确认后保存。`;
  };
  $('bookScopeForm').onsubmit=async e=>{
    e.preventDefault();if(!ui.scope?.id)return;const button=e.target.querySelector('button[type="submit"]');button.disabled=true;
    const coordinate=(input,key)=>{const value=Number($(input).value)/100;return Math.abs(value-ui.scope[key])<1e-8?ui.scope[key]:Number(value.toFixed(8));};
    try{await api('/api/library/nodes/'+ui.scope.id,opts('PUT',{title:$('bookNodeTitle').value,start_page:Number($('bookStart').value),end_page:Number($('bookEnd').value),start_y:coordinate('bookStartY','start_y'),end_y:coordinate('bookEndY','end_y'),confirmed:$('bookScopeConfirmed').checked}));await refreshCurrent();scopeDialog.close();}
    catch(er){fail(er);}finally{button.disabled=false;}
  };
  async function showNotes(id,readingId=null){
    const n=ui.nodes.find(n=>n.id===id);if(!n)throw new Error('章节已改变，请从当前目录重新打开笔记。');
    ui.notes?.controller.abort();const token=++ui.notesEpoch;
    const note={id,book:ui.book.id,page:n.start_page,controller:new AbortController()};ui.notes=note;
    notesDialog.querySelector('h2').textContent='阅读笔记 · '+n.title;
    const source=document.createElement('p');source.className='book-notes-source';
    source.textContent=ui.book.title+' · '+nodePath(n)+(n.start_page?' · PDF '+n.start_page+'–'+n.end_page:'');
    const loading=document.createElement('p');loading.className='book-notice';loading.textContent='正在打开已保存的阅读笔记…';loading.setAttribute('role','status');
    $('bookNotesBody').replaceChildren(source,loading);$('bookNotesOriginal').disabled=!note.page;$('bookNotesReference').disabled=true;$('bookNotesDeepen').disabled=true;
    if(!notesDialog.open)notesDialog.showModal();
    try{
      const query=readingId?'?reading_id='+encodeURIComponent(readingId):'?depth='+ui.readingDepth+(ui.readingDepth==='deep'?'&focus='+encodeURIComponent(ui.readingFocus.trim()):'');
      const result=await api('/api/library/nodes/'+id+'/notes'+query,{signal:note.controller.signal});
      if(token!==ui.notesEpoch||!notesDialog.open||ui.book?.id!==note.book)return;
      const warning=document.createElement('p');warning.className='book-notice';warning.textContent=result.warnings.length?result.warnings.join('\n'):'以下是 AI 整理笔记；重要论断仍需核对原页，不证明学生已经掌握。';
      const content=document.createElement('div');content.className='message-content';
      renderLessonText(content,result.notes);
      const versions=document.createElement('label');versions.className='book-notes-versions';versions.textContent='阅读版本';
      const picker=document.createElement('select');picker.id='bookNotesVersion';
      for(const v of result.versions||[]){const option=document.createElement('option');option.value=v.id;option.textContent=(v.suspect?'待核对 · ':'')+(v.depth==='deep'?'重点精读':'梳理重点')+' · '+(v.focus?v.focus.slice(0,50)+' · ':'')+(v.model||v.provider)+' · '+new Date(v.updated_at).toLocaleString();option.title=(v.focus||'')+' · 推理 '+(v.effort||'自动')+' · 扫描页核对 '+(v.vision_model||'旧记录未保存');picker.append(option);}
      picker.value=result.reading?.id||'';picker.onchange=()=>showNotes(id,picker.value).catch(fail);versions.append(picker);
      const emphasis=document.createElement('p');emphasis.className='book-notice';emphasis.textContent=result.reading?.depth==='deep'?'本版为重点精读。'+(result.reading.focus?'精读问题：'+result.reading.focus:'围绕原文概念、论证与构造动机整理。'):'本版为梳理重点；可点击“精读这一章节”进一步整理原页难点。';
      note.focus=result.reading?.focus||'';
      const review=document.createElement('form');review.className='book-note-review';review.innerHTML='<h3>疑点与校订</h3><p class="book-notice">只影响这个阅读版本。标记后，后续引用继续使用原页，跳过本版 AI 笔记。校订作为独立意见供导师核对，不直接记入学习画像；原始笔记保留。</p><label class="book-note-flag"><input type="checkbox" data-note-suspect> 此版本有疑点，暂停引用它的 AI 笔记</label><label>我的校订或待核实问题<textarea data-note-comment rows="4" maxlength="1200" placeholder="指出哪一步有问题、原页位置，以及你的修正或疑问（最多 1200 字）。保存后生效。"></textarea></label><div class="book-note-actions"><button type="submit">保存校订</button><button type="button" data-note-clear>清除并保存</button></div><p class="book-notice" data-note-status role="status"></p>';
      const annotation=result.annotation||{suspect:false,comment:'',revision:0},flag=review.querySelector('[data-note-suspect]'),comment=review.querySelector('[data-note-comment]'),status=review.querySelector('[data-note-status]');flag.checked=annotation.suspect;comment.value=annotation.comment;status.textContent=annotation.suspect?'此版本的 AI 笔记已暂停参与后续引用。':annotation.comment?'已保存独立校订；导师引用时会同时得到它。':'尚未添加校订。';
      review.onsubmit=async event=>{event.preventDefault();const buttons=[...review.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);status.textContent='正在保存此版本的校订…';try{const saved=await api('/api/library/nodes/'+id+'/notes/'+result.reading.id+'/annotation',opts('PUT',{suspect:flag.checked,comment:comment.value,revision:annotation.revision,reading_updated_at:result.reading.updated_at}));Object.assign(annotation,saved);if(token!==ui.notesEpoch||!review.isConnected)return;status.textContent=saved.suspect?'已保存：跳过本版 AI 笔记，仍可引用原页。':saved.comment?'校订已保存，后续引用会携带它供核对。':'疑点标记和校订已清除。';const option=[...picker.options].find(o=>o.value===result.reading.id);if(option)option.textContent=option.textContent.replace(/^待核对 · /,'');if(option&&saved.suspect)option.textContent='待核对 · '+option.textContent;}catch(e){if(token===ui.notesEpoch&&review.isConnected)status.textContent='未保存：'+e.message;fail(e);}finally{buttons.forEach(b=>b.disabled=false);}};
      review.querySelector('[data-note-clear]').onclick=()=>{flag.checked=false;comment.value='';review.requestSubmit();};
      $('bookNotesBody').replaceChildren(source,...(picker.options.length?[versions]:[]),emphasis,warning,review,content);$('bookNotesReference').disabled=!current().chat;
      $('bookNotesDeepen').disabled=false;$('bookNotesDeepen').textContent=result.reading?.depth==='deep'?'换个问题精读':'精读这一章节';
    }catch(e){
      if(note.controller.signal.aborted||token!==ui.notesEpoch||!notesDialog.open)return;
      loading.classList.add('book-error');loading.textContent='笔记打开未完成：'+e.message;
      const retry=document.createElement('button');retry.type='button';retry.textContent='重试打开笔记';retry.onclick=()=>showNotes(id,readingId).catch(fail);$('bookNotesBody').append(retry);
    }
  }
  function renderReferences(){
    $('bookReferenceMode').value=ui.pref.mode;
    $('bookReferences').innerHTML=ui.pref.references.map(ref=>`<div class="book-reference-chip"><strong>${esc(ref.title||'目录项')}</strong><small>${esc(ref.book_title||'')} · ${ref.state==='read'?'AI已整理':'尚未阅读'}</small><div><select data-book-purpose="${ref.node_id}" aria-label="引用用途"><option value="reference" ${ref.purpose==='reference'?'selected':''}>参考背景</option><option value="primary" ${ref.purpose==='primary'?'selected':''}>重点讲解对象</option></select><button type="button" data-remove-book-ref="${ref.node_id}" aria-label="移除引用">✕</button></div></div>`).join('');
    $('bookReferences').querySelectorAll('[data-book-purpose]').forEach(select=>select.onchange=()=>{ui.pref.references.find(r=>r.node_id===select.dataset.bookPurpose).purpose=select.value;saveReferences().catch(fail);});
    $('bookReferences').querySelectorAll('[data-remove-book-ref]').forEach(button=>button.onclick=()=>{ui.pref.references=ui.pref.references.filter(r=>r.node_id!==button.dataset.removeBookRef);renderReferences();saveReferences().catch(fail);});
    const pending=Boolean(ui.pendingRefs.get(ui.chat));
    $('bookReferenceMode').disabled=!ui.chat||pending;
    $('bookReferences').querySelectorAll('button,select').forEach(control=>control.disabled=pending);
    window.dispatchEvent(new CustomEvent('studyforge-library-references',{detail:{chat:ui.chat,project:ui.project,pref:ui.pref,ready:ui.prefReady,pending}}));
  }
  async function reloadReferences(chat=current().chat,project=current().project){
    const changed=ui.chat!==chat||ui.project!==project;
    const token=++ui.epoch;ui.prefRevision++;ui.chat=chat;ui.project=project;ui.prefReady=false;ui.pref={mode:'auto',references:[]};renderReferences();
    if(changed){ui.matchHistory=[];ui.matchRevision++;renderMatchHistory();}const revision=ui.matchRevision;
    if(!chat||!project)return;
    await (ui.saves.get(chat)||Promise.resolve()).catch(()=>{});
    if(token!==ui.epoch||current().chat!==chat)return;
    const [pref,history]=await Promise.all([api('/api/library/conversations/'+chat+'?project_id='+project),
      api('/api/library/conversations/'+chat+'/history?project_id='+project)]);
    if(token!==ui.epoch||current().chat!==chat)return;ui.pref=pref;ui.prefReady=true;renderReferences();
    if(revision===ui.matchRevision)ui.matchHistory=history.entries;
    else{const found=new Map([...ui.matchHistory,...history.entries].map(entry=>[entry.id,entry]));ui.matchHistory=[...found.values()].sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,30);}
    renderMatchHistory();
  }
  function queueReferenceSave(chat,operation){
    const pending=(ui.saves.get(chat)||Promise.resolve()).catch(()=>{}).then(operation);
    ui.saves.set(chat,pending);ui.save=pending;
    pending.then(()=>{if(ui.saves.get(chat)===pending)ui.saves.delete(chat);},()=>{});
    return pending;
  }
  async function saveReferences(){
    const {chat,project}=ui;if(!chat||!project)return;
    const revision=++ui.prefRevision;
    const value={project_id:project,mode:ui.pref.mode,references:ui.pref.references.map(r=>({node_id:r.node_id,purpose:r.purpose}))};
    const result=await queueReferenceSave(chat,()=>api('/api/library/conversations/'+chat,opts('PUT',value)));
    if(ui.chat===chat&&current().chat===chat&&revision===ui.prefRevision){ui.epoch++;ui.pref=result;ui.prefReady=true;renderReferences();}return result;
  }
  async function addReference(id){
    const target=current();if(!target.chat)throw new Error('先在项目中新建或选择学习对话，再引用章节。');
    const n=ui.nodes.find(r=>r.id===id),book=ui.book;
    if(!n||!book)throw new Error('章节已改变，请从当前目录重新选择引用。');
    if(n?.state==='read'){
      const previous=ui.pref.references.find(ref=>ref.node_id===id);
      await window.libraryAddReference({node_id:id},previous?.purpose||'reference',target);
      return toast('已加入当前对话书库参考；可将用途改为“重点讲解对象”。');
    }
    await (ui.saves.get(target.chat)||Promise.resolve());
    if(current().chat!==target.chat)throw new Error('对话已经切换，请重新选择章节。');
    if(ui.chat!==target.chat)await reloadReferences();
    if(current().chat!==target.chat||ui.book?.id!==book.id)throw new Error('对话或教材已经切换，请重新选择引用。');
    if(!ui.pref.references.some(r=>r.node_id===id)){
      ui.pref.references.push({node_id:id,purpose:'reference',title:n.title,book_title:book.title,book_id:book.id,state:n.state});
    }
    if(ui.pref.mode==='off')ui.pref.mode='manual';await saveReferences();toast('已加入当前对话书库参考；可将用途改为“重点讲解对象”。');
  }
  $('openBookLibrary').onclick=()=>open().catch(fail);
  $('bookReferenceMode').onchange=()=>{ui.pref.mode=$('bookReferenceMode').value;saveReferences().catch(fail);};
  $('bookSearch').oninput=searchShelf;
  $('bookUpload').onchange=async()=>{
    const files=[...$('bookUpload').files];$('bookUpload').value='';$('bookUpload').disabled=true;
    try{for(const [index,file] of files.entries()){$('bookUploadStatus').textContent=`放入 ${index+1}/${files.length}：${file.name}`;const data=new FormData();data.append('file',file);const result=await api('/api/library/books',{method:'POST',body:data});await refreshShelf();await selectBook(result.book.id);}
      $('bookUploadStatus').textContent='已放入书架；有 PDF 书签时直接建目录，扫描书选择目录页，尚未通读正文。';}
    catch(e){fail(e);$('bookUploadStatus').textContent='上传未完成：'+e.message;}finally{$('bookUpload').disabled=false;}
  };
  window.libraryConversationChanged=(chat,project)=>reloadReferences(chat,project).catch(fail);
  window.libraryRefreshMatches=async(owner=current())=>{
    const revision=ui.matchRevision;
    if(!owner.chat||!owner.project)return;
    const result=await api('/api/library/conversations/'+owner.chat+'/history?project_id='+owner.project);
    if(owner.chat!==current().chat||owner.project!==current().project||ui.chat!==owner.chat)return;
    if(revision===ui.matchRevision)ui.matchHistory=result.entries;
    else{const found=new Map([...ui.matchHistory,...result.entries].map(entry=>[entry.id,entry]));ui.matchHistory=[...found.values()].sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,30);}
    renderMatchHistory();
  };
  window.libraryOpen=open;
  window.libraryFlush=(chat=current().chat)=>ui.saves.get(chat)||Promise.resolve();
  window.libraryReferenceOwner=current;
  window.libraryAddReference=(node,purpose='reference',owner=current())=>{
    const same=()=>owner.chat===current().chat&&owner.project===current().project;
    if(!owner.chat||!same())return Promise.reject(new Error('对话已经切换，请在当前对话重新选择章节。'));
    const revision=++ui.prefRevision;
    ui.pendingRefs.set(owner.chat,(ui.pendingRefs.get(owner.chat)||0)+1);renderReferences();
    return queueReferenceSave(owner.chat,async()=>{
      try{
        if(!same())throw new Error('对话已经切换，请重新选择章节。');
        const result=await api('/api/library/conversations/'+owner.chat+'/references',opts('POST',{project_id:owner.project,node_id:node.node_id,purpose}));
        if(same()&&ui.chat===owner.chat&&revision===ui.prefRevision){ui.epoch++;ui.pref=result;ui.prefReady=true;renderReferences();}
        return result;
      }finally{ui.pendingRefs.set(owner.chat,Math.max(0,(ui.pendingRefs.get(owner.chat)||1)-1));renderReferences();}
    });
  };
  window.libraryRemoveReference=async(id,owner=current())=>{
    if(ui.pendingRefs.get(owner.chat))throw new Error('引用正在保存，请稍后再移除。');
    if(owner.chat!==current().chat||owner.project!==current().project)throw new Error('对话已经切换，请重新选择。');
    if(ui.chat!==owner.chat||!ui.prefReady)await reloadReferences(owner.chat,owner.project);
    if(owner.chat!==current().chat||ui.chat!==owner.chat)throw new Error('对话已经切换，请重新选择。');
    ui.pref.references=ui.pref.references.filter(r=>r.node_id!==id);renderReferences();return saveReferences();
  };
  window.libraryReferencePurpose=async(id,purpose,owner=current())=>{
    if(ui.pendingRefs.get(owner.chat))throw new Error('引用正在保存，请稍后再修改用途。');
    if(owner.chat!==current().chat||owner.project!==current().project)throw new Error('对话已经切换，请重新选择。');
    if(ui.chat!==owner.chat||!ui.prefReady)await reloadReferences(owner.chat,owner.project);
    if(owner.chat!==current().chat||ui.chat!==owner.chat)throw new Error('对话已经切换，请重新选择。');
    const ref=ui.pref.references.find(r=>r.node_id===id);if(!ref)throw new Error('该引用已移除，请重新选择。');
    ref.purpose=purpose;return saveReferences();
  };
  window.libraryHasPrimary=()=>ui.chat===current().chat&&ui.pref.mode!=='off'&&ui.pref.references.some(r=>r.purpose==='primary'&&r.state==='read');
  window.libraryViewChanged=view=>{if(view==='library'){$('viewLabel').textContent='全局书库';refreshShelf().then(()=>refreshCurrent()).catch(fail);startPoll();}};
  function renderMatchHistory(){
    const host=$('bookReferenceStatus'),key=ui.chat+'|'+JSON.stringify(ui.matchHistory);
    if(ui.matchRenderKey===key)return;
    const previous=host.querySelector('.book-match-list'),scroll=previous?.scrollTop||0;
    const expanded=new Set([...host.querySelectorAll('.book-match-entry[open][data-user-expanded="true"]')].map(el=>el.dataset.lookupId));
    ui.matchRenderKey=key;host.replaceChildren();
    if(!ui.matchHistory.length){host.textContent='自动引用仅作辅助；未读章节先征求你的选择。检索记录随本对话保存。';return;}
    const heading=document.createElement('div');heading.className='book-reference-head';
    const title=document.createElement('strong');title.textContent='书库检索记录 · '+ui.matchHistory.length+' 次';
    const clear=document.createElement('button');clear.type='button';clear.textContent='清空记录';clear.onclick=()=>{
      const owner=current(),box=dialog('clearBookHistory','清空本对话检索记录','<p>仅清空当前对话的章节检索导航；书籍、阅读笔记、手动引用和聊天保留。</p><button type="button" data-clear>确认清空记录</button>');
      box.addEventListener('close',()=>box.remove());box.showModal();box.querySelector('[data-clear]').onclick=async()=>{
        try{await api('/api/library/conversations/'+owner.chat+'/history?project_id='+owner.project,{method:'DELETE'});
          if(current().chat===owner.chat){ui.matchRevision++;ui.matchHistory=[];renderMatchHistory();}box.close();}catch(e){fail(e);}
      };
    };heading.append(title,clear);host.append(heading);
    const list=document.createElement('div');list.className='book-match-list';list.tabIndex=0;list.setAttribute('aria-label','本对话书库检索记录，可滚动');
    ui.matchHistory.forEach((entry,index)=>{
      const section=document.createElement('details');section.className='book-match-entry';
      section.dataset.lookupId=entry.id;
      const summary=document.createElement('summary');summary.textContent=(index===0?'最近一次 · ':'')+new Date(entry.created_at).toLocaleString()+' · '+entry.query;
      summary.onclick=()=>{section.dataset.userExpanded=String(!section.open);};
      section.dataset.userExpanded=String(expanded.has(entry.id));
      section.append(summary);let loaded=false;
      const fill=()=>{if(loaded)return;loaded=true;
        for(const item of entry.nodes){const button=document.createElement('button');button.type='button';
          button.textContent=(item.kind==='original'?'已回查：':item.kind==='omitted'?'本次未提供：':'目录候选：')+item.book_title+' · '+item.title+(item.pages.length?' · PDF '+item.pages.join('、'):'')+
            (item.available===false?' · 已删除':item.scope_changed?' · 历史范围已变化':'');
          button.disabled=item.available===false;button.onclick=()=>open(item.book_id,item.node_id).catch(fail);section.append(button);
        }
        const receipt=window.studyforgeSourceEvidence?.createReference(entry.receipt,'lookup:'+entry.id);
        if(receipt)section.append(receipt);
        else if(entry.nodes.some(item=>item.kind==='original')){const note=document.createElement('small');note.textContent='旧回查记录未保存实际阅读版本及字符范围，不以当前书库状态补填；需要时请重新回查。';section.append(note);}
        if(entry.truncated){const note=document.createElement('small');note.textContent=entry.receipt?.input_kind==='agent_library_read'?'当时仅读取这个窗口；未返回部分尚未提供，可请导师继续回查。':'当时按长度上限提供摘录，需要时可指定章节回查。';section.append(note);}
      };section.ontoggle=()=>{if(section.open)fill();};if(index===0||expanded.has(entry.id)){fill();section.open=true;}list.append(section);
    });host.append(list);list.scrollTop=scroll;
  }
  window.libraryShowMatches=(value,request)=>{
    if(request.conversation_id!==current().chat)return;
    let entry=value.history;
    if(!entry){const groups=new Map();for(const [kind,items] of [['original',value.evidence||[]],['candidate',value.candidates||[]],
      ['omitted',(value.receipt?.sources||[]).filter(source=>!source.included)]])
      for(const item of items){if(!groups.has(item.node_id))groups.set(item.node_id,{...item,kind,pages:[]});if(item.page)groups.get(item.node_id).pages.push(item.page);}
      if(!groups.size)return;
      entry={id:'live-'+Date.now(),created_at:new Date().toISOString(),query:request.text||'当前问题',nodes:[...groups.values()],truncated:value.truncated,receipt:value.receipt};
    }
    ui.matchRevision++;ui.matchHistory=[entry,...ui.matchHistory.filter(item=>item.id!==entry.id)].slice(0,30);renderMatchHistory();
  };
  if(!phone&&current().chat)reloadReferences().catch(fail);
  window.studyforgeBookLibrary=ui;
})();
