/* Notifications belong above the workspace and inside the active modal's focus scope. */
const notificationState={active:false,timer:null,remaining:0,deadline:0,paused:new Set(),dialogs:[],scheduled:false,promote:false};

function notificationModal() {
  notificationState.dialogs=notificationState.dialogs.filter(node=>node.isConnected&&node.matches('dialog:modal'));
  return notificationState.dialogs.at(-1)||[...document.querySelectorAll('dialog:modal')].at(-1);
}

function promoteNotification(force=false) {
  if(!notificationState.active)return;
  const node=document.getElementById('toast'),fullscreen=document.fullscreenElement;
  const parent=notificationModal()||(fullscreen&&!fullscreen.contains(document.body)?fullscreen:document.body);
  if(node.parentElement!==parent||force) {
    if(node.matches(':popover-open'))node.hidePopover();
    if(node.parentElement!==parent)parent.appendChild(node);
  }
  // A high z-index is the fallback; popovers also escape clipping and modal backdrops.
  if(typeof node.showPopover==='function'&&!node.matches(':popover-open')) {
    try{node.showPopover();}catch(_){/* Keep the fixed-position fallback visible. */}
  }
}

function scheduleNotificationPromotion(force=false) {
  notificationState.promote||=force;
  if(notificationState.scheduled)return;
  notificationState.scheduled=true;
  queueMicrotask(()=>{notificationState.scheduled=false;const promote=notificationState.promote;notificationState.promote=false;promoteNotification(promote);});
}

function dismissToast() {
  const node=document.getElementById('toast');
  clearTimeout(notificationState.timer);notificationState.timer=null;notificationState.active=false;notificationState.paused.clear();
  node.classList.remove('show');
  if(node.matches(':popover-open'))node.hidePopover();
  node.hidden=true;
  // A later dialog clear/rebuild must not remove the notification host.
  if(node.parentElement!==document.body)document.body.appendChild(node);
}

function resumeToast() {
  clearTimeout(notificationState.timer);notificationState.timer=null;
  if(!notificationState.active)return;
  const host=document.getElementById('toast');
  // Native focus transitions and top-layer changes can omit boundary events.
  if(!host.matches(':hover'))notificationState.paused.delete('hover');
  if(!host.contains(document.activeElement))notificationState.paused.delete('focus');
  if(notificationState.paused.size){notificationState.timer=setTimeout(resumeToast,250);return;}
  notificationState.deadline=performance.now()+notificationState.remaining;
  notificationState.timer=setTimeout(()=>{
    // A toast can appear under a stationary pointer without a new enter event.
    const node=document.getElementById('toast');
    if(node.matches(':hover'))return pauseToast('hover');
    if(node.contains(document.activeElement))return pauseToast('focus');
    dismissToast();
  },notificationState.remaining);
}

function pauseToast(reason) {
  if(notificationState.paused.has(reason))return;
  if(notificationState.active&&!notificationState.paused.size)notificationState.remaining=Math.max(0,notificationState.deadline-performance.now());
  notificationState.paused.add(reason);clearTimeout(notificationState.timer);notificationState.timer=null;
  notificationState.timer=setTimeout(resumeToast,250);
}

function unpauseToast(reason) {if(notificationState.paused.delete(reason))resumeToast();}

function toast(message,options={}) {
  const node=document.getElementById('toast');
  clearTimeout(notificationState.timer);
  node.querySelector('.toast-message').textContent=String(message??'');
  window.studyforgeOperationErrors?.decorateToast(node,message);
  const duration=Number(options.duration??5000);
  notificationState.remaining=Number.isFinite(duration)?Math.min(60000,Math.max(100,duration)):5000;
  notificationState.active=true;node.hidden=false;node.classList.add('show');
  // Replacing a toast must not leave a stale hover/focus pause from its old parent.
  notificationState.paused.clear();promoteNotification();
  if(node.matches(':hover'))notificationState.paused.add('hover');
  if(node.contains(document.activeElement))notificationState.paused.add('focus');
  resumeToast();
}

const notificationHost=document.getElementById('toast');
notificationHost.querySelector('.toast-close').addEventListener('click',dismissToast);
notificationHost.addEventListener('pointerenter',()=>pauseToast('hover'));
notificationHost.addEventListener('pointerleave',()=>unpauseToast('hover'));
notificationHost.addEventListener('focusin',()=>pauseToast('focus'));
notificationHost.addEventListener('focusout',event=>{if(!notificationHost.contains(event.relatedTarget))unpauseToast('focus');});
// Top-layer reparenting can suppress an enter/leave pair. Actual pointer motion
// still provides the correct target, including after opening or closing a dialog.
for(const name of ['pointermove','mousemove'])document.addEventListener(name,event=>{
  if(!notificationState.active)return;
  if(event.composedPath().includes(notificationHost))pauseToast('hover');else unpauseToast('hover');
},true);
document.addEventListener('beforetoggle',event=>{
  if(event.target.tagName!=='DIALOG')return;
  const node=event.target;notificationState.dialogs=notificationState.dialogs.filter(dialog=>dialog!==node);
  if(event.newState==='open')notificationState.dialogs.push(node);
  scheduleNotificationPromotion();
},true);
new MutationObserver(records=>{
  if(records.some(record=>record.type==='attributes'?record.target.tagName==='DIALOG':
    [...record.addedNodes,...record.removedNodes].some(node=>node.nodeType===1&&(node.tagName==='DIALOG'||node.querySelector('dialog')))))scheduleNotificationPromotion();
}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});
document.addEventListener('fullscreenchange',()=>scheduleNotificationPromotion(true));
