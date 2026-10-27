const {desktopCaller}=require('./lifecycle');

const CATEGORIES=new Set(['complete','approval','failure','questionnaire','chat','update']);
const VIEWS=new Set(['study','sources','artifacts','settings']);
function safeTarget(value){
  if(!value||typeof value!=='object'||!VIEWS.has(value.view))throw new Error('通知目标无效');
  const target={view:value.view};
  if(value.settings_section!=null){
    if(!['notifications','system'].includes(value.settings_section))throw new Error('通知设置分类无效');
    target.settings_section=value.settings_section;
  }
  for(const key of ['project_id','conversation_id','artifact_id','job_id','approval_id','homework_attempt_id']){
    if(value[key]==null)continue;
    if(typeof value[key]!=='string'||!/^\w[\w-]{0,127}$/.test(value[key]))throw new Error('通知目标标识无效');
    target[key]=value[key];
  }
  return target;
}

function createNotificationManager({Notification,icon,getWindow,showWindow,readFeed,acknowledge,
                                    notify=()=>{},interval=1500,onError=()=>{}}){
  let timer,busy=false,stopped=false,config={},recent=[],actions=[],connected=false,lastError='',lastDelivery=null;
  let revision='',connectionError='';
  const sent=new Map(),native=new Map(),pendingReceipts=new Map(),localHistory=new Map();
  const supported=()=>{try{return Boolean(Notification.isSupported());}catch(_){return false;}};
  const snapshot=()=>({supported:supported(),connected,settings:{...config},last_error:lastError,
    last_delivery:lastDelivery,active_actions:actions.length,
    recent:[...localHistory.values(),...recent].sort((a,b)=>Number(Boolean(b.action_pending))-Number(Boolean(a.action_pending))||b.created_at.localeCompare(a.created_at)).slice(0,50)});
  function publish(){const value=snapshot(),signature=JSON.stringify(value);if(signature!==revision){revision=signature;notify(value);}}
  const focused=()=>{const win=getWindow();return Boolean(win&&!win.isDestroyed()&&win.isVisible()&&!win.isMinimized()&&win.isFocused());};
  const remember=(key,status)=>{sent.set(key,status);while(sent.size>1000)sent.delete(sent.keys().next().value);};
  function dismiss(key){const instance=native.get(key);if(!instance)return;native.delete(key);try{instance.close();}catch(_){}}
  function fail(error){lastError=String(error?.message||error).slice(0,400);onError(new Error(lastError));publish();}
  function show(event,{test=false}={}){
    if(stopped||(!test&&sent.has(event.notice_key)))return sent.get(event.notice_key)||'skipped';
    if(!test&&(!config.desktop_notifications_enabled||!config['desktop_notifications_'+event.category]
       ||(focused()&&(event.category==='chat'||config.desktop_notifications_foreground===false)))){
      remember(event.notice_key,'skipped');return 'skipped';
    }
    if(!supported()){remember(event.notice_key,'failed');fail('当前系统无法使用桌面通知');return 'failed';}
    try{
      const target=safeTarget(event.target);
      const instance=new Notification({title:'StudyForge · '+String(event.title).slice(0,100),
        body:String(event.body).slice(0,380),icon,silent:config.desktop_notifications_sound===false,
        timeoutType:['approval','questionnaire'].includes(event.category)?'never':'default'});
      native.set(event.notice_key,instance);
      // Keep native objects alive after banner timeout: a click from Windows'
      // notification center must still return to the right project and chat.
      let clicked=false;
      instance.on('click',()=>{if(clicked)return;clicked=true;Promise.resolve().then(()=>showWindow(target)).catch(fail);});
      instance.on('failed',(_event,message)=>{
        for(const key of event.notice_keys||[event.notice_key])remember(key,'failed');
        for(const id of event.receipt_ids||[event.id])if(Number.isInteger(id))pendingReceipts.set(id,'failed');
        fail(message||'Windows 未能显示通知');});
      instance.on('show',()=>{lastDelivery={title:event.title,created_at:new Date().toISOString(),native_shown:true};publish();});
      instance.show();
      if(sent.get(event.notice_key)==='failed')return 'failed';
      remember(event.notice_key,'sent');lastError='';
      lastDelivery={title:event.title,created_at:new Date().toISOString(),native_shown:lastDelivery?.title===event.title&&Boolean(lastDelivery.native_shown)};
      while(native.size>100)dismiss(native.keys().next().value);
      publish();return 'sent';
    }catch(error){remember(event.notice_key,'failed');fail(error);return 'failed';}
  }
  async function flushReceipts(){
    for(const status of ['sent','skipped','failed']){
      const ids=[...pendingReceipts].filter(([,value])=>value===status).slice(0,40).map(([id])=>id);
      if(!ids.length)continue;
      await acknowledge(ids,status);
      for(const id of ids)if(pendingReceipts.get(id)===status)pendingReceipts.delete(id);
    }
  }
  async function poll(){
    if(busy||stopped)return;busy=true;
    try{
      await flushReceipts();
      const feed=await readFeed();if(stopped)return;
      if(lastError===connectionError)lastError='';connectionError='';
      config=feed.settings;recent=feed.recent;actions=feed.active_actions;connected=true;
      for(const [key] of native)if((key.startsWith('approval:')||key.startsWith('causes:'))&&!actions.includes(key))dismiss(key);
      const batches=new Map();
      for(const event of feed.events){
        if(!CATEGORIES.has(event.category))continue;
        const key=event.category==='complete'&&event.target?.job_id?'job:'+event.target.job_id:event.notice_key;
        if(!batches.has(key))batches.set(key,[]);batches.get(key).push(event);
      }
      // Several formats delivered by one generation task form one banner.
      // Independent tasks and decisions keep separate targets.
      let banners=0;
      for(const events of batches.values()){
        if(banners>=4)break;
        const event=events.length>1?{...events[0],title:`已完成 ${events.length} 份成果`,receipt_ids:events.map(row=>row.id),notice_keys:events.map(row=>row.notice_key),
          body:events[0].body.split('\n')[0]+'\n'+events.map(row=>row.body.split('\n').slice(1).join(' ')).join('\n')}:events[0];
        const status=show(event);if(status==='sent')banners++;
        for(const row of events){remember(row.notice_key,status);pendingReceipts.set(row.id,status);}
      }
      await flushReceipts();publish();
    }catch(error){connected=false;connectionError=String(error?.message||error).slice(0,400);fail(error);}finally{busy=false;}
  }
  async function open(id){
    const event=[...localHistory.values(),...recent].find(row=>row.id===id);
    if(!event)throw new Error('通知已过期，请在项目中查看');
    await showWindow(safeTarget(event.target));return true;
  }
  function local(event){
    const key=event.notice_key;if(localHistory.has(key)||stopped)return;
    event={...event,id:key,created_at:new Date().toISOString(),status:'local'};
    localHistory.set(key,event);while(localHistory.size>20)localHistory.delete(localHistory.keys().next().value);
    show(event);publish();
  }
  function update(state){
    if(!['available','downloaded'].includes(state.status)||!state.candidate?.version)return;
    local({notice_key:'update:'+state.status+':'+state.candidate.version,category:'update',target:{view:'settings',settings_section:'system'},
      title:state.status==='downloaded'?'更新已下载，等待你安装':'发现新版本 '+state.candidate.version,
      body:state.status==='downloaded'?'点击查看更新并选择何时重启安装。':'点击查看版本说明与下载选项。'});
  }
  function backendStopped(){local({notice_key:'backend-stopped',category:'failure',title:'本机学习服务意外停止',
    body:'当前任务无法继续，请重新打开 StudyForge。已保存的资料和成果仍保留。',target:{view:'settings',settings_section:'system'}});}
  async function test(){
    await poll();
    // A user can save and immediately press Test while the timer poll is still
    // finishing. Read the latest preferences, rather than using that old poll.
    config=(await readFeed()).settings;
    if(!config.desktop_notifications_enabled)throw new Error('请先启用并保存 Windows 桌面通知');
    const status=show({notice_key:'test:'+Date.now(),category:'complete',title:'Windows 桌面通知测试',
      body:'如果你看到此提醒，桌面通知已接通。点击可回到 StudyForge 的通知设置。',target:{view:'settings',settings_section:'notifications'}},{test:true});
    if(status==='failed')throw new Error(lastError||'Windows 通知发送失败');return snapshot();
  }
  function start(){if(timer||stopped)return;const first=poll();timer=setInterval(poll,interval);timer.unref();return first;}
  function dispose(){stopped=true;clearInterval(timer);for(const key of [...native.keys()])dismiss(key);}
  return {start,poll,snapshot,open,test,update,backendStopped,dispose};
}

function registerNotificationHandlers(ipcMain,origin,getWindow,manager){
  for(const [channel,callback] of [
    ['studyforge:notification-status',()=>manager.snapshot()],
    ['studyforge:notification-test',()=>manager.test()],
    ['studyforge:notification-open',id=>{if(!['string','number'].includes(typeof id))throw new Error('通知标识无效');return manager.open(id);}]
  ])ipcMain.handle(channel,(event,value)=>{desktopCaller(event,origin,getWindow);return callback(value);});
}
module.exports={createNotificationManager,registerNotificationHandlers,safeTarget};
