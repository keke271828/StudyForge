/* Reading notes use an independent, local viewer; opening it never sends a chat. */
const readingNotesState = {key: null, scope: null, readingId: null, positions: new Map()};

function rememberReadingNotesPosition() {
  if (!readingNotesState.key) return;
  const positions = readingNotesState.positions;
  positions.delete(readingNotesState.key);
  positions.set(readingNotesState.key, $('readingNotesBody').scrollTop);
  if (positions.size > 40) positions.delete(positions.keys().next().value);
}

function closeReadingNotes(invalidate = false) {
  const dialog = $('readingNotesDialog');
  if (dialog.open) {
    rememberReadingNotesPosition();
    dialog.close();
    const opener = $('showReadingNotes');
    if (!invalidate && state.view === 'study' && !opener.hidden && !opener.disabled) opener.focus({preventScroll:true});
  }
  if (invalidate) {
    readingNotesState.key = readingNotesState.scope = readingNotesState.readingId = null;
    $('readingNotesText').replaceChildren();
    delete $('readingNotesText').dataset.rawText;
    $('readingNotesSources').replaceChildren();
    $('readingNotesContext').textContent = '';
    $('readingNotesCopyStatus').textContent = '';
  }
}

function syncReadingNotes() {
  if (!$('readingNotesDialog').open) return;
  if (state.reading?.status !== 'completed' || readingNotesState.scope !== materialScope()
      || readingNotesState.readingId !== state.reading.reading_id) closeReadingNotes(true);
}

function openReadingNotes() {
  const reading = state.reading;
  if (!state.ready || state.projectLoading || conversationUI.restoring) return;
  if (reading?.status !== 'completed' || !reading.notes?.trim()) return toast('当前资料暂无阅读笔记，请先完成通读');
  const scope = materialScope(), key = `${scope}:${reading.reading_id || ''}`;
  const dialog = $('readingNotesDialog'), body = $('readingNotesBody');
  if (dialog.open && readingNotesState.key === key) return;
  closeReadingNotes();
  const unchanged = readingNotesState.key === key && $('readingNotesText').dataset.rawText === reading.notes;
  readingNotesState.key = key; readingNotesState.scope = scope; readingNotesState.readingId = reading.reading_id;
  if (!unchanged) renderLessonText($('readingNotesText'), reading.notes);
  $('readingNotesContext').textContent = `${state.project.name} · ${$('conversationTitle').textContent}`;
  $('readingNotesSourceCount').textContent = `所选资料（${state.selected.size}）`;
  $('readingNotesSources').replaceChildren();
  for (const id of state.selected) {
    const item = document.createElement('li');
    item.textContent = state.sources.find(row => row.id === id)?.name || '当前所选资料';
    $('readingNotesSources').append(item);
  }
  $('readingNotesCopyStatus').textContent = '';
  if (!unchanged) $('readingNotesMaterials').open = false;
  dialog.showModal();
  body.scrollTop = readingNotesState.positions.get(key) || 0;
}

function initializeReadingNotes() {
  $('showReadingNotes').onclick = openReadingNotes;
  for (const id of ['closeReadingNotes', 'returnFromReadingNotes']) $(id).onclick = () => closeReadingNotes();
  $('readingNotesDialog').addEventListener('cancel', event => {
    event.preventDefault(); closeReadingNotes();
  });
  $('copyReadingNotes').onclick = async () => {
    const key = readingNotesState.key, text = $('readingNotesText').dataset.rawText;
    if (!text || !key) return;
    const button = $('copyReadingNotes'); button.disabled = true;
    try {
      await copyText(text);
      if (key === readingNotesState.key && $('readingNotesDialog').open) $('readingNotesCopyStatus').textContent = '笔记已复制';
    } catch (failure) {
      if (key === readingNotesState.key && $('readingNotesDialog').open) $('readingNotesCopyStatus').textContent = `${failure.message}；可直接选中笔记手动复制`;
    } finally { button.disabled = false; }
  };
}
