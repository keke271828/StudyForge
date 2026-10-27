// Keep LaTeX intact through Markdown parsing, then render it locally with KaTeX.
function protectLessonMath(text) {
  let prefix = 'STUDYFORGEMATHZ';
  while (text.includes(prefix)) prefix += 'Z';
  const formulas = [];
  let result = '', index = 0;
  while (index < text.length) {
    const remaining = text.slice(index);
    if (index === 0 || text[index - 1] === '\n') {
      const fence = remaining.match(/^ {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)/);
      if (fence) {
        const close = new RegExp('^ {0,3}' + fence[1][0] + '{' + fence[1].length + ',}[^\\n]*(?:\\n|$)', 'm');
        const after = remaining.slice(fence[0].length);
        const ending = after.match(close);
        const length = ending ? fence[0].length + ending.index + ending[0].length : remaining.length;
        result += remaining.slice(0, length); index += length; continue;
      }
    }
    if (text[index] === '`') {
      const ticks = remaining.match(/^`+/)[0];
      const end = text.indexOf(ticks, index + ticks.length);
      if (end >= 0) { result += text.slice(index, end + ticks.length); index = end + ticks.length; continue; }
    }
    const delimiter = remaining.startsWith('$$') ? ['$$', '$$', true]
      : remaining.startsWith('\\[') ? ['\\[', '\\]', true]
      : remaining.startsWith('\\(') ? ['\\(', '\\)', false]
      : text[index] === '$' && text[index - 1] !== '\\' ? ['$', '$', false] : null;
    if (delimiter) {
      const [left, right, display] = delimiter;
      let end = text.indexOf(right, index + left.length);
      while (end >= 0) {
        let slashes = 0;
        for (let cursor = end - 1; cursor >= 0 && text[cursor] === '\\'; cursor--) slashes++;
        if (right.startsWith('\\') || slashes % 2 === 0) break;
        end = text.indexOf(right, end + right.length);
      }
      const latex = end >= 0 ? text.slice(index + left.length, end) : '';
      if (end >= 0 && latex.trim() && (display || !latex.includes('\n'))) {
        const token = prefix + formulas.length + 'Q';
        formulas.push({ token, latex: latex.replace(/^\s*> ?/gm, ''), display,
          sourceStart:index,sourceEnd:end+right.length });
        result += token; index = end + right.length; continue;
      }
    }
    result += text[index++];
  }
  return { text: result, formulas, prefix };
}

function lessonRenderer() {
  const escaped = value => value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const renderer = new marked.Renderer();
  renderer.html = token => escaped(token.text);
  renderer.image = token => /^\/api\/agent\/assets\/[a-f0-9]{32}\/image$/.test(token.href || '')
    ? `<img src="${token.href}" alt="${escaped(token.text || '学习示意图')}" loading="lazy">` : escaped(token.text || '外部图片');
  return renderer;
}

function lessonFragment(html, protectedText) {
  const wrapper = document.createElement('div');
  wrapper.className = 'lesson-explanation';
  wrapper.innerHTML = DOMPurify.sanitize(html, { USE_PROFILES: { html: true },
    FORBID_TAGS: ['video', 'audio', 'iframe', 'form', 'input', 'button', 'style'],
    FORBID_ATTR: ['style'] });
  wrapper.querySelectorAll('blockquote').forEach(quote => quote.classList.add('lesson-quote'));
  wrapper.querySelectorAll('a').forEach(link => {
    if (/^\/api\/artifacts\/[a-f0-9]{32}\/download$/.test(link.getAttribute('href') || '')) { link.setAttribute('download', ''); return; }
    if (!/^https?:\/\//i.test(link.getAttribute('href') || '')) link.removeAttribute('href');
    link.target = '_blank'; link.rel = 'noopener noreferrer';
  });
  wrapper.querySelectorAll('img').forEach(img => { if (!/^\/api\/agent\/assets\/[a-f0-9]{32}\/image$/.test(img.getAttribute('src') || '')) img.remove(); });
  const walker = document.createTreeWalker(wrapper, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  const pattern = new RegExp(protectedText.prefix + '(\\d+)Q', 'g');
  for (const node of nodes) {
    if (node.parentElement.closest('code, pre')) continue;
    const matches = [...node.textContent.matchAll(pattern)];
    if (!matches.length) continue;
    const fragment = document.createDocumentFragment();
    let offset = 0;
    for (const match of matches) {
      fragment.append(document.createTextNode(node.textContent.slice(offset, match.index)));
      const formula = protectedText.formulas[Number(match[1])];
      const element = document.createElement('span');
      element.className = formula.display ? 'lesson-math display-math' : 'lesson-math';
      katex.render(formula.latex, element, { displayMode: formula.display, throwOnError: false,
        trust: false, strict: 'ignore', maxExpand: 1000, maxSize: 30 });
      if (element.querySelector('.katex-error')) element.title = '公式暂无法排版，保留原始表达式供核对';
      fragment.append(element); offset = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(node.textContent.slice(offset)));
    node.replaceWith(fragment);
  }
  return wrapper;
}

const lessonStreamStates = new WeakMap();
function renderLessonText(container, text) {
  lessonStreamStates.delete(container);
  container.dataset.rawText = text;
  if (!window.marked || !window.DOMPurify || !window.katex) { container.textContent = text; return; }
  const protectedText = protectLessonMath(text);
  const html = marked.parse(protectedText.text, { gfm: true, breaks: false, renderer: lessonRenderer() });
  container.replaceChildren(lessonFragment(html, protectedText));
}

// Retain unchanged top-level Markdown blocks and their already rendered math.
// Relexing the whole answer preserves lists, tables, open fences, and reference
// links. A changed reference definition invalidates all prior block rendering.
function renderLessonStream(container, text) {
  if (!window.marked || !window.DOMPurify || !window.katex) return renderLessonText(container, text);
  const protectedText = protectLessonMath(text);
  const tokens = marked.lexer(protectedText.text, { gfm: true, breaks: false });
  const context = protectedText.prefix + JSON.stringify(tokens.links);
  const pattern = new RegExp(protectedText.prefix + '(\\d+)Q', 'g');
  const signatures = tokens.map(token => [...(token.raw || '').matchAll(pattern)].map(match => {
    const item = protectedText.formulas[Number(match[1])];return JSON.stringify([item.latex, item.display]);
  }).join('|'));
  let state = lessonStreamStates.get(container);
  if (!state || state.wrapper.parentNode !== container) {
    const wrapper = document.createElement('div');wrapper.className = 'lesson-explanation';
    container.replaceChildren(wrapper);state = {wrapper, blocks: [], context};
    lessonStreamStates.set(container, state);
  }
  let retained = 0;
  if (state.context === context) {
    while (retained < tokens.length && retained < state.blocks.length &&
      state.blocks[retained].raw === tokens[retained].raw && state.blocks[retained].type === tokens[retained].type &&
      state.blocks[retained].math === signatures[retained]) retained++;
  }
  for (const block of state.blocks.slice(retained)) for (const node of block.nodes) node.remove();
  state.blocks.length = retained;
  for (let index = retained; index < tokens.length; index++) {
    const token = tokens[index];
    const group = [token];group.links = tokens.links;
    const html = marked.parser(group, {gfm: true, breaks: false, renderer: lessonRenderer()});
    const fragment = lessonFragment(html, protectedText);
    const nodes = [...fragment.childNodes];state.wrapper.append(...nodes);
    state.blocks.push({type: token.type, raw: token.raw, math: signatures[index], nodes});
  }
  state.context = context;container.dataset.rawText = text;
  return {retained, rendered: tokens.length - retained, total: tokens.length};
}
