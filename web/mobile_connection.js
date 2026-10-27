(()=>{
  const byId=id=>document.getElementById(id),bridge=window.studyforgeDesktop;
  if(!bridge?.mobileStatus)return;
  const trigger=document.createElement('button');trigger.id='connectMobile';trigger.type='button';trigger.textContent='连接手机';trigger.title='局域网与跨网络连接';
  document.querySelector('.workspace-actions').prepend(trigger);
  const dialog=document.createElement('dialog');dialog.id='mobileConnectionDialog';dialog.className='mobile-connect-dialog';
  dialog.innerHTML=`<header><div><h2>把学习工作台带到手机</h2><small>电脑处理资料，手机专注阅读与交流</small></div><button type="button" id="closeMobileConnection">关闭</button></header>
    <div class="mobile-connect-body"><section id="mobileRuntimeUpdate" class="mobile-runtime-update" role="alert" hidden><h3>请先重新打开最新版软件</h3><p>这个窗口仍在使用旧版桌面窗口或学习服务；只刷新页面不会更新软件本身。旧地址已隐藏，避免连接到仍限制局域网的服务。</p><p>点击下面按钮保存并退出当前旧版，再双击项目文件夹中的「验收最新版.vbs」。重新打开后启用跨网络连接。</p><button id="exitOldMobileRuntime" type="button">保存并退出旧版</button><p id="oldMobileExitStatus"></p></section>
    <section class="mobile-private-connection"><div class="mobile-private-heading"><div><h3>固定网址，随时接着学</h3><p>电脑与手机各登录一次 Tailscale，之后换 Wi-Fi 或使用手机流量都用同一个私人地址。</p></div><span id="mobileTailscaleStatus" role="status">正在检测…</span></div><label class="setting-check"><input id="mobileUseTailscale" type="checkbox">同时启用 Tailscale 跨网络连接</label><p id="mobileTailscaleDetail" class="small-note"></p><div class="mobile-private-actions"><button id="setupMobileTailscale" type="button" title="启用固定连接、自动启动和长期记住设备；已有手机回复会停止">启用跨网络连接</button><button id="refreshMobileNetwork" type="button">重新检测</button><button id="installTailscaleWindows" type="button">电脑安装 / 登录说明</button><button id="installTailscaleAndroid" type="button">手机安装入口</button></div></section>
    <div class="mobile-connect-controls"><label>电脑连接地址<select id="mobileAddress"></select></label><label>连接端口<input id="mobilePort" type="number" min="1024" max="65535" value="18765"></label><button id="startMobileConnection" type="button">启用手机连接</button><button id="restartMobileConnection" type="button" title="切换网络或连接方式后刷新地址；正在进行的手机回复会停止" hidden>重新开启连接</button><button id="stopMobileConnection" type="button" hidden>停止连接</button></div>
    <div class="mobile-connect-preferences"><label class="setting-check"><input id="mobileAutoStart" type="checkbox">打开软件时自动启用手机连接</label><label>记住设备<select id="mobileRememberDays"><option value="365">长期记住 · 每次使用自动续期</option><option value="90">90 天 · 自动续期</option><option value="30">30 天 · 自动续期</option></select></label><button id="saveMobilePreferences" type="button">保存连接偏好</button></div><p class="small-note">已配对的同一浏览器无需每次扫码。固定网址可添加到手机主屏幕；清除浏览器数据或撤销设备后需要重新配对。</p><p id="mobileConnectionStatus" class="mobile-connect-status" role="status">局域网或已登录的 Tailscale 均可连接。</p>
    <section class="mobile-connect-diagnostics"><div class="mobile-connect-diagnostic-tools"><button id="diagnoseMobileConnection" type="button">连接自检</button><label>手机 Wi-Fi IP（可选）<input id="mobilePhoneIP" inputmode="decimal" maxlength="15" placeholder="在手机 Wi-Fi 详情中查看"></label></div><div id="mobileDiagnosticResult" role="status" hidden></div></section>
    <div id="mobileConnectionDetails" class="mobile-connect-grid" hidden>
      <div class="mobile-connect-qr"><img id="mobileConnectionQR" alt="手机连接二维码"><div id="mobilePairingCode" class="mobile-pairing-code"></div><small id="mobilePairingExpiry"></small><p><button id="refreshMobilePairing" type="button">刷新配对码</button></p><button id="copyMobileAddress" type="button">复制连接地址</button></div>
      <div><ol class="mobile-connect-steps">
        <li><strong>第一次连接：先在手机安装电脑导出的证书</strong><br>点击“导出连接证书”，传到手机；安卓设置中找到“安装证书 → CA 证书”。已安装同一电脑导出的证书无需因换网重装。<br><button id="exportMobileCertificate" type="button">导出连接证书</button></li>
        <li><strong>首次配对，以后直接打开</strong><br><span id="mobileConnectionURL"></span><br>填写配对码和设备名称，在此面板确认设备。之后使用同一入口、同一浏览器，无需重复扫码。</li>
        <li><strong>添加手机主屏幕入口</strong><br>手机输入区“⋯”→“添加手机主屏幕入口”。随时上传文件、交流和下载成果；专注模式只保留对话与输入区。</li>
      </ol><details><summary>连接信息与故障检查</summary><p id="mobileCertificateFingerprint" class="mobile-connect-fingerprint"></p><p class="small-note">跨网络连接需要两端 Tailscale 开启并登录同一账号；Wi-Fi 直连需使用当前局域网地址。电脑应开机且未睡眠，软件在后台运行。可用上方连接自检核对服务与证书。首次改用新地址需配对，之后保存固定网址。</p></details></div>
    </div>
    <h3>配对请求与已连接设备</h3><div id="mobileDeviceList" class="mobile-device-list"></div></div>`;
  document.body.append(dialog);
  let current=null,busy=false,qrKey='',poll=null,diagnosticEpoch=0,diagnosedFor='',settingsDirty=false,addressManual=false;
  const labels={pending:'等待你确认',approved:'等待手机完成配对',active:'已连接',revoked:'已撤销',denied:'已拒绝',expired:'已过期'};
  function notice(value){byId('mobileConnectionStatus').textContent=value;}
  function renderDevices(rows){
    const list=byId('mobileDeviceList');list.replaceChildren();
    if(!rows.length){const p=document.createElement('p');p.className='small-note';p.textContent='尚未连接手机。扫码后，确认请求会出现在这里。';list.append(p);return;}
    for(const row of rows){
      const item=document.createElement('div');item.className='mobile-device-row';item.dataset.pending=String(row.status==='pending');
      const info=document.createElement('div'),name=document.createElement('strong'),status=document.createElement('div');name.textContent=row.name;status.textContent=(labels[row.status]||row.status)+(row.status==='active'?' · 自动记住至 '+new Date(row.expires_at).toLocaleDateString():'');status.className='small-note';info.append(name,status);
      const controls=document.createElement('div');
      if(row.status==='pending')for(const [text,approved] of [['允许连接',true],['拒绝',false]]){const button=document.createElement('button');button.textContent=text;button.onclick=()=>action(()=>bridge.mobileDecide({id:row.id,approved}));controls.append(button);}
      else if(['active','approved'].includes(row.status)){const button=document.createElement('button');button.textContent='撤销连接';button.onclick=()=>action(()=>bridge.mobileRevoke(row.id));controls.append(button);}
      item.append(info,controls);list.append(item);
    }
  }
  async function render(value){
    current=value;const select=byId('mobileAddress'),old=select.value;
    const supported=value.gateway_version>=2&&Boolean(bridge.mobileNetworkRefresh&&bridge.mobilePreferences);
    byId('mobileRuntimeUpdate').hidden=supported;
    for(const id of ['startMobileConnection','restartMobileConnection','setupMobileTailscale','refreshMobileNetwork','saveMobilePreferences','diagnoseMobileConnection'])byId(id).disabled=!supported;
    if(!supported){
      qrKey='';byId('mobileConnectionDetails').hidden=true;byId('mobileConnectionQR').removeAttribute('src');byId('mobileConnectionURL').textContent='';
      byId('mobileTailscaleStatus').textContent='旧版后台';byId('mobileTailscaleDetail').textContent='先保存并退出旧版，再打开最新版。';
      notice('当前学习服务版本还不支持跨网络连接，请使用上方“保存并退出旧版”。');return;
    }
    if(value.interfaces){select.replaceChildren();for(const item of value.interfaces){const option=document.createElement('option');option.value=item.address;option.dataset.kind=item.kind||'lan';option.textContent=item.name+' · '+item.address;select.append(option);}if(!addressManual&&value.preferred_address&&[...select.options].some(item=>item.value===value.preferred_address))select.value=value.preferred_address;else if([...select.options].some(item=>item.value===old))select.value=old;}
    if(diagnosedFor&&diagnosedFor!==select.value+'|'+value.port){diagnosticEpoch++;diagnosedFor='';byId('mobileDiagnosticResult').hidden=true;}
    if(!settingsDirty){byId('mobilePort').value=value.port;byId('mobileAutoStart').checked=value.auto_start;byId('mobileUseTailscale').checked=value.enable_tailscale===true;byId('mobileRememberDays').value=String(value.remember_days||365);}
    const tailnet=value.tailscale||{};byId('mobileTailscaleStatus').textContent=tailnet.connected?'Tailscale 已连接':tailnet.installed?'等待登录 / 连接':'尚未安装';byId('mobileTailscaleStatus').dataset.ready=String(Boolean(tailnet.connected));
    byId('mobileTailscaleDetail').textContent=(tailnet.message||'安装并登录后点“重新检测”。')+(tailnet.connected?' · '+(tailnet.addresses||[]).join('、'):'')+(value.enable_tailscale&&!tailnet.connected?'；当前仍可用局域网。登录后固定地址会自动接入。':'')+(tailnet.health?.length?' · '+tailnet.health.join('；'):'')+(value.network_error?' · 自动恢复提示：'+value.network_error:'');
    select.disabled=busy;byId('mobilePort').disabled=value.running||busy;
    byId('startMobileConnection').hidden=value.running;byId('restartMobileConnection').hidden=!value.running;byId('stopMobileConnection').hidden=!value.running;byId('mobileConnectionDetails').hidden=!value.running;
    notice(value.error|| (value.running?(value.preferred_address?'跨网络连接已启用。手机开启同账号的 Tailscale 后，可在不同网络直接打开；已配对设备无需重复扫码。':'同一 Wi-Fi 连接已启用。关闭电脑窗口后，托盘后台仍可提供连接；跨网络请启用跨网络连接。'):'首次开启后确认手机；以后可从手机主屏幕直接进入。'));
    renderDevices(value.devices||[]);
    if(value.running){
      const address=select.value||value.addresses[0],key=address+'|'+value.pairing_code;
      if(!value.addresses.includes(address)){
        qrKey='';byId('mobileConnectionQR').removeAttribute('src');byId('mobileConnectionQR').hidden=true;
        byId('mobileConnectionURL').textContent='网络已切换。请点击“重新开启连接”，再使用新地址。';
        byId('mobilePairingCode').textContent='需刷新连接';byId('mobilePairingExpiry').textContent='旧地址已不适用';
        notice('检测到当前网卡地址变化，请重新开启手机连接；不继续显示旧二维码。');return;
      }
      byId('mobileConnectionQR').hidden=false;
      byId('mobileConnectionURL').textContent='https://'+address+':'+value.port+'/';
      byId('mobilePairingCode').textContent=value.pairing_code||'等待配对';
      byId('mobilePairingExpiry').textContent=value.pairing_code?'配对码 '+value.pairing_seconds+' 秒后过期':'刷新配对码以连接另一台手机';
      byId('mobileCertificateFingerprint').textContent=value.fingerprint||'';
      if(key!==qrKey){const qr=await bridge.mobileQR(address);if(current!==value||select.value!==address)return;byId('mobileConnectionQR').src='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(qr.svg)));qrKey=key;}
    }
  }
  async function refresh(){if(busy||!dialog.open)return;try{await render(await bridge.mobileStatus());}catch(failure){notice(failure.message);}}
  async function action(operation){if(busy)return;diagnosticEpoch++;diagnosedFor='';byId('mobileDiagnosticResult').hidden=true;busy=true;try{await operation();qrKey='';busy=false;await refresh();}catch(failure){notice(failure.message);}finally{busy=false;}}
  trigger.onclick=()=>{dialog.showModal();refresh();poll=setInterval(refresh,2500);};
  byId('closeMobileConnection').onclick=()=>dialog.close();dialog.onclose=()=>{clearInterval(poll);poll=null;};
  byId('exitOldMobileRuntime').onclick=async()=>{
    const button=byId('exitOldMobileRuntime'),status=byId('oldMobileExitStatus');button.disabled=true;
    try{if(!bridge.quit)throw new Error('请从 Windows 通知区托盘右键选择“退出 StudyForge”。');await bridge.quit();status.textContent='正在保存并退出；关闭后双击“验收最新版.vbs”。';}
    catch(failure){status.textContent=failure.message;button.disabled=false;}
  };
  function options(){return {address:byId('mobileAddress').value,port:Number(byId('mobilePort').value),auto_start:byId('mobileAutoStart').checked,enable_tailscale:byId('mobileUseTailscale').checked,remember_days:Number(byId('mobileRememberDays').value)};}
  async function start(optionsValue){await bridge.mobileStart(optionsValue);settingsDirty=false;addressManual=false;}
  byId('startMobileConnection').onclick=()=>action(()=>start(options()));
  byId('restartMobileConnection').onclick=()=>{
    const value=options();action(async()=>{await bridge.mobileStop();await start(value);});
  };
  byId('stopMobileConnection').onclick=()=>action(()=>bridge.mobileStop());
  byId('refreshMobilePairing').onclick=()=>action(()=>bridge.mobilePairing());
  byId('mobileAddress').onchange=()=>{addressManual=true;if(byId('mobileAddress').selectedOptions[0]?.dataset.kind==='tailscale'){byId('mobileUseTailscale').checked=true;settingsDirty=true;}diagnosticEpoch++;byId('mobileDiagnosticResult').hidden=true;qrKey='';if(current)render(current).catch(failure=>notice(failure.message));};
  for(const id of ['mobileAutoStart','mobileRememberDays','mobileUseTailscale','mobilePort'])byId(id).onchange=()=>{settingsDirty=true;};
  byId('saveMobilePreferences').onclick=()=>action(async()=>{await bridge.mobilePreferences({auto_start:byId('mobileAutoStart').checked,remember_days:Number(byId('mobileRememberDays').value)});if(byId('mobileUseTailscale').checked===current.enable_tailscale)settingsDirty=false;});
  byId('refreshMobileNetwork').onclick=()=>action(async()=>{const value=await bridge.mobileNetworkRefresh();await render(value);});
  byId('setupMobileTailscale').onclick=()=>{
    if(!current?.tailscale?.connected)return notice('请先让电脑和手机登录同一 Tailscale 账号，然后点“重新检测”。');
    byId('mobileUseTailscale').checked=true;byId('mobileAutoStart').checked=true;byId('mobileRememberDays').value='365';settingsDirty=true;
    const value=options();action(async()=>{if(current?.running)await bridge.mobileStop();await start(value);});
  };
  for(const [id,kind] of [['installTailscaleWindows','windows'],['installTailscaleAndroid','android']])byId(id).onclick=async()=>{try{await bridge.mobileTailscaleHelp(kind);}catch(failure){notice(failure.message);}};
  byId('copyMobileAddress').onclick=async()=>{try{await bridge.copyText(byId('mobileConnectionURL').textContent);notice('连接地址已复制，可发送到手机。');}catch(failure){notice(failure.message);}};
  byId('exportMobileCertificate').onclick=async()=>{try{const result=await bridge.mobileCertificate();if(result.saved)notice('连接证书已导出：'+result.path+'。传到手机安装后再扫码。');}catch(failure){notice(failure.message);}};
  byId('diagnoseMobileConnection').onclick=async()=>{
    const button=byId('diagnoseMobileConnection'),result=byId('mobileDiagnosticResult'),token=++diagnosticEpoch;
    if(!bridge.mobileDiagnostics)return notice('请退出旧版，从“验收最新版”重新打开后使用连接自检。');
    button.disabled=true;button.textContent='正在检查…';
    try{
      const report=await bridge.mobileDiagnostics({address:byId('mobileAddress').value,phone_ip:byId('mobilePhoneIP').value});
      if(token!==diagnosticEpoch)return;diagnosedFor=byId('mobileAddress').value+'|'+current.port;result.replaceChildren();result.hidden=false;
      for(const check of report.checks){
        const card=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('p');
        card.className='mobile-diagnostic-check';card.dataset.level=check.level;title.textContent=check.title;detail.textContent=check.detail;
        card.append(title,detail);result.append(card);
      }
      for(const text of report.tips){const tip=document.createElement('p');tip.className='mobile-diagnostic-tip';tip.textContent=text;result.append(tip);}
    }catch(failure){notice(failure.message);}finally{button.disabled=false;button.textContent='连接自检';}
  };
})();
