$ErrorActionPreference='Stop'
$sfRoot=Split-Path $PSScriptRoot -Parent
$sfReport=Join-Path $sfRoot ('build\homework-ui-'+[guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($sfReport)|Out-Null
$sfNames=@('STUDYFORGE_DATA_DIR','STUDYFORGE_HOMEWORK_CASE','STUDYFORGE_HOMEWORK_PHASE','PYTHONUTF8')
$sfPrevious=@{}
foreach($sfName in $sfNames){$sfPrevious[$sfName]=[Environment]::GetEnvironmentVariable($sfName,'Process')}
$sfServer=$null;$sfUi=$null
try{
  $env:STUDYFORGE_DATA_DIR=Join-Path $sfReport 'data'
  $env:STUDYFORGE_HOMEWORK_CASE=Join-Path $sfReport 'case.json'
  $env:PYTHONUTF8='1'
  $sfPython=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  foreach($sfPhase in @('1','2')){
    $env:STUDYFORGE_HOMEWORK_PHASE=$sfPhase
    $sfBefore=if(Test-Path -LiteralPath $env:STUDYFORGE_HOMEWORK_CASE){(Get-Item -LiteralPath $env:STUDYFORGE_HOMEWORK_CASE).LastWriteTimeUtc}else{[datetime]::MinValue}
    $sfServer=Start-Process -FilePath $sfPython -ArgumentList '-m scripts.smoke_homework' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReport "server-$sfPhase.log") -RedirectStandardError (Join-Path $sfReport "server-$sfPhase-error.log")
    $sfReady=$false;$sfDeadline=[DateTime]::UtcNow.AddSeconds(30)
    while([DateTime]::UtcNow -lt $sfDeadline){
      if($sfServer.HasExited){throw (Get-Content -LiteralPath (Join-Path $sfReport "server-$sfPhase-error.log") -Raw)}
      if((Test-Path -LiteralPath $env:STUDYFORGE_HOMEWORK_CASE) -and (Get-Item -LiteralPath $env:STUDYFORGE_HOMEWORK_CASE).LastWriteTimeUtc -gt $sfBefore){
        $sfCase=Get-Content -LiteralPath $env:STUDYFORGE_HOMEWORK_CASE -Raw -Encoding UTF8|ConvertFrom-Json
        try{Invoke-RestMethod -Uri ($sfCase.url+'/api/health') -TimeoutSec 1|Out-Null;$sfReady=$true;break}catch{}
      }
      Start-Sleep -Milliseconds 200
    }
    if(-not $sfReady){throw "Homework server startup timeout: $sfReport"}
    $sfUi=Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') -ArgumentList 'scripts/smoke_homework_ui.js' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfReport "ui-$sfPhase.log") -RedirectStandardError (Join-Path $sfReport "ui-$sfPhase-error.log")
    $null=$sfUi.Handle
    if(-not $sfUi.WaitForExit(90000)){throw "Homework UI timeout: $sfReport"}
    $sfUi.Refresh()
    if($sfUi.ExitCode -ne 0){throw ((Get-Content -LiteralPath (Join-Path $sfReport "ui-$sfPhase-error.log") -Raw)+"`n$sfReport")}
    Stop-Process -Id $sfServer.Id -Force
    $sfServer=$null
  }
  Get-Content -LiteralPath (Join-Path $sfReport 'result.json') -Raw -Encoding UTF8
  Write-Output $sfReport
}finally{
  if($sfUi -and -not $sfUi.HasExited){Stop-Process -Id $sfUi.Id -Force}
  if($sfServer -and -not $sfServer.HasExited){Stop-Process -Id $sfServer.Id -Force}
  foreach($sfName in $sfNames){[Environment]::SetEnvironmentVariable($sfName,$sfPrevious[$sfName],'Process')}
}
