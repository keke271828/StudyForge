/* File permissions are enforced by shared backend tools for either AI provider. */
let agentPermissionSave=Promise.resolve(),agentPermissionPending=0,agentPermissionRevision=0;
let agentPermissionConfirmed='approval',agentPermissionCurrent='approval',agentApprovalPollBusy=false;
const agentApprovalDecisions=new Set();
const permissionDescriptions={read_only:'只读：AI 可以看当前资料和允许读取的文件夹，不能创建、修改或删除文件。',
  approval:'需要审批：AI 可操作当前工作文件夹和你已授权的文件夹；其他文件操作会先问你。',
  full_access:'完全访问：AI 可按当前 Windows 账号权限操作文件，删除和修改也可能直接执行。其他对话仍不共享；联网、网页视频需另行允许。'};

function applyAgentPermissionPreferences(config){
  if(!agentPermissionPending){agentPermissionConfirmed=config.agent_permission_mode||'approval';agentPermissionCurrent=agentPermissionConfirmed;}
  const select=$('agentPermissionMode');select.value=agentPermissionCurrent;
  select.title=permissionDescriptions[agentPermissionCurrent];
  select.dataset.mode=agentPermissionCurrent;
  $('agentPermissionHint').textContent=agentPermissionPending?'正在保存权限…':permissionDescriptions[agentPermissionCurrent];
  $('agentPermissionHint').title=permissionDescriptions[agentPermissionCurrent];
  $('videoImportMode').value=config.video_import_mode||'full';
}

function saveAgentPermissionMode(mode){
  const revision=++agentPermissionRevision;agentPermissionPending++;agentPermissionCurrent=mode;
  applyAgentPermissionPreferences(state.settings||{});
  agentPermissionSave=agentPermissionSave.catch(()=>{}).then(async()=>{
    try{
      const config=await api('/api/settings',jsonOptions('PUT',{agent_permission_mode:mode}));
      agentPermissionConfirmed=config.agent_permission_mode;
      if(state.settings)state.settings.agent_permission_mode=agentPermissionConfirmed;
      if(revision===agentPermissionRevision)toast('权限已生效：'+$('agentPermissionMode').selectedOptions[0].textContent);
    }catch(failure){if(revision===agentPermissionRevision)agentPermissionCurrent=agentPermissionConfirmed;error(failure);}
    finally{agentPermissionPending--;if(!agentPermissionPending)applyAgentPermissionPreferences({...state.settings,agent_permission_mode:agentPermissionCurrent});}
  });
  return agentPermissionSave;
}

function approvalScope(){return `${state.project?.id||''}:${state.conversation||''}`;}
function agentApprovalHost(){
  let host=$('agentApprovalRequests');
  if(!host){host=document.createElement('section');host.id='agentApprovalRequests';host.hidden=true;host.setAttribute('aria-label','文件操作审批');host.setAttribute('aria-live','polite');$('messages').append(host);}
  return host;
}
async function refreshAgentApprovals(){
  if(agentApprovalPollBusy||!state.project||!state.conversation||conversationUI.restoring)return;
  agentApprovalPollBusy=true;const scope=approvalScope();
  try{
    const value=await api(`/api/agent/approvals?project_id=${encodeURIComponent(state.project.id)}&conversation_id=${encodeURIComponent(state.conversation)}`);
    if(scope!==approvalScope()||conversationUI.restoring)return;
    // A poll started before a click may return after its successful decision.
    value.requests=value.requests.filter(row=>!agentApprovalDecisions.has(row.id));
    const host=agentApprovalHost();host.hidden=!value.requests.length;
    const identity=JSON.stringify(value.requests);
    if(host.dataset.identity===identity&&host.dataset.scope===scope)return;
    host.dataset.identity=identity;host.dataset.scope=scope;host.replaceChildren();
    for(const row of value.requests){
      const card=document.createElement('article');card.className='agent-approval-card';card.dataset.approvalId=row.id;
      const title=document.createElement('strong');title.textContent='等待你审批 · '+({sf_read_file:'读取文件',sf_list_files:'查看目录',sf_inspect_media:'读取画面',sf_write_text:'写入文件',sf_edit_text:'修改文件',sf_delete_file:'删除文件',sf_copy_file:'复制文件'}[row.tool]||row.tool);card.append(title);
      for(const item of row.details.paths||[]){const path=document.createElement('p');path.className='approval-path';path.textContent=item.operation+'：'+item.path;card.append(path);}
      if(row.details.preview){const preview=document.createElement('details');const label=document.createElement('summary');label.textContent='查看修改内容';const pre=document.createElement('pre');pre.textContent=row.details.preview;preview.append(label,pre);card.append(preview);}
      const description=document.createElement('small');description.textContent=row.details.scope;card.append(description);
      const controls=document.createElement('div');controls.className='approval-actions';
      for(const [approved,label] of [[true,'批准这一次'],[false,'拒绝']]){
        const button=document.createElement('button');button.textContent=label;if(approved)button.className='primary';
        button.onclick=async()=>{
          if(scope!==approvalScope())return;
          for(const el of controls.children)el.disabled=true;
          try{
            await api(`/api/agent/approvals/${row.id}`,jsonOptions('POST',{project_id:row.project_id,conversation_id:row.conversation_id,approved}));
            agentApprovalDecisions.add(row.id);if(agentApprovalDecisions.size>256)agentApprovalDecisions.delete(agentApprovalDecisions.values().next().value);
            card.remove();host.hidden=!host.children.length;host.dataset.identity='';
          }
          catch(failure){for(const el of controls.children)el.disabled=false;error(failure);}
        };controls.append(button);
      }card.append(controls);host.append(card);
    }
    if(value.requests.length){$('messages').querySelector('.empty-state')?.remove();host.scrollIntoView({block:'nearest'});}
  }catch(_){/* Reconcile after switching chats or restarting a local server. */}
  finally{agentApprovalPollBusy=false;}
}

function initializeAgentPermissions(){
  const control=document.createElement('label');control.className='agent-permission-control';control.textContent='权限 ';
  const select=document.createElement('select');select.id='agentPermissionMode';select.setAttribute('aria-label','AI 可以怎样操作文件');
  for(const [value,label] of [['read_only','只读'],['approval','需要审批'],['full_access','完全访问']]){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}
  control.append(select);$('recordVoice').before(control);select.onchange=()=>saveAgentPermissionMode(select.value);
  const hint=document.createElement('span');hint.id='agentPermissionHint';hint.className='agent-permission-hint';hint.setAttribute('role','status');document.querySelector('.composer-actions').after(hint);
  agentApprovalHost();
  const video=document.createElement('label');video.className='field';video.textContent='网址视频读取方式';
  const mode=document.createElement('select');mode.id='videoImportMode';
  for(const [value,label] of [['full','读取声音和关键画面（含板书、图表）'],['subtitles_first','先读字幕 · 完整时不下载视频']]){const option=document.createElement('option');option.value=value;option.textContent=label;mode.append(option);}
  video.append(mode);const note=document.createElement('small');note.className='small-note';note.textContent='读声音和画面时，可能需要临时下载视频，完成后会自动清理。只读字幕更省时间，但看不到板书和图表；字幕不完整时会改读声音和画面。';video.append(note);$('agentToolsEnabled').closest('.settings-card').append(video);
  mode.onchange=async()=>{mode.disabled=true;try{state.settings=await api('/api/settings',jsonOptions('PUT',{video_import_mode:mode.value}));toast('视频读取方式已保存');}catch(failure){mode.value=state.settings?.video_import_mode||'full';error(failure);}finally{mode.disabled=false;}};
  applyAgentPermissionPreferences({});
  setInterval(()=>{if(state.view==='study')refreshAgentApprovals();},750);
}
