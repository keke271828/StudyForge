$ErrorActionPreference = 'Stop'
$sfRoot = Split-Path $PSScriptRoot -Parent
$sfTestRoot = Join-Path $sfRoot ('build\updates-native-' + [guid]::NewGuid().ToString('N'))
$sfData = Join-Path $sfTestRoot 'data'
[System.IO.Directory]::CreateDirectory($sfData) | Out-Null
$sfVariables = @('STUDYFORGE_DATA_DIR','STUDYFORGE_SMOKE_REPORT','STUDYFORGE_SMOKE_TRAY','STUDYFORGE_TRAY_PHASE','STUDYFORGE_SMOKE_UPDATES')
$sfOriginal = @{}
foreach ($sfName in $sfVariables) { $sfOriginal[$sfName] = [System.Environment]::GetEnvironmentVariable($sfName,'Process') }
$sfProcess = $null
try {
  $env:STUDYFORGE_DATA_DIR=$sfData
  $env:STUDYFORGE_SMOKE_REPORT=Join-Path $sfTestRoot 'result.json'
  $env:STUDYFORGE_SMOKE_TRAY='1'
  $env:STUDYFORGE_TRAY_PHASE='1'
  $env:STUDYFORGE_SMOKE_UPDATES='1'
  $sfProcess=Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') `
    -ArgumentList ('"'+$sfRoot+'"') -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $sfTestRoot 'desktop.log') -RedirectStandardError (Join-Path $sfTestRoot 'desktop-error.log')
  if(-not $sfProcess.WaitForExit(50000)){throw "原生更新验收超时：$sfTestRoot"}
  $sfResult=Get-Content -LiteralPath $env:STUDYFORGE_SMOKE_REPORT -Raw -Encoding UTF8 | ConvertFrom-Json
  if(-not $sfResult.ok){throw ('原生更新验收失败：'+($sfResult | ConvertTo-Json -Depth 8 -Compress))}
  foreach($sfOwnPid in @($sfResult.backend_pid,$sfResult.child_pid)){
    $sfOwn=Get-Process -Id $sfOwnPid -ErrorAction SilentlyContinue
    if($sfOwn -and -not $sfOwn.WaitForExit(2500)){throw '安装替身执行后自己的后台未结束'}
  }
  $sfResult | ConvertTo-Json -Depth 8
}finally{
  if($sfProcess -and -not $sfProcess.HasExited){Stop-Process -Id $sfProcess.Id -Force}
  $sfPidFile=Join-Path $sfData 'tray-process-1.json'
  if(Test-Path -LiteralPath $sfPidFile){
    $sfPids=Get-Content -LiteralPath $sfPidFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach($sfOwnPid in @($sfPids.backend_pid,$sfPids.child_pid)){Stop-Process -Id $sfOwnPid -Force -ErrorAction SilentlyContinue}
  }
  foreach($sfName in $sfVariables){[System.Environment]::SetEnvironmentVariable($sfName,$sfOriginal[$sfName],'Process')}
}
