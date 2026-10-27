$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
$pythonPath = 'C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe'
$electronPath = Join-Path $repoPath 'node_modules/electron/dist/electron.exe'
$runPath = Join-Path $repoPath ('build/user-guide-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runPath | Out-Null
$env:STUDYFORGE_MOBILE_CASE = Join-Path $runPath 'case.json'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $repoPath
$fixture = $null
try {
  $fixture = Start-Process -FilePath $pythonPath -ArgumentList @('-u', 'scripts/smoke_mobile.py') -WorkingDirectory $repoPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runPath 'server.log') -RedirectStandardError (Join-Path $runPath 'server-error.log')
  for ($index=0; $index -lt 240; $index++) {
    if (Test-Path -LiteralPath $env:STUDYFORGE_MOBILE_CASE) { break }
    if ($fixture.HasExited) { throw 'Guide fixture exited before startup; inspect server-error.log' }
    Start-Sleep -Milliseconds 200
  }
  if (-not (Test-Path -LiteralPath $env:STUDYFORGE_MOBILE_CASE)) { throw 'Guide fixture did not start' }
  $uiProcess = Start-Process -FilePath $electronPath -ArgumentList @('scripts/smoke_user_guide_ui.js') -WorkingDirectory $repoPath -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $runPath 'ui.log') -RedirectStandardError (Join-Path $runPath 'ui-error.log')
  Get-Content -LiteralPath (Join-Path $runPath 'ui.log')
  if ($uiProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $runPath 'ui-report.json'))) {
    Get-Content -LiteralPath (Join-Path $runPath 'ui-error.log')
    throw ('User guide check failed: ' + $runPath)
  }
  Write-Output ('USER_GUIDE_CHECK_PASS ' + $runPath)
} finally {
  if ($fixture -and -not $fixture.HasExited) { Stop-Process -Id $fixture.Id -ErrorAction SilentlyContinue }
}
