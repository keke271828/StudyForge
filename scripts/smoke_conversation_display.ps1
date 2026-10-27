param([string]$UiScript='scripts/smoke_conversation_display_ui.js')
$ErrorActionPreference='Stop'
$sfRoot=Split-Path $PSScriptRoot -Parent
$sfReport=Join-Path $sfRoot ('build\conversation-display-'+[guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($sfReport)|Out-Null
$sfNames=@('STUDYFORGE_DATA_DIR','STUDYFORGE_DISPLAY_CASE','PYTHONUTF8')
$sfPrevious=@{}
foreach($sfName in $sfNames){$sfPrevious[$sfName]=[Environment]::GetEnvironmentVariable($sfName,'Process')}
$sfServer=$null;$sfUi=$null
try{
  $env:STUDYFORGE_DATA_DIR=Join-Path $sfReport 'data'
  $env:STUDYFORGE_DISPLAY_CASE=Join-Path $sfReport 'case.json'
  $env:PYTHONUTF8='1'
  $sfPython=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  $sfServer=Start-Process -FilePath $sfPython -ArgumentList '-m scripts.smoke_conversation_display' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReport 'server.log') -RedirectStandardError (Join-Path $sfReport 'server-error.log')
  $sfReady=$false;$sfDeadline=[DateTime]::UtcNow.AddSeconds(30)
  while([DateTime]::UtcNow -lt $sfDeadline){
    if($sfServer.HasExited){throw (Get-Content -LiteralPath (Join-Path $sfReport 'server-error.log') -Raw -Encoding UTF8)}
    if(Test-Path -LiteralPath $env:STUDYFORGE_DISPLAY_CASE){
      $sfCase=Get-Content -LiteralPath $env:STUDYFORGE_DISPLAY_CASE -Raw -Encoding UTF8|ConvertFrom-Json
      try{Invoke-RestMethod -Uri ($sfCase.url+'/api/health') -TimeoutSec 1|Out-Null;$sfReady=$true;break}catch{}
    }
    Start-Sleep -Milliseconds 150
  }
  if(-not $sfReady){throw "Display server startup timeout: $sfReport"}
  $sfUi=Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') -ArgumentList $UiScript -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReport 'ui.log') -RedirectStandardError (Join-Path $sfReport 'ui-error.log')
  $null=$sfUi.Handle
  if(-not $sfUi.WaitForExit(120000)){throw "Display UI timeout: $sfReport"}
  $sfUi.Refresh()
  if($sfUi.ExitCode -ne 0){throw ((Get-Content -LiteralPath (Join-Path $sfReport 'ui-error.log') -Raw -Encoding UTF8)+"`n$sfReport")}
  if(-not (Test-Path -LiteralPath (Join-Path $sfReport 'result.json'))){throw ((Get-Content -LiteralPath (Join-Path $sfReport 'ui-error.log') -Raw -Encoding UTF8)+"`nDisplay UI did not finish: $sfReport")}
  Get-Content -LiteralPath (Join-Path $sfReport 'result.json') -Raw -Encoding UTF8
  Write-Output $sfReport
}finally{
  if($sfUi -and -not $sfUi.HasExited){Stop-Process -Id $sfUi.Id -Force}
  if($sfServer -and -not $sfServer.HasExited){Stop-Process -Id $sfServer.Id -Force}
  foreach($sfName in $sfNames){[Environment]::SetEnvironmentVariable($sfName,$sfPrevious[$sfName],'Process')}
}
