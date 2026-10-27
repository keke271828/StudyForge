/* Optional exact passage selection, shared by desktop and phone.
   No AI request or source parsing; every window comes from its saved lesson. */
(() => {
  function create(host, options) {
    const root=document.createElement('div');root.className='lesson-passage';
    root.innerHTML='<button type="button" data-passage-open>查看本节原句 · 可选段</button><div data-passage-reader hidden><p data-passage-range class="small-note helper"></p><div class="lesson-passage-view" role="group" aria-label="历史讲解显示方式"><button type="button" data-passage-rendered aria-pressed="true">正常阅读（显示公式）</button><button type="button" data-passage-source aria-pressed="false">查看排版原文（Markdown）</button></div><div class="lesson-passage-reading markdown" data-passage-preview role="document" tabindex="0" aria-label="历史AI讲解，可选取原句与完整公式"></div><label data-passage-source-label hidden>历史 AI 讲解原文<textarea data-passage-text rows="8" readonly spellcheck="false" aria-label="历史AI讲解原句，可选择具体片段"></textarea></label><div class="lesson-passage-actions"><button type="button" data-passage-prev>上一段</button><button type="button" data-passage-next>下一段</button><button type="button" data-passage-use>使用选中原句</button></div><label class="lesson-passage-jump">从本节跳到第几个字查看<input type="text" inputmode="numeric" value="1" data-passage-offset><button type="button" data-passage-jump>前往</button></label></div><div data-passage-chosen hidden><p>本次只针对这段历史 AI 原句补讲</p><blockquote data-passage-quote></blockquote><button type="button" data-passage-clear>取消选段，改按章节补讲</button></div><p data-passage-status role="status" class="small-note helper"></p>';
    host.replaceChildren(root);
    const find=name=>root.querySelector('[data-passage-'+name+']');
    let section='',selection=null,windowData=null,revision=0,view='rendered',loading=false;
    const active=()=>host.isConnected&&host.firstChild===root&&section===options.getSection()&&(!options.isActive||options.isActive());
    function display(value){
      view=value;find('preview').hidden=value!=='rendered';find('source-label').hidden=value!=='source';
      find('rendered').setAttribute('aria-pressed',String(value==='rendered'));find('source').setAttribute('aria-pressed',String(value==='source'));
      const chosen=window.getSelection();if(chosen?.anchorNode&&root.contains(chosen.anchorNode))chosen.removeAllRanges();
    }
    function controls(){
      find('prev').disabled=loading||!windowData||windowData.previous_offset===null;
      find('next').disabled=loading||!windowData||windowData.next_offset===null;
      find('use').disabled=loading||!windowData;find('jump').disabled=loading||!windowData;
    }
    function paint(){
      root.hidden=!section;find('chosen').hidden=!selection;
      if(selection){if(typeof renderLessonText==='function')renderLessonText(find('quote'),selection.text);else find('quote').textContent=selection.text;}
      else find('quote').replaceChildren();
    }
    function setSection(value, restored){
      if(value!==section){section=value;selection=null;windowData=null;loading=false;revision++;find('reader').hidden=true;find('status').textContent='';find('text').value='';find('preview').replaceChildren();display('rendered');controls();}
      if(restored!==undefined){selection=restored&&Number.isInteger(restored.start)&&Number.isInteger(restored.end)&&
        typeof restored.text==='string'&&restored.text.length<=6000?{start:restored.start,end:restored.end,text:restored.text}:null;}
      paint();
    }
    async function load(offset=0){
      if(!section||!active())return;
      const token=++revision,id=options.getId(),captured=section;
      loading=true;controls();find('status').textContent='正在读取已保存的讲解片段，不调用 AI…';
      try{
        const path=position=>'/api/lesson-feedback/'+encodeURIComponent(id)+'/passage?section_id='+encodeURIComponent(captured)+'&offset='+position;
        let data=await options.api(path(offset));
        if(token!==revision||!active()||id!==options.getId())return;
        // Keep short proofs continuous, with at most one extra bounded read.
        // Both windows must belong to the same saved document and section.
        if(offset===0&&data.total<=7000&&data.next_offset!==null){
          const more=await options.api(path(data.next_offset));
          if(token!==revision||!active()||id!==options.getId())return;
          if(!data.document_sha256||more.document_sha256!==data.document_sha256||more.section_id!==data.section_id||more.total!==data.total||more.offset!==data.end)
            throw Error('历史讲解已经变化，请重新打开本节；不会拼接不同版本。');
          data={...data,text:data.text+more.text,end:more.end,next_offset:more.next_offset};
        }
        windowData=data;find('text').value=data.text;find('reader').hidden=false;
        if(window.studyforgeSourceSelection){studyforgeSourceSelection.render(find('preview'),data.text);display(view);}
        else display('source');
        find('preview').scrollTop=0;find('text').scrollTop=0;
        find('range').textContent=`本节第 ${data.offset+1}–${data.end} 字符，共 ${data.total} 字符。这里只查看历史 AI 讲解，不是原文件。`;
        find('offset').value=data.offset+1;find('offset').max=data.total;
        find('status').textContent=(window.studyforgeSourceSelection?'':'排版组件未就绪，已显示原文。')+'拖选或长按选中，再点“使用选中原句”（最多3000字符）；公式和代码会完整引用。仅查看不调用AI，填写疑问并提交后才补讲。'+(data.total>7000?'长节按片段显示，段首段尾可能仍有接续内容；需要核对源码时切“原文”。':'');
      }catch(error){if(token===revision&&active())find('status').textContent=error.message||'片段读取失败，请重试。';}
      finally{if(token===revision&&active()){loading=false;controls();}}
    }
    find('open').onclick=()=>{if(windowData)find('reader').hidden=!find('reader').hidden;else load();};
    find('prev').onclick=()=>{if(windowData&&windowData.previous_offset!==null)load(windowData.previous_offset);};
    find('next').onclick=()=>{if(windowData&&windowData.next_offset!==null)load(windowData.next_offset);};
    find('jump').onclick=()=>{
      const number=Number(find('offset').value);
      if(!Number.isSafeInteger(number)||number<1||number>(windowData?.total||0)){find('status').textContent='请填写本节范围内的字符位置。';return;}
      load(number-1);
    };
    find('offset').onkeydown=event=>{
      if(event.key==='Enter'&&!event.isComposing){event.preventDefault();event.stopPropagation();find('jump').click();}
    };
    find('use').onclick=()=>{
      if(!windowData||loading||!active())return;
      const area=find('text');
      // Native textareas normalize CRLF; source mode maps back before counting
      // Unicode code points. Rendered mode uses exact source-bound DOM ranges.
      function rawBoundary(boundary){let raw=0,shown=0;while(shown<boundary&&raw<windowData.text.length){raw+=windowData.text[raw]==='\r'&&windowData.text[raw+1]==='\n'?2:1;shown++;}return raw;}
      let start,end,text;
      if(view==='rendered'){
        try{({start,end,text}=studyforgeSourceSelection.selection(find('preview')));}
        catch(error){find('status').textContent=error.message;return;}
      }else{start=rawBoundary(area.selectionStart);end=rawBoundary(area.selectionEnd);text=windowData.text.slice(start,end);}
      if(!text.trim()||Array.from(text).length>3000){find('status').textContent='请先选择 1–3000 个字符；可拖选或在手机上长按选择。';return;}
      selection={start:windowData.offset+Array.from(windowData.text.slice(0,start)).length,
        end:windowData.offset+Array.from(windowData.text.slice(0,end)).length,text};
      paint();find('status').textContent='已选好原句。再勾选困难或填写你的具体疑问，提交后才请导师补讲。';options.onChange();
    };
    find('rendered').onclick=()=>{if(window.studyforgeSourceSelection&&windowData){
      if(find('preview').dataset.rawText!==windowData.text)studyforgeSourceSelection.render(find('preview'),windowData.text);
      display('rendered');
    }};
    find('source').onclick=()=>display('source');
    find('clear').onclick=()=>{selection=null;paint();find('status').textContent='已取消选段，保留章节和你填写的疑问。';options.onChange();};
    setSection('');
    return {setSection,value:()=>selection?{...selection}:null};
  }
  window.studyforgeLessonPassage={create};
})();
