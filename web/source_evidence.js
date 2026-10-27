/* Saved source provenance, shared by desktop and phone. No live-book lookup. */
(() => {
  const expanded = new Set();
  const sourcesOf = meta => Array.isArray(meta?.source_reading) ? meta.source_reading.filter(source => source && typeof source === 'object') : [];
  const count = value => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0;
  const isScoped = source => String(source.method || '').startsWith('explicit_selected');
  const referenceSources = receipt => Array.isArray(receipt?.sources) ? receipt.sources : [];
  const hasReference = receipt => receipt?.schema === 'library-reference-receipt-v1' &&
    (referenceSources(receipt).length || receipt.unread_candidates?.length);
  const oldReferences = meta => (meta.library_references?.references || []).filter(ref => ref.purpose === 'reference');

  function summary(meta, modeLabel = '') {
    const sources = sourcesOf(meta), scoped = sources.filter(isScoped).length;
    const input = meta.chat_export?'直接保存导师回答 · 未重新读取资料':`读取 ${sources.length} 份资料${scoped ? `（含 ${scoped} 份选定范围）` : ''}`;
    const auxiliary = referenceSources(meta.library_evidence).filter(source => source.purpose === 'reference' && source.included).length;
    return [meta.model || '模型未记录', meta.reasoning_effort, modeLabel, input,
      auxiliary ? `书库背景摘录 ${auxiliary} 个节点` : '',
      `${meta.chat_export?count(meta.chat_export.content_characters):sources.reduce((sum, source) => sum + count(source.characters), 0)} 字符`].filter(Boolean).join(' · ');
  }

  function sourceScope(source) {
    const scope = source.scope;
    if (scope && Number.isInteger(scope.start_page) && Number.isInteger(scope.end_page)) {
      const pages = scope.start_page === scope.end_page ? `${scope.start_page}` : `${scope.start_page}–${scope.end_page}`;
      const edge = Number.isFinite(scope.start_y) && Number.isFinite(scope.end_y)
        ? ` · 首页从 ${Math.round(scope.start_y * 100)}%，末页至 ${Math.round(scope.end_y * 100)}%` : '';
      return `PDF 第 ${pages} 页${edge}`;
    }
    if (source.method === 'explicit_selected_library_node') return '选定书库节点（此前成果未记录具体页界）';
    if (isScoped(source)) return '本次选定页或选段；不代表通读整份文件';
    return '本次提供的文件提取记录；提取缺口见下方提示';
  }

  function line(parent, text) {
    const p = document.createElement('p'); p.textContent = text; parent.append(p); return p;
  }

  function spanLabel(name, span) {
    if (!span || !Number.isInteger(span.start_char) || !Number.isInteger(span.end_char)) return `${name}：范围未记录`;
    if (!span.total_chars) return `${name}：本次记录无可读文字，不代表原页为空白`;
    if (span.end_char <= span.start_char) return `${name}：本次未提供文字（记录共 ${span.total_chars} 字符）`;
    return `${name}：第 ${span.start_char + 1}–${span.end_char} 字符 / 共 ${span.total_chars} 字符${span.truncated ? ' · 已节选，没有提供的部分尚未检查' : ' · 这段文字已完整提供'}`;
  }

  function appendReadingNotes(body, meta) {
    const inputs = meta.lesson_quality?.reading_note_inputs;
    if (!Array.isArray(inputs)) {
      if (meta.reading_id) line(body, '此前成果未保存通读笔记与讲解分段的对应记录，无法补认当时提供了哪部分笔记。');
      return;
    }
    if (!inputs.some(input => input?.total_notes > 0)) return;
    const title = document.createElement('h4'); title.textContent = '这次用了哪些阅读笔记？'; body.append(title);
    line(body, '阅读笔记帮助 AI 组织讲解，不能代替原文。这里只列出确实用于这一部分的笔记；原文会另行提供。');
    const list = document.createElement('ol'); list.className = 'reading-note-evidence-list';
    inputs.forEach((input, index) => {
      const item = document.createElement('li');
      const included = Array.isArray(input?.included) ? input.included : [];
      let label;
      if (input?.reason === 'exact_original_input') {
        label = included.length ? '使用输入相同的通读笔记' : '通读输入对应，但本次预算内没有完整笔记段落';
      } else if (input?.reason === 'legacy_unassigned') {
        label = included.length ? '使用旧版整体笔记作导航，未确认对应本分段' : '旧版笔记未记录分段对应，本次未提供正文';
      } else if (input?.reason === 'no_matching_original_input') {
        label = '没有匹配的通读输入，未猜配笔记，直接依据完整原文';
      } else label = '未使用通读笔记';
      item.textContent = `第 ${index + 1} 部分：${label}${included.some(note => note?.excerpted) ? ' · 笔记已节选' : ''}`;
      list.append(item);
    });
    body.append(list);
  }

  function appendReference(body, receipt) {
    const direct = receipt.input_kind === 'agent_library_read';
    const title = document.createElement('h4'); title.textContent = direct ? '导师这次查到的原页' : '这次参考的书库内容'; body.append(title);
    line(body, `${receipt.shared_chapter_count ? '每部分' : '本次'}提供 ${count(receipt.context_characters)} 字符${Number.isInteger(receipt.context_limit) ? ' / 上限 ' + receipt.context_limit : ''}。` + (direct ? '只记录这次实际返回的片段，不代表通读本节或确认内容正确。' : '这是辅助摘录与导航；重点章节的完整原页输入另列在“用于生成正文的资料”。'));
    if (direct) {
      const window = receipt.read_window || {};
      line(body, `本次读取的位置：${Number.isInteger(window.page) ? '指定 PDF 第 ' + window.page + ' 页' : '节点已授权范围'} · 从合并文字的第几个字符开始 ${count(window.offset)}${Number.isInteger(window.total_characters) ? ' / 共 ' + window.total_characters + ' 字符' : ''}（含来源标题；原页文字位置见下方）。`);
      if (Number.isInteger(window.next_offset)) line(body, '仍有后续片段，继续位置：' + window.next_offset + '；未返回部分尚未提供。');
      if (receipt.image_rechecked) line(body, '本次另有 AI 图像复核输出，不属于这里记录的原文片段，也不代表复核一定正确。');
    }
    if (receipt.shared_chapter_count) line(body, `${receipt.shared_chapter_count} 部分讲解共用这份固定参考输入，已按长文预算整理；不与阅读笔记一起隐式截断。`);
    if (receipt.truncated) line(body, '参考输入已缩减或节选；下列页码和字符范围只表示实际提供的部分，不表示通读这些章节。');
    const list = document.createElement('ol'); list.className = 'reference-evidence-list';
    for (const source of referenceSources(receipt)) {
      const item = document.createElement('li'); item.dataset.referenceNode = source.node_id;
      const title = document.createElement('strong'); title.textContent = `${source.book_title} · ${source.title}`; item.append(title);
      line(item, direct ? '按当前对话授权回查的片段' : source.purpose === 'primary' ? '重点章节的辅助摘录／导航' : '参考背景，辅助回答当前问题');
      line(item, sourceScope(source));
      if (!source.included) {
        line(item, direct ? '本次未返回可确认范围的原页文字：可能只取到来源标题或已到末尾；不能算作读过正文。' : '本次未提供这一章节的正文：长度预算或原页记录不足；不能把目录命中当作已经阅读。');
      } else {
        const reading = source.library_reading || {};
        line(item, `阅读：${reading.model || '模型未记录'}${reading.effort ? ' · ' + reading.effort : ''}${reading.id ? ' · 版本 ' + String(reading.id).slice(0, 8) : ''}`);
        if (direct) {
          line(item, '阅读整理：' + (reading.depth === 'deep' ? '重点精读' : reading.depth === 'index' ? '梳理重点' : '深度未记录'));
          if (reading.focus) line(item, '当时精读问题：' + reading.focus);
          if (reading.updated_at) line(item, '阅读记录时间：' + reading.updated_at);
        }
        if (reading.vision_model) line(item, '图像核对模型：' + reading.vision_model);
        for (const page of source.pages || []) {
          line(item, `实际提供：${page.locator || 'PDF 第 ' + page.page + ' 页'}`);
          line(item, spanLabel('原页提取／OCR', page.original_excerpt));
          if (page.visual_excerpt?.total_chars) line(item, spanLabel('AI 图像核对记录（不是原文引语）', page.visual_excerpt));
        }
        if (source.navigation_excluded) line(item, '此版本的 AI 导航笔记已标疑，本次未提供它的笔记正文。');
        else if (source.navigation_excerpt?.total_chars) line(item, spanLabel('AI 导航笔记（不是教材正文）', source.navigation_excerpt));
        if (source.warnings_text) line(item, source.warnings_text);
        if (source.annotation?.comment_excerpt) {
          line(item, '启动时的用户校订／疑问：' + source.annotation.comment_excerpt);
          if (source.annotation.comment_span?.truncated) line(item, '此条用户校订也已节选；不是原文或学生能力证据。');
        }
      }
      list.append(item);
    }
    for (const candidate of receipt.unread_candidates || []) {
      const item = document.createElement('li'); item.dataset.referenceCandidate = candidate.node_id;
      const title = document.createElement('strong'); title.textContent = candidate.title || '未读目录候选'; item.append(title);
      line(item, '只提供目录位置，未读取正文；等待你决定是否安排阅读。'); list.append(item);
    }
    body.append(list);
    if (receipt.context_sha256) {
      const id = line(body, '本次提供给 AI 的内容：' + receipt.context_sha256.slice(0, 12)); id.title = receipt.context_sha256;
    }
  }

  function panel(key, headingText, buildBody) {
    const details = document.createElement('details'); details.className = 'source-evidence small-note';
    const heading = document.createElement('summary');
    heading.textContent = headingText;
    details.append(heading);
    let built = false;
    function build() {
      if (built) return; built = true;
      const body = document.createElement('div'); body.className = 'source-evidence-body';
      buildBody(body); details.append(body);
    }
    if (key && expanded.has(key)) { details.open = true; build(); }
    details.addEventListener('toggle', () => {
      if (details.open) {
        build();
        if (key) { expanded.delete(key); expanded.add(key); if (expanded.size > 200) expanded.delete(expanded.values().next().value); }
      } else if (key) expanded.delete(key);
    });
    return details;
  }

  function createReference(receipt, key = '') {
    if (!hasReference(receipt)) return null;
    return panel(key, receipt.input_kind === 'agent_library_read' ? '查看导师查过的原页和选段' : '查看本次参考的书库页码和文字', body => appendReference(body, receipt));
  }

  function create(meta, key = '') {
    const sources = sourcesOf(meta), reference = hasReference(meta.library_evidence), legacy = !reference && oldReferences(meta).length;
    if (!sources.length && !reference && !legacy && !meta.chat_export) return null;
    const bookVersion = sources.some(source => source.library_reading), bookSource = sources.some(source => source.method === 'explicit_selected_library_node');
    return panel('artifact:' + key, meta.chat_export?'直接保存的导师回答':`本次使用的资料 · 正文 ${sources.length} 份${reference ? ' · 含这次参考的书库内容' : bookVersion ? ' · 含书库阅读版本' : bookSource ? ' · 书库旧记录' : ''}`, body => {
      const intro = document.createElement('p');
      intro.textContent = meta.chat_export?'这份文件原样保存原对话中已公开的导师回答，未重新生成、读取资料或核查。':'这里可以检查这份讲解用了哪些资料、读了哪些页。文字识别和 AI 阅读都可能出错，重要内容请对照原页。';
      body.append(intro);
      if(meta.chat_export){
        line(body,'原回答模型及当时的完整资料范围未单独记录，不使用当前对话设置补填。');
        if(meta.chat_export.message_created_at)line(body,'回答时间：'+meta.chat_export.message_created_at);
        if(meta.chat_export.content_sha256)line(body,'回答内容校验编号：'+meta.chat_export.content_sha256.slice(0,12));
      }
      const quality = meta.lesson_quality;
      appendReadingNotes(body, meta);
      if (Number.isInteger(quality?.summary_caution_sections_total) && quality.summary_caution_sections_total > 0) {
        const title = document.createElement('h4'); title.textContent = '全文总结的核查记录'; body.append(title);
        line(body, `共 ${quality.summary_caution_sections_total} 段核查记录，全文总结输入保留 ${count(quality.summary_caution_sections_included)} 段${quality.summary_caution_sections_omitted ? `，另有 ${quality.summary_caution_sections_omitted} 段未列入辅助输入` : ''}。正文中的记录仍完整保留。`);
        line(body, '这是核查记录的段落数，不是已确认错误数。待核实的条件仍需对照原文；已修订但未再次复核，也不等于确认仍然错误。');
      }
      if (sources.length) { const title = document.createElement('h4'); title.textContent = '用于生成正文的资料'; body.append(title); }
      const list = document.createElement('ol'); list.className = 'primary-evidence-list';
      for (const source of sources) {
        const item = document.createElement('li'), title = document.createElement('strong');
        title.textContent = source.name || '未命名资料'; item.append(title);
        const line = text => { const p = document.createElement('p'); p.textContent = text; item.append(p); };
        line(sourceScope(source));
        const origin = source.content_origin;
        if (origin?.role === 'ai_generated_artifact') line('资料身份：本软件 AI 成果；不代表已回查其引用的原文。');
        else if (origin?.role === 'derived_source_record') line('资料身份：整理的来源记录；可能含自动识别误差，不代表重新核对了原视频或原资料。');
        else if (origin?.role === 'attached_artifact') line('资料身份：外部附加或类型未知的成果；作者与真实性未认证。');
        else if (origin?.role === 'provided_material') line('资料身份：导入资料；未认证作者或内容正确性。');
        else if (origin?.role === 'excerpt_material' && origin.lineage === 'unresolved') line('资料身份：已保留选段；原资料关系不完整，无法据此确认来源。');
        line(`${count(source.segments)} 条提取记录 · ${count(source.characters)} 字符`);
        const reading = source.library_reading;
        if (reading) {
          const depth = reading.depth === 'deep' ? '重点精读' : reading.depth === 'index' ? '梳理重点' : '深度未记录';
          line(`书库阅读：${reading.model || '模型未记录'}${reading.effort ? ' · ' + reading.effort : ''} · ${depth}`);
          if (reading.vision_model) line('扫描页核对：' + reading.vision_model);
          if (reading.focus) line('精读重点：' + reading.focus);
          if (reading.id) { const p = document.createElement('p'); p.textContent = '阅读版本：' + String(reading.id).slice(0, 8); p.title = String(reading.id); item.append(p); }
          const references = meta.library_references?.references;
          const mark = Array.isArray(references) ? references.find(ref => ref.node_id === source.source_id)?.note_annotation : null;
          if (mark?.reading_id === reading.id) {
            if (mark.suspect) line('此版本的 AI 导航笔记已标疑；生成仍须依据原页核对。');
            if (mark.comment) line('启动时的用户校订／疑问：' + mark.comment);
          }
        } else if (source.method === 'explicit_selected_library_node') line('此前成果未保存阅读模型与版本，不用当前书库状态补填。');
        for (const warning of Array.isArray(source.limitations) ? source.limitations : []) line('待核对：' + warning);
        list.append(item);
      }
      body.append(list);
      if (reference) appendReference(body, meta.library_evidence);
      else if (legacy) line(body, '此前成果未保存书库参考片段的实际页码、范围与阅读版本，无法追溯当时提供的辅助输入；不使用当前书库状态补填。');
    });
  }
  window.studyforgeSourceEvidence = {summary, create, createReference};
})();
