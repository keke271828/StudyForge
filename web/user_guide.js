/* Local help stays outside the conversation and never starts an AI task. */
(() => {
  const phone = Boolean(document.getElementById('pairScreen'));
  const dialog = document.createElement('dialog');
  dialog.id = 'userGuideDialog';
  dialog.className = 'user-guide-dialog';
  dialog.setAttribute('aria-label', 'StudyForge 零基础操作指南');
  dialog.innerHTML = '<header class="user-guide-header"><div><strong>使用指南</strong><span>零基础上手 · 随时查阅</span></div><button type="button" aria-label="关闭使用指南">关闭 <kbd>Esc</kbd></button></header><p class="user-guide-loading" role="status">正在打开本机指南…</p><iframe title="StudyForge 零基础操作指南" referrerpolicy="same-origin"></iframe>';
  document.body.append(dialog);
  const frame = dialog.querySelector('iframe');
  const close = dialog.querySelector('button');
  let opener = null, section = 'start', loaded = false, assigned = false;
  const sections = new Set(['start','map','models','projects','materials','library','tutor','teaching','outputs','feedback','homework','profile','goals','permissions','phone','background','appearance','troubleshooting','teaching-review']);
  const desktopActions = {
    study: () => showView('study'), sources: () => showView('sources'), library: () => showView('library'),
    artifacts: () => showView('artifacts'), exercises: () => showView('exercises'),
    profile: () => showView('profile'), goals: () => showView('goals'),
    models: () => { showView('settings'); showSettingsSection('models'); },
    tools: () => { showView('settings'); showSettingsSection('tools'); },
    generation: () => { showView('settings'); showSettingsSection('generation'); },
    appearance: () => { showView('settings'); showSettingsSection('appearance'); },
    system: () => { showView('settings'); showSettingsSection('system'); },
    phone: () => document.getElementById('connectMobile')?.click()
  };
  const phoneActions = {study: null, sources: 'materialsDialog', artifacts: 'artifactsDialog',
    exercises: 'homeworkDialog', models: 'optionsDialog', projects: 'workspaceDialog', library: null};
  const extra = document.createElement('button');
  extra.type = 'button';extra.className = 'user-guide-entry user-guide-settings-entry';
  extra.dataset.openUserGuide = 'start';extra.textContent = '使用指南 · 从零开始 / 常见问题';
  extra.setAttribute('aria-haspopup', 'dialog');
  if (phone) document.querySelector('#optionsDialog .sheet-body').prepend(extra);
  else {
    // A second entry lives with the system settings, outside the chat history.
    document.getElementById('desktopControls').parentElement.append(extra);
  }
  function actions() {
    if (!phone) return Object.keys(desktopActions).filter(key => key !== 'phone' || document.getElementById('connectMobile'));
    return document.getElementById('learningApp').hidden ? [] : Object.keys(phoneActions);
  }
  function context(navigate = false) {
    if (!loaded) return;
    const theme = document.documentElement.dataset.theme;
    frame.contentWindow.postMessage({type: 'studyforge-guide-context', platform: phone ? 'phone' : 'desktop',
      theme: ['night','dark'].includes(theme) ? 'dark' : theme === 'forest' ? 'forest' : 'light',
      largeText: document.documentElement.dataset.textSize === 'large', ...(navigate ? {section} : {}), actions: actions()}, location.origin);
  }
  function open(target = 'start') {
    if (typeof target === 'string' && sections.has(target)) section = target;
    if (dialog.open) { context(true); return; }
    opener = document.activeElement;
    // A phone sheet may be the caller; avoid leaving a second modal underneath.
    if (phone) for (const other of document.querySelectorAll('dialog[open]')) if (other !== dialog) other.close();
    dialog.showModal();
    if (!assigned) { assigned = true; frame.src = '/help/guide.html'; }
    context(true); close.focus();
  }
  close.onclick = () => dialog.close();
  dialog.addEventListener('close', () => { if (opener?.isConnected && !opener.closest('dialog:not([open])')) opener.focus({preventScroll: true}); });
  frame.addEventListener('load', () => { loaded = true; dialog.querySelector('.user-guide-loading').hidden = true; context(true); });
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== frame.contentWindow || !dialog.open) return;
    if (event.data?.type === 'studyforge-guide-ready') { loaded = true; context(true); return; }
    if (event.data?.type !== 'studyforge-guide-action') return;
    const action = event.data.action;
    if (action === 'close') { dialog.close(); return; }
    if (!actions().includes(action)) return;
    dialog.close();
    if (phone) {
      if (action === 'library') Promise.resolve(window.libraryOpen()).catch(error => toast(error.message));
      else if (action === 'exercises' && window.studyforgeMobileHomework) Promise.resolve(window.studyforgeMobileHomework.open()).catch(error => toast(error.message));
      else if (phoneActions[action]) openSheet(phoneActions[action]);
    } else desktopActions[action]();
  });
  new MutationObserver(() => context()).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme','data-text-size']});
  const helpTargets = phone ? [
    ['#materialsDialog .sheet-body', 'materials', '上传和解析怎么用？'],
    ['#generateForm', 'outputs', '怎样生成和下载？'],
    ['#homeworkBrowse', 'homework', '怎样交作业和看解析？']
  ] : [
    ['#view-study .context-toolbar', 'materials', '上传和解析怎么用？'],
    ['#view-study .generation-intro', 'outputs', '怎样生成和下载？'],
    ['#view-sources .page-heading', 'materials', '资料操作说明'],
    ['#view-artifacts .page-heading', 'outputs', '成果操作说明'],
    ['#view-exercises .page-heading', 'homework', '出题与交作业说明'],
    ['#view-profile .page-heading', 'profile', '画像和自评怎么用？'],
    ['#view-goals .section-intro', 'goals', '怎样安排学习目标？']
  ];
  for (const [selector, target, label] of helpTargets) {
    const host = document.querySelector(selector); if (!host) continue;
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'user-guide-context'; button.dataset.openUserGuide = target;
    button.setAttribute('aria-haspopup', 'dialog'); button.textContent = '? ' + label;
    if (phone) host.prepend(button); else host.append(button);
  }
  // Delegation also covers help buttons in dynamically rendered book panels.
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-open-user-guide]');
    if (!button) return; event.preventDefault(); open(button.dataset.openUserGuide || 'start');
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'F1' && !event.isComposing) { event.preventDefault(); if (!dialog.open) open(); else close.focus(); }
  });
  window.studyforgeUserGuide = {open};
})();
