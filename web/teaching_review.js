/* Public explanation audits, never exercise solutions or private reasoning. */
(() => {
  'use strict';
  const views = new Map(), PAGE = 5;
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  const text = value => typeof value === 'string' ? value : '';
  const array = value => Array.isArray(value) ? value : [];
  const number = value => Number.isInteger(value) && value >= 0;
  const clamp = (value, max) => Math.max(0, Math.min(number(value) ? value : 0, Math.max(0, max)));
  function node(tag, value, className) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  }
  function field(host, label, value, className = '') {
    if (!text(value)) return;
    const block = node('div', undefined, 'teaching-review-field ' + className);
    block.append(node('strong', label));
    const body = node('div', undefined, 'teaching-review-text');
    // Long records stay available, but do not all enter the DOM on refresh.
    if (value.length > 1400) {
      body.append(node('p', value.slice(0, 1400) + '…'));
      const more = node('details'), heading = node('summary', `展开完整记录（${value.length} 字符）`);
      more.append(heading);
      more.addEventListener('toggle', () => {
        if (more.open && !more.querySelector('pre')) more.append(node('pre', value));
      });
      body.append(more);
    } else body.textContent = value;
    block.append(body); host.append(block);
  }
  function describe(report) {
    const issues = array(report?.issues);
    if (issues.length) return report.passed === true
      ? '本轮仍列出疑点；即使 AI 标了通过，也不能认为这些疑点已经解决'
      : '本轮提出了疑点；不代表最终稿仍然错误';
    if (report?.passed === true) return '本轮未列出疑点，仍可能漏检';
    if (report?.passed === false) return '本轮未确认通过，未保存具体疑点';
    return '未记录独立核查通过；具体情况见本轮说明';
  }
  function issueStatus(report, index) {
    return array(report?.locally_corrected_issues).some(value => number(value) && value === index)
      ? '已记录局部修订 · 未再次独立复核'
      : '当时提出的疑点 · 请结合交付稿核对';
  }
  function pager(label, index, total, onChange) {
    const bar = node('div', undefined, 'teaching-review-pager');
    const previous = node('button', '上一' + label), next = node('button', '下一' + label);
    previous.type = next.type = 'button'; previous.disabled = index === 0; next.disabled = index + 1 >= total;
    previous.onclick = () => onChange(index - 1); next.onclick = () => onChange(index + 1);
    const jump = node('label', label + ' '), input = node('input');
    input.type = 'number'; input.min = '1'; input.max = String(total); input.value = String(index + 1);
    input.setAttribute('aria-label', '跳转到第几' + label);
    input.onchange = () => {
      const value = Number(input.value);
      if (!Number.isInteger(value) || value < 1 || value > total) { input.value = String(index + 1); return; }
      onChange(value - 1);
    };
    jump.append(input, document.createTextNode(' / ' + total));
    bar.append(previous, jump, next); return bar;
  }
  function create(meta, key, kind) {
    if (kind !== 'explanation' || !object(meta)) return null;
    const reports = array(meta.reviews);
    if (!reports.length && !meta.generation_job_id) return null;
    const saved = views.get(key) || {open:false, report:0, page:0, scroll:0, edits:new Set()};
    const details = node('details', undefined, 'teaching-review');
    details.dataset.teachingReview = key;
    const summary = node('summary', reports.length
      ? `讲解检查记录 · ${reports.length} 项记录 · 查看疑点与修订`
      : '讲解检查记录 · 此前成果未保存明细');
    details.append(summary);
    let body;
    function remember() {
      if (!key) return;
      views.delete(key); views.set(key, saved);
      if (views.size > 120) views.delete(views.keys().next().value);
    }
    function paint() {
      body.replaceChildren();
      body.append(node('p', '这里是生成讲解时的检查记录，不是对你能力的评价。旧问题可能已在后续修改中解决；请对照最后交付的讲解来看。AI 检查也可能漏错。', 'teaching-review-intro'));
      if (!reports.length) {
        body.append(node('p', '没有保存逐项核查明细，不能用当前设置补认当时已经审查。原讲解与已有的“待核实事项”仍可对照查看。'));
        return;
      }
      saved.report = clamp(saved.report, reports.length - 1);
      if (reports.length > 1) body.append(pager('项记录', saved.report, reports.length, value => {
        saved.report = value; saved.page = 0; saved.scroll = 0; paint(); body.scrollTop = 0; remember();
      }));
      const report = object(reports[saved.report]) ? reports[saved.report] : {};
      const heading = [number(report.section) && report.section > 0 ? '讲解第 ' + report.section + ' 部分' : '',
        text(report.stage) || '阶段未记录', number(report.attempt) && report.attempt > 0 ? '第 ' + report.attempt + ' 轮' : ''].filter(Boolean).join(' · ');
      body.append(node('h4', heading), node('p', describe(report), 'teaching-review-status'));
      if (!object(reports[saved.report])) body.append(node('p', '这项旧记录结构不完整，不能据此判断内容已核对。'));
      field(body, '本轮说明', text(report.note));
      if (report.review_context === 'same_dialogue_self_check') body.append(node('p', '核查方式：同一对话的导师自检；不是另一个独立模型的验证。'));
      else if (report.review_context === 'separate_review') body.append(node('p', '核查方式：单独发起核查；仍可能重复原讲解的错误。'));
      const issues = array(report.issues), pages = Math.ceil(issues.length / PAGE);
      saved.page = clamp(saved.page, pages - 1);
      if (pages > 1) body.append(pager('页疑点', saved.page, pages, value => {
        saved.page = value; saved.scroll = 0; paint(); body.scrollTop = 0; remember();
      }));
      const list = node('div', undefined, 'teaching-review-issues');
      for (let index = saved.page * PAGE; index < Math.min(issues.length, (saved.page + 1) * PAGE); index++) {
        const issue = object(issues[index]) ? issues[index] : {};
        const item = node('article', undefined, 'teaching-review-issue'); item.dataset.reviewIssue = String(index);
        item.append(node('h5', `疑点 ${index + 1} / ${issues.length}`), node('p', issueStatus(report, index), 'teaching-review-status'));
        field(item, '核查给出的位置（未重新定位）', text(issue.location));
        field(item, '需要核对什么', text(issue.problem) || text(issues[index]) || '旧记录没有保存具体问题');
        field(item, 'AI 为什么认为这里需要检查（仍需核对原资料）', text(issue.evidence));
        const patches = array(report.corrections).filter(patch => object(patch) && number(patch.issue_index) && patch.issue_index === index);
        const receipts = array(report.local_correction_anchors).filter(receipt => object(receipt) && receipt.issue_index === index);
        if (patches.length) {
          const edits = node('details', undefined, 'teaching-review-edits');
          edits.append(node('summary', `替换提议与定位记录（${patches.length} 处）`));
          // Fast review produces at most eight edits. Older/malformed records
          // are batched too; never silently present a prefix as the full set.
          let shown = 0;
          const more = node('button', '继续显示替换提议'); more.type = 'button';
          const add = () => {
            const end = Math.min(shown + 8, patches.length);
            for (; shown < end; shown++) {
              const patch = patches[shown], block = node('section', undefined, 'teaching-review-edit');
              block.append(node('h6', '替换提议 ' + (shown + 1)));
              field(block, 'AI 想修改的原文（保留公式和排版代码）', text(patch.before), 'teaching-review-before');
              if (text(patch.passage_id)) {
                field(block, '原段编号', patch.passage_id);
                block.append(node('p', '此提议按段落编号定位，记录未保存原段全文；不从后来的正文猜补。'));
              }
              field(block, 'AI 建议改成什么（不一定已写入最终稿）', text(patch.after), 'teaching-review-after');
              edits.insertBefore(block, more);
            }
            more.hidden = shown >= patches.length;
          };
          more.onclick = add; edits.append(more);
          const editKey = saved.report + ':' + index;
          edits.addEventListener('toggle', () => {
            if (edits.open) {
              if (!shown) add();
              saved.edits.add(editKey);
              if (saved.edits.size > 80) saved.edits.delete(saved.edits.values().next().value);
            } else saved.edits.delete(editKey);
            remember();
          });
          if (saved.edits.has(editKey)) { edits.open = true; add(); }
          item.append(edits);
        }
        if (receipts.length) item.append(node('p', `本机保存了 ${receipts.length} 处实际替换记录；定位成功只表示程序完成了替换，不证明新文字正确。`, 'teaching-review-receipt'));
        else if (array(report.locally_corrected_issues).includes(index)) item.append(node('p', '旧记录标注了局部修订，但缺少详细定位记录；不能补认具体替换范围。'));
        list.append(item);
      }
      body.append(list);
      body.append(node('p', '需要核对时，可在这份成果的“理解反馈”中选择“讲解可能有误或依据不清”，并指出具体章节／原句。问卷已提交或跳过时，点“核对讲解新疑问”另开一次核对，旧反馈保留。查看本面板不会请求模型、出题或写入学习画像。', 'teaching-review-help'));
    }
    function build() {
      if (body) return;
      body = node('div', undefined, 'teaching-review-body');
      body.tabIndex = 0; body.setAttribute('role', 'region'); body.setAttribute('aria-label', '讲解检查记录，可滚动');
      body.addEventListener('scroll', () => {
        if (details.isConnected && details.open) { saved.scroll = body.scrollTop; remember(); }
      }, {passive:true});
      const restore = saved.scroll;
      details.append(body); paint();
      // Reconciled cards are constructed before insertion. A detached element
      // cannot restore scrollTop; wait for layout and keep user scrolling first.
      requestAnimationFrame(() => {
        if (details.isConnected && details.open && saved.scroll === restore) body.scrollTop = restore;
      });
    }
    details.addEventListener('toggle', () => { saved.open = details.open; if (details.open) build(); remember(); });
    if (saved.open) { details.open = true; build(); }
    return details;
  }
  window.studyforgeTeachingReview = {create, describe, issueStatus};
})();
