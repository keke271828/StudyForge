/* Native Windows preferences stay local to the owner desktop window. */
(()=>{
  const host=document.getElementById('desktopControls');if(!host)return;
  const card=document.createElement('section');card.className='desktop-startup-card';
  card.innerHTML=`<div><span class="eyebrow">READY WHEN YOU ARE</span><h4>开机自动启动</h4><p>登录 Windows 后自动准备学习工作台和已启用的手机连接。</p></div>
    <label class="desktop-startup-choice"><input id="desktopAutoStart" type="checkbox"><span><strong>开机自动启动 StudyForge</strong><small>只为当前 Windows 用户登记，可随时关闭。</small></span></label>
    <label class="desktop-startup-choice"><input id="desktopStartHidden" type="checkbox" checked><span><strong>启动后隐藏到托盘</strong><small>推荐：后台准备，不打断桌面；手动打开仍显示窗口。</small></span></label>
    <div class="desktop-startup-actions"><button id="saveDesktopStartup" type="button">保存启动设置</button><button id="refreshDesktopStartup" type="button">检查实际状态</button></div>
    <p id="desktopStartupStatus" class="small-note" role="status"></p>`;
  host.append(card);
  const $=id=>document.getElementById(id),bridge=window.studyforgeDesktop;
  let busy=false,dirty=false,available=false,revision=0;
  function controls(){
    $('desktopAutoStart').disabled=busy||!available;
    $('desktopStartHidden').disabled=busy||!available||!$('desktopAutoStart').checked;
    $('saveDesktopStartup').disabled=busy||!available;$('refreshDesktopStartup').disabled=busy||!available;
  }
  function render(value){
    available=Boolean(value.available);
    if(!dirty){$('desktopAutoStart').checked=value.enabled;$('desktopStartHidden').checked=value.start_hidden;}
    controls();card.dataset.state=value.blocked_by_windows?'warning':value.enabled?'enabled':'disabled';
    $('desktopStartupStatus').textContent=value.message+(value.source_build?' 当前从源码运行；请保留项目文件夹。':'');
  }
  async function refresh(){
    if(busy)return;
    const current=++revision;
    if(!bridge?.startupStatus){available=false;controls();$('desktopStartupStatus').textContent='请通过 StudyForge 桌面应用设置 Windows 开机启动；若已在桌面应用中，请从托盘完全退出后重新打开。';return;}
    try{const value=await bridge.startupStatus();if(current===revision&&!busy)render(value);}
    catch(error){if(current===revision&&!busy)$('desktopStartupStatus').textContent='无法核对 Windows 开机启动设置：'+error.message;}
  }
  for(const id of ['desktopAutoStart','desktopStartHidden'])$(id).onchange=()=>{dirty=true;controls();};
  $('saveDesktopStartup').onclick=async()=>{
    if(busy||!available)return;++revision;busy=true;controls();$('desktopStartupStatus').textContent='正在登记并核对 Windows 开机启动设置…';
    try{const value=await bridge.saveStartupSettings({enabled:$('desktopAutoStart').checked,start_hidden:$('desktopStartHidden').checked});dirty=false;render(value);window.toast?.('启动设置已保存，并已核对 Windows 状态');}
    catch(error){$('desktopStartupStatus').textContent=error.message;}
    finally{busy=false;controls();}
  };
  $('refreshDesktopStartup').onclick=()=>{dirty=false;refresh();};
  window.studyforgeStartup={refresh};controls();refresh();
})();
