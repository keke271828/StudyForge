$ErrorActionPreference = 'Stop'
$startupRepo = Split-Path $PSScriptRoot -Parent
$startupRun = Join-Path $startupRepo ('build\desktop-startup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $startupRun | Out-Null
$startupVariables = @('STUDYFORGE_DATA_DIR','STUDYFORGE_SMOKE_REPORT','STUDYFORGE_SMOKE_STARTUP','STUDYFORGE_SMOKE_TRAY')
$startupOriginal = @{}
foreach ($startupName in $startupVariables) { $startupOriginal[$startupName] = [Environment]::GetEnvironmentVariable($startupName, 'Process') }
$startupProcess = $null
try {
  $env:STUDYFORGE_DATA_DIR = Join-Path $startupRun 'data'
  $env:STUDYFORGE_SMOKE_REPORT = Join-Path $startupRun 'result.json'
  $env:STUDYFORGE_SMOKE_STARTUP = '1'
  $env:STUDYFORGE_SMOKE_TRAY = '0'
  $startupProcess = Start-Process -FilePath (Join-Path $startupRepo 'node_modules\electron\dist\electron.exe') -ArgumentList @(('"' + $startupRepo + '"'),'--studyforge-autostart','--studyforge-start-hidden') -WorkingDirectory $startupRepo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $startupRun 'desktop.log') -RedirectStandardError (Join-Path $startupRun 'desktop-error.log')
  if (-not $startupProcess.WaitForExit(90000)) { throw ('Startup check timed out: ' + $startupRun) }
  $startupResult = Get-Content -LiteralPath $env:STUDYFORGE_SMOKE_REPORT -Raw -Encoding utf8 | ConvertFrom-Json
  $startupResult | ConvertTo-Json -Depth 6
  if (-not $startupResult.ok) { throw ('Startup check failed: ' + $startupRun) }
  $startupEntry = 'StudyForge.Acceptance.' + (Split-Path $startupRun -Leaf)
  $startupNative = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $startupEntry -ErrorAction SilentlyContinue
  if ($startupNative) { throw 'Acceptance entry was not removed' }
  $startupBackend = Get-Process -Id $startupResult.backend_pid -ErrorAction SilentlyContinue
  if ($startupBackend -and -not $startupBackend.WaitForExit(5000)) { throw 'Acceptance backend did not exit' }
  Write-Output ('STARTUP_CHECK_PASS ' + $startupRun)
} finally {
  if ($startupProcess -and -not $startupProcess.HasExited) { Stop-Process -Id $startupProcess.Id -ErrorAction SilentlyContinue }
  # Own temporary value only. Never remove the user's StudyForge startup entry.
  $startupEntry = 'StudyForge.Acceptance.' + (Split-Path $startupRun -Leaf)
  Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $startupEntry -ErrorAction SilentlyContinue
  Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' -Name $startupEntry -ErrorAction SilentlyContinue
  foreach ($startupName in $startupVariables) { [Environment]::SetEnvironmentVariable($startupName,$startupOriginal[$startupName],'Process') }
}
