const {test}=require('node:test');
const assert=require('node:assert/strict');
const {diagnose,ipv4,sameSubnet}=require('../desktop/mobile_diagnostics');
const defaults=()=>({status:{running:true,port:18765,addresses:['10.64.60.164']},
  interfaces:[{name:'WLAN',address:'10.64.60.164',netmask:'255.255.255.0'}],
  address:'10.64.60.164',certificate:{data:Buffer.from('mock ca').toString('base64')},
  probe:async()=>({status:200,mobilePage:true})});

test('IPv4 parsing and actual adapter subnet mask',()=>{
  assert.equal(ipv4('256.1.2.3'),null);assert.equal(ipv4('10.1.2'),null);
  assert.equal(sameSubnet('10.139.24.202','10.139.50.3','255.255.0.0'),true);
  assert.equal(sameSubnet('10.139.24.202','10.64.60.43','255.255.0.0'),false);
  assert.equal(sameSubnet('10.1.2.3','invalid','255.255.255.0'),null);
});
test('probe only a current local adapter address',async()=>{
  let calls=0;
  await assert.rejects(diagnose({...defaults(),address:'8.8.8.8',probe:async()=>{calls++;}}));
  assert.equal(calls,0);
});
test('stopped service does not probe or require a certificate',async()=>{
  const options=defaults();options.status.running=false;options.certificate=null;
  options.probe=async()=>{throw new Error('must not probe');};
  const result=await diagnose(options);assert.equal(result.checks[0].level,'error');
});
test('network change invalidates the old URL and requests restart without probing',async()=>{
  const options=defaults();options.status.addresses=['10.139.24.202'];
  options.probe=async()=>{throw new Error('must not probe an unconfigured address');};
  const result=await diagnose(options);
  assert.ok(result.checks.some(row=>row.title==='网络地址已改变'&&row.level==='error'));
  assert.ok(result.tips.join('').includes('旧二维码'));
});
test('trusted local response never claims the phone path is verified',async()=>{
  const options=defaults();options.phoneIP='10.64.60.43';options.network={
    networks:[{InterfaceAlias:'WLAN',category:'Public'}],firewalls:[{Name:'Public',enabled:false}]};
  const result=await diagnose(options);assert.equal(result.phone_path_verified,false);
  assert.ok(result.checks.some(row=>row.title==='电脑上的加密连接与证书'&&row.level==='ok'));
  assert.ok(result.checks.some(row=>row.title==='Windows 网络与防火墙'&&row.detail.includes('未启用')));
  assert.ok(result.checks.some(row=>row.title==='手机和电脑是否在同一网络'&&row.detail.includes('仍需用手机试开')));
});
test('unexpected response and TLS error remain explicit errors',async()=>{
  const wrong=await diagnose({...defaults(),probe:async()=>({status:200,mobilePage:false})});
  assert.equal(wrong.checks[1].level,'error');
  const failed=await diagnose({...defaults(),probe:async()=>{throw Object.assign(new Error('mismatch'),{code:'ERR_TLS_CERT_ALTNAME_INVALID'});}});
  assert.equal(failed.checks[1].level,'error');assert.ok(failed.checks[1].detail.includes('ERR_TLS'));
});
test('bad phone address and bad port fail before network probing',async()=>{
  await assert.rejects(diagnose({...defaults(),phoneIP:'<script>'}));
  await assert.rejects(diagnose({...defaults(),status:{...defaults().status,port:70000}}));
});
test('private fixed address is recognized as the intended connection rather than an unwanted VPN',async()=>{
  const options=defaults();options.address='100.83.42.9';options.phoneIP='192.168.1.20';
  options.interfaces=[{name:'Tailscale · 固定私人地址',address:options.address,netmask:'255.255.255.255',kind:'tailscale'}];
  options.status={...options.status,addresses:[options.address],enable_tailscale:true,tailscale:{connected:true}};
  const result=await diagnose(options);
  assert.ok(result.checks.some(row=>row.title==='跨网络连接'&&row.level==='ok'));
  assert.ok(!result.tips.join('').includes('请优先选择 Wi-Fi'));
  assert.ok(!result.checks.some(row=>row.title==='手机和电脑是否在同一网络'));
  assert.equal(result.phone_path_verified,false);
});
