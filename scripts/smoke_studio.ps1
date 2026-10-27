$ErrorActionPreference='Stop'
$sfRoot=Split-Path $PSScriptRoot -Parent
$sfReportRoot=Join-Path $sfRoot ('build\studio-ui-'+[guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($sfReportRoot)|Out-Null
$sfVariables=@('STUDYFORGE_DATA_DIR','STUDYFORGE_MODELS_UI_CASE','PYTHONUTF8','CODEX_HOME')
$sfOriginal=@{}
foreach($sfName in $sfVariables){$sfOriginal[$sfName]=[System.Environment]::GetEnvironmentVariable($sfName,'Process')}
$sfServer=$null;$sfUi=$null
try{
  $env:STUDYFORGE_DATA_DIR=Join-Path $sfReportRoot 'data'
  $env:STUDYFORGE_MODELS_UI_CASE=Join-Path $sfReportRoot 'case.json'
  $env:CODEX_HOME=Join-Path $sfReportRoot 'codex-config'
  [System.IO.Directory]::CreateDirectory($env:CODEX_HOME)|Out-Null
  [System.IO.File]::WriteAllText((Join-Path $env:CODEX_HOME 'config.toml'),'model="gpt-6.1-sol"',[System.Text.UTF8Encoding]::new($false))
  $env:PYTHONUTF8='1'
  $sfPython=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  if(Test-Path -LiteralPath (Join-Path $sfRoot '.studyforge-python')){$sfPython=(Get-Content -LiteralPath (Join-Path $sfRoot '.studyforge-python') -Raw).Trim()}
  $sfServer=Start-Process -FilePath $sfPython -ArgumentList '-m scripts.smoke_model_selection' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReportRoot 'server.log') -RedirectStandardError (Join-Path $sfReportRoot 'server-error.log')
  $sfReady=$false;$sfDeadline=[DateTime]::UtcNow.AddSeconds(25)
  while([DateTime]::UtcNow -lt $sfDeadline){
    if($sfServer.HasExited){throw (Get-Content -LiteralPath (Join-Path $sfReportRoot 'server-error.log') -Raw)}
    if(Test-Path -LiteralPath $env:STUDYFORGE_MODELS_UI_CASE){
      $sfCase=Get-Content -LiteralPath $env:STUDYFORGE_MODELS_UI_CASE -Raw -Encoding UTF8|ConvertFrom-Json
      try{foreach($sfUrl in $sfCase.urls){Invoke-RestMethod -Uri ($sfUrl+'/api/health') -TimeoutSec 1|Out-Null};$sfReady=$true;break}catch{}
    }
    Start-Sleep -Milliseconds 200
  }
  if(-not $sfReady){throw 'Studio UI server startup timeout'}
  $sfUi=Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') -ArgumentList 'scripts/smoke_studio_ui.js' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReportRoot 'ui.log') -RedirectStandardError (Join-Path $sfReportRoot 'ui-error.log')
  if(-not $sfUi.WaitForExit(50000)){throw "Studio UI timeout: $sfReportRoot"}
  if($sfUi.ExitCode -ne 0){throw ((Get-Content -LiteralPath (Join-Path $sfReportRoot 'ui-error.log') -Raw)+"`n$sfReportRoot")}
  Get-Content -LiteralPath (Join-Path $sfReportRoot 'result.json') -Raw -Encoding UTF8
  Write-Output $sfReportRoot
}finally{
  if($sfUi -and -not $sfUi.HasExited){Stop-Process -Id $sfUi.Id -Force}
  if($sfServer -and -not $sfServer.HasExited){Stop-Process -Id $sfServer.Id -Force}
  foreach($sfName in $sfVariables){[System.Environment]::SetEnvironmentVariable($sfName,$sfOriginal[$sfName],'Process')}
}
