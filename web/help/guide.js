/* Guide search and example copying require neither a model nor a network service. */
(() => {
  const byId = id => document.getElementById(id);
  const sections = [...document.querySelectorAll('.guide-section')];
  const links = [...byId('guideContents').querySelectorAll('a')];
  const searchable = new Map(sections.map(section => [section.id, (section.textContent + ' ' + (section.dataset.search || '')).toLocaleLowerCase()]));
  const detailsBeforeSearch = new Map();
  let contextActions = [], embedded = window.parent !== window, copyTimer;
  const notify = action => { if (embedded) window.parent.postMessage({type:'studyforge-guide-action', action}, location.origin); };
  function search() {
    const words = byId('guideSearch').value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    let count = 0;
    for (const section of sections) {
      const match = words.every(word => searchable.get(section.id).includes(word));
      section.hidden = !match; if (match) count++;
      const link = links.find(link => link.hash === '#' + section.id); if (link) link.hidden = !match;
      for (const detail of section.querySelectorAll('details')) {
        if (words.length) {
          if (!detailsBeforeSearch.has(detail)) detailsBeforeSearch.set(detail, detail.open);
          detail.open = match && words.some(word => detail.textContent.toLocaleLowerCase().includes(word));
        } else if (detailsBeforeSearch.has(detail)) detail.open = detailsBeforeSearch.get(detail);
      }
    }
    if (!words.length) detailsBeforeSearch.clear();
    byId('guideNoResults').hidden = count > 0;
    byId('guideSearchStatus').textContent = words.length ? `找到 ${count} 个相关主题，相关的折叠说明已展开。点目录查看步骤。` : '第一次来，先看“第一次使用”。其他内容用到再查。';
  }
  function go(id, home = false) {
    const section = byId(id);
    if (!section?.classList.contains('guide-section')) return;
    if (section.hidden) { byId('guideSearch').value = ''; search(); }
    links.forEach(link => link.setAttribute('aria-current', String(link.hash === '#' + id)));
    if (id === 'start' && home) { byId('guideMain').scrollTop = 0; window.scrollTo({top:0, behavior:'instant'}); }
    else section.scrollIntoView({block:'start', behavior:'instant'});
    history.replaceState(null, '', '#' + id);
  }
  byId('guideSearch').addEventListener('input', search);
  byId('clearGuideSearch').onclick = () => { byId('guideSearch').value = ''; search(); byId('guideSearch').focus(); };
  byId('mobileGuideNav').onclick = () => { document.querySelector('.guide-nav').scrollIntoView({block:'start',behavior:'instant'});byId('guideSearch').focus({preventScroll:true}); };
  for (const link of document.querySelectorAll('a[href^="#"]')) link.addEventListener('click', event => { event.preventDefault(); go(link.hash.slice(1)); });
  function reflectActions() {
    for (const button of document.querySelectorAll('[data-guide-action]')) button.hidden = !embedded || !contextActions.includes(button.dataset.guideAction);
  }
  for (const button of document.querySelectorAll('[data-guide-action]')) button.onclick = () => notify(button.dataset.guideAction);
  reflectActions();
  window.addEventListener('message', event => {
    if (!embedded || event.source !== window.parent || event.origin !== location.origin || event.data?.type !== 'studyforge-guide-context') return;
    const data = event.data;
    document.documentElement.dataset.theme = ['dark','forest'].includes(data.theme) ? data.theme : 'light';
    document.documentElement.dataset.largeText = String(Boolean(data.largeText));
    document.documentElement.dataset.platform = data.platform === 'phone' ? 'phone' : 'desktop';
    contextActions = Array.isArray(data.actions) ? data.actions : []; reflectActions();
    if (data.section) go(data.section, true);
  });
  document.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'Escape' && embedded) { event.preventDefault(); notify('close'); }
    if (event.key === 'F1') event.preventDefault();
  });
  for (const button of document.querySelectorAll('[data-copy-example]')) button.addEventListener('click', async () => {
    const text = byId(button.dataset.copyExample), value = text.textContent;
    let copied = false;
    try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(value); copied = true; } } catch (_) { /* A denied clipboard uses the local fallback below. */ }
    if (!copied) {
      const input = document.createElement('textarea');input.value = value;
      Object.assign(input.style, {position:'fixed',top:'0',left:'-10000px'});document.body.append(input);
      input.focus();input.select();
      try { copied = document.execCommand('copy'); } catch (_) { /* Select the visible example for manual copying. */ }
      input.remove();button.focus({preventScroll:true});
    }
    if (!copied) { const selection = window.getSelection(), range = document.createRange();range.selectNodeContents(text);selection.removeAllRanges();selection.addRange(range); }
    clearTimeout(copyTimer);byId('guideCopyStatus').textContent = copied ? '示例已复制，可以粘贴到学习对话。' : '已选中示例。请按 Ctrl+C，或在手机长按复制。';
    copyTimer = setTimeout(() => { byId('guideCopyStatus').textContent = ''; }, 6000);
  });
  if (embedded) window.parent.postMessage({type:'studyforge-guide-ready'}, location.origin);
  else if (location.hash) go(location.hash.slice(1));
})();
