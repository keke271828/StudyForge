/* Project folders are visible inside Outputs and share the active project. */
const artifactFoldersState = {projects: [], signature: null};

function setArtifactFolderProjects(projects) {
  const old = new Map(artifactFoldersState.projects.map(project => [project.id, project]));
  artifactFoldersState.projects = projects.map(project => ({...old.get(project.id), ...project}));
  renderArtifactFolders();
}

function renderArtifactFolders() {
  const host = $('artifactFolders');
  if (!host) return;
  const selected = state.project;
  $('artifactFolderTitle').textContent = selected?.name || '选择一个学习项目';
  const current = artifactFoldersState.projects.find(project => project.id === selected?.id);
  $('artifactFolderSummary').textContent = current
    ? `${current.artifact_count ?? 0} 份成果${current.pending_count ? ' · '+current.pending_count+' 项未完成任务' : ''}`
    : '成果按学习项目保存';
  const query = $('artifactFolderSearch').value.trim().toLocaleLowerCase();
  const signature = JSON.stringify([selected?.id, query, artifactFoldersState.projects]);
  if (signature === artifactFoldersState.signature) return;
  artifactFoldersState.signature = signature;
  const projects = artifactFoldersState.projects.filter(project => project.name.toLocaleLowerCase().includes(query));
  $('artifactFolderCount').textContent = `${artifactFoldersState.projects.length} 个项目`;
  const focusId = document.activeElement?.dataset?.artifactProject;
  const position = host.scrollTop;
  host.innerHTML = projects.length ? projects.map(project => {
    const active = project.id === selected?.id;
    return `<button type="button" class="artifact-folder ${active ? 'active' : ''}" data-artifact-project="${escapeHtml(project.id)}" ${active ? 'aria-current="page"' : ''}>
      <svg class="artifact-folder-icon" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"/><path d="M3 10h18"/></svg>
      <span class="artifact-folder-text"><strong title="${escapeHtml(project.name)}">${escapeHtml(project.name)}</strong><small><span data-folder-artifact-count>${project.artifact_count ?? 0}</span> 份成果${project.pending_count ? ' · '+project.pending_count+' 项未完成' : ''}</small></span>
      ${active ? '<span class="artifact-folder-selected" aria-hidden="true">›</span>' : ''}</button>`;
  }).join('') : '<p class="small-note artifact-folder-empty">没有匹配的项目文件夹。</p>';
  host.scrollTop = position;
  if (focusId) [...host.querySelectorAll('[data-artifact-project]')].find(button => button.dataset.artifactProject === focusId)?.focus({preventScroll:true});
}

function initializeArtifactFolders() {
  $('artifactFolderSearch').oninput = renderArtifactFolders;
  $('artifactFolders').onclick = async event => {
    const button = event.target.closest('[data-artifact-project]');
    if (!button) return;
    const project = artifactFoldersState.projects.find(row => row.id === button.dataset.artifactProject);
    if (!project) return;
    try {
      if (state.project?.id !== project.id) await selectProject(project);
      else await refreshArtifacts();
    } catch (failure) { error(failure); }
  };
}
