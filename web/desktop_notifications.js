/* Native delivery is owned by Electron, including when the window is hidden. */
const desktopNoticeFields={
  desktop_notifications_enabled:'desktopNotifyEnabled',desktop_notifications_sound:'desktopNotifySound',
  desktop_notifications_foreground:'desktopNotifyForeground',desktop_notifications_complete:'desktopNotifyComplete',
  desktop_notifications_approval:'desktopNotifyApproval',desktop_notifications_failure:'desktopNotifyFailure',
  desktop_notifications_questionnaire:'desktopNotifyQuestionnaire',desktop_notifications_chat:'desktopNotifyChat',
  desktop_notifications_update:'desktopNotifyUpdate'};
let desktopNoticeState=null,desktopNoticePendingTarget=null,desktopNoticeNavigation=Promise.resolve();
let desktopNoticeSettingsRevision=0,desktopNoticeSettingsDirty=false;

function applyDesktopNotificationSettings(config,revision=desktopNoticeSettingsRevision){
  if(desktopNoticeSettingsDirty||revision!==desktopNoticeSettingsRevision)return;
  for(const [key,id] of Object.entries(desktopNoticeFields))if($(id))$(id).checked=config[key]!==false;
}
function renderDesktopNotifications(value){
  desktopNoticeState=value;const badge=$('desktopNoticeBadge');badge.textContent=value.active_actions||'';badge.hidden=!value.active_actions;
  $('desktopNoticeBell').title=value.active_actions?`${value.active_actions} 项等待你处理 · 查看通知`:'查看通知';
  const status=$('desktopNotifyStatus');
  status.textContent=value.last_error?'通知遇到问题：'+value.last_error:!value.connected?'正在连接本机通知服务…':!value.settings.desktop_notifications_enabled?'Windows 桌面通知已关闭；通知记录仍保留。':!value.supported?'当前系统不支持桌面通知。':
    value.last_delivery?.native_shown?'Windows 已接收最近一条Windows 通知；实际横幅显示遵循系统的通知与勿扰设置。':'通知已启用；成果完成与待处理事件会自动提醒。';
  paintDesktopNoticeList();
}
function paintDesktopNoticeList(){
  const host=$('desktopNoticeList');if(!host||!$('desktopNoticesDialog').open)return;
  host.replaceChildren();const recent=desktopNoticeState?.recent||[];
  if(!recent.length){const p=document.createElement('p');p.className='small-note';p.textContent='目前没有通知。完成成果、收到审批或需要填写错因问卷时会显示在这里。';host.append(p);return;}
  const icons={complete:'✓',approval:'◇',failure:'!',questionnaire:'?',chat:'☏',update:'↻'};
  for(const row of recent){
    const button=document.createElement('button');button.type='button';button.className='desktop-notice-item';
    button.dataset.desktopNotice=String(row.id);
    const icon=document.createElement('span');icon.className='desktop-notice-icon';icon.textContent=icons[row.category]||'•';icon.setAttribute('aria-hidden','true');
    const text=document.createElement('span'),title=document.createElement('strong'),body=document.createElement('span'),date=document.createElement('small');
    title.textContent=row.title+(['approval','questionnaire'].includes(row.category)&&!row.action_pending?' · 已处理':'');body.textContent=row.body;body.className='desktop-notice-detail';
    date.textContent=new Date(row.created_at).toLocaleString('zh-CN');text.append(title,body,date);button.append(icon,text);
    button.onclick=async()=>{button.disabled=true;try{$('desktopNoticesDialog').close();await window.studyforgeDesktop.openNotification(row.id);}catch(failure){error(failure);button.disabled=false;}};
    host.append(button);
  }
}
async function refreshDesktopNotificationControls(){
  if(!window.studyforgeDesktop?.notificationStatus){$('testDesktopNotification').disabled=true;return;}
  $('desktopNoticeBell').hidden=false;
  try{renderDesktopNotifications(await window.studyforgeDesktop.notificationStatus());}catch(_){/* Main-process startup may still be registering IPC. */}
}
function navigateDesktopNotice(target){
  if(!state.ready){desktopNoticePendingTarget=target;return Promise.resolve();}
  desktopNoticeNavigation=desktopNoticeNavigation.catch(()=>{}).then(async()=>{
    if(typeof target==='string'){showView(target);return;}
    if(!target||!['study','artifacts','sources','settings','library'].includes(target.view))return;
    if($('homeworkDialog')?.open)captureHomeworkDraft();
    document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
    if(target.project_id){
      await refreshNavigation();const project=navigationUI.projects.find(row=>row.id===target.project_id);
      if(!project)throw new Error('通知对应的项目已移入回收站或删除');
      await selectProject(project,{conversationId:target.conversation_id||null});
    }
    showView(target.view);
    if(target.view==='library'){await window.libraryOpen?.(target.book_id);return;}
    if(target.view==='settings')showSettingsSection(target.settings_section||'notifications');
    if(target.view==='artifacts'){
      await refreshArtifacts();
      const card=[...$('artifacts').querySelectorAll('[data-artifact]')].find(row=>row.dataset.artifact===target.artifact_id);
      if(card){card.scrollIntoView({block:'center'});card.classList.add('notice-arrival');setTimeout(()=>card.classList.remove('notice-arrival'),2000);}
    }
    if(target.approval_id){
      for(let i=0;agentApprovalPollBusy&&i<25;i++)await new Promise(resolve=>setTimeout(resolve,40));
      await refreshAgentApprovals();
      const card=[...document.querySelectorAll('[data-approval-id]')].find(row=>row.dataset.approvalId===target.approval_id);
      if(card)card.scrollIntoView({block:'center'});
      else toast('这项审批已经处理或失效；已打开原对话');
    }
    if(target.homework_attempt_id){await refreshArtifacts();await openHomeworkCauses(target.homework_attempt_id);}
  });
  return desktopNoticeNavigation;
}
function initializeDesktopNotifications(){
  $('desktopNoticeBell').querySelector('[aria-hidden]').innerHTML='<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 9a6 6 0 0 1 12 0v5l2 3H4l2-3V9Z"/><path d="M9 20h6"/></svg>';
  window.studyforgeDesktop?.onNotificationChanged?.(renderDesktopNotifications);
  for(const id of Object.values(desktopNoticeFields))$(id).onchange=()=>{desktopNoticeSettingsDirty=true;desktopNoticeSettingsRevision++;};
  $('desktopNoticeBell').onclick=async()=>{await refreshDesktopNotificationControls();$('desktopNoticesDialog').showModal();paintDesktopNoticeList();};
  $('closeDesktopNotices').onclick=()=>$('desktopNoticesDialog').close();
  $('desktopNoticeSettings').onclick=()=>{$('desktopNoticesDialog').close();showView('settings');showSettingsSection('notifications');$('desktopNotificationControls').scrollIntoView({block:'center'});};
  $('saveDesktopNotifications').onclick=async()=>{
    const button=$('saveDesktopNotifications');button.disabled=true;
    const revision=desktopNoticeSettingsRevision;
    try{
      const payload=Object.fromEntries(Object.entries(desktopNoticeFields).map(([key,id])=>[key,$(id).checked]));
      const config=await api('/api/settings',jsonOptions('PUT',payload));state.settings={...state.settings,...config};
      if(revision===desktopNoticeSettingsRevision)desktopNoticeSettingsDirty=false;
      toast('Windows 桌面通知设置已保存');await refreshDesktopNotificationControls();
    }catch(failure){error(failure);}finally{button.disabled=false;}
  };
  $('testDesktopNotification').onclick=async()=>{
    const button=$('testDesktopNotification');button.disabled=true;
    try{renderDesktopNotifications(await window.studyforgeDesktop.testNotification());toast('已发送测试通知，请查看 Windows 右下角或通知中心');}
    catch(failure){error(failure);}finally{button.disabled=false;}
  };
  refreshDesktopNotificationControls();
}
