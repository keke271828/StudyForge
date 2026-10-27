$ErrorActionPreference='Stop'
$sfRoot=Split-Path $PSScriptRoot -Parent
$sfReportRoot=Join-Path $sfRoot ('build\pause-workflows-ui-'+[guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($sfReportRoot)|Out-Null
$sfNames=@('STUDYFORGE_DATA_DIR','STUDYFORGE_PAUSE_CASE','STUDYFORGE_PAUSE_PHASE','PYTHONUTF8')
$sfOld=@{}
foreach($sfName in $sfNames){$sfOld[$sfName]=[System.Environment]::GetEnvironmentVariable($sfName,'Process')}
$sfServer=$null;$sfUi=$null
try{
  $env:STUDYFORGE_DATA_DIR=Join-Path $sfReportRoot 'data'
  $env:STUDYFORGE_PAUSE_CASE=Join-Path $sfReportRoot 'case.json'
  $env:PYTHONUTF8='1'
  $sfPython=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  if(Test-Path -LiteralPath (Join-Path $sfRoot '.studyforge-python')){$sfPython=(Get-Content -LiteralPath (Join-Path $sfRoot '.studyforge-python') -Raw).Trim()}
  foreach($sfPhase in @('1','2')){
    $env:STUDYFORGE_PAUSE_PHASE=$sfPhase
    $sfBefore=if(Test-Path -LiteralPath $env:STUDYFORGE_PAUSE_CASE){(Get-Item -LiteralPath $env:STUDYFORGE_PAUSE_CASE).LastWriteTimeUtc}else{[datetime]::MinValue}
    $sfServer=Start-Process -FilePath $sfPython -ArgumentList '-m scripts.smoke_pause_workflows' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReportRoot "server-$sfPhase.log") -RedirectStandardError (Join-Path $sfReportRoot "server-$sfPhase-error.log")
    $sfReady=$false;$sfDeadline=[DateTime]::UtcNow.AddSeconds(25)
    while([DateTime]::UtcNow -lt $sfDeadline){
      if($sfServer.HasExited){throw (Get-Content -LiteralPath (Join-Path $sfReportRoot "server-$sfPhase-error.log") -Raw)}
      if((Test-Path -LiteralPath $env:STUDYFORGE_PAUSE_CASE) -and (Get-Item -LiteralPath $env:STUDYFORGE_PAUSE_CASE).LastWriteTimeUtc -gt $sfBefore){
        $sfCase=Get-Content -LiteralPath $env:STUDYFORGE_PAUSE_CASE -Raw -Encoding UTF8|ConvertFrom-Json
        try{Invoke-RestMethod -Uri ($sfCase.url+'/api/health') -TimeoutSec 1|Out-Null;$sfReady=$true;break}catch{}
      }
      Start-Sleep -Milliseconds 200
    }
    if(-not $sfReady){throw "Pause fixture startup timeout: $sfReportRoot"}
    $sfUi=Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') -ArgumentList 'scripts/smoke_pause_workflows_ui.js' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReportRoot "ui-$sfPhase.log") -RedirectStandardError (Join-Path $sfReportRoot "ui-$sfPhase-error.log")
    $null=$sfUi.Handle
    if(-not $sfUi.WaitForExit(55000)){throw "Pause UI timeout: $sfReportRoot"}
    $sfUi.Refresh()
    if($sfUi.ExitCode -ne 0){throw ((Get-Content -LiteralPath (Join-Path $sfReportRoot "ui-$sfPhase-error.log") -Raw)+"`n$sfReportRoot")}
    Stop-Process -Id $sfServer.Id -Force;$sfServer=$null
  }
  Get-Content -LiteralPath (Join-Path $sfReportRoot 'result.json') -Raw -Encoding UTF8
  Write-Output $sfReportRoot
}finally{
  if($sfUi -and -not $sfUi.HasExited){Stop-Process -Id $sfUi.Id -Force}
  if($sfServer -and -not $sfServer.HasExited){Stop-Process -Id $sfServer.Id -Force}
  foreach($sfName in $sfNames){[System.Environment]::SetEnvironmentVariable($sfName,$sfOld[$sfName],'Process')}
}
