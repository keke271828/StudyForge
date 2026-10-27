// The guide uses the same mode definitions as the actual model requests.
let modeGuideCatalog = null;
let modeGuideLoading = null;

function refreshModeGuideSelection() {
  const selected = currentLearningMode();
  document.querySelectorAll('[data-mode-guide-select]').forEach(button => {
    const active = button.dataset.modeGuideSelect === selected;
    button.setAttribute('aria-pressed', String(active));
    button.textContent = active ? '当前模式' : '使用这个模式';
    button.disabled = $('learningMode').disabled;
    button.closest('.mode-guide-card').classList.toggle('selected', active);
  });
  const feature = modeGuideCatalog?.[selected];
  if (feature) $('learningModeHint').title = `${feature.aim}。${feature.focus}。${feature.method}。`;
}

async function openModeGuide() {
  const dialog = $('modeGuideDialog');
  if (!dialog.open) dialog.showModal();
  refreshModeGuideSelection();
  if (modeGuideCatalog) return;
  $('modeGuideStatus').textContent = '正在读取当前教学模式说明…';
  modeGuideLoading ||= api('/api/learning-modes').finally(() => { modeGuideLoading = null; });
  try {
    const result = await modeGuideLoading;
    modeGuideCatalog = result.modes;
    const host = $('modeGuideCards'); host.replaceChildren();
    for (const [key, feature] of Object.entries(modeGuideCatalog)) {
      const card = document.createElement('article'); card.className = 'mode-guide-card';
      const title = document.createElement('h3'); title.textContent = feature.label;
      const aim = document.createElement('p'); aim.className = 'mode-guide-aim'; aim.textContent = feature.aim;
      const detail = document.createElement('p'); detail.textContent = feature.allocation;
      const checks = document.createElement('ul');
      feature.checks.forEach(text => { const item = document.createElement('li'); item.textContent = text; checks.append(item); });
      const button = document.createElement('button'); button.type = 'button'; button.dataset.modeGuideSelect = key;
      button.onclick = () => { if ($('learningMode').disabled) return; applyLearningMode(key); refreshModeGuideSelection(); dialog.close(); };
      card.append(title, aim, detail, checks, button); host.append(card);
    }
    $('modeGuideStatus').textContent = result.notice;
    refreshModeGuideSelection();
  } catch (err) {
    $('modeGuideStatus').textContent = `模式说明读取失败：${err.message}。关闭后重新打开可重试。`;
  }
}

document.getElementById('openModeGuide').onclick = openModeGuide;
document.getElementById('closeModeGuide').onclick = () => $('modeGuideDialog').close();
