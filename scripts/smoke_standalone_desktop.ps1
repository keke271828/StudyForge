param([switch]$AcceptanceLauncher)
$ErrorActionPreference = 'Stop'
$sfRoot = Split-Path $PSScriptRoot -Parent
$sfTestRoot = Join-Path $sfRoot ('build\standalone-desktop-' + [guid]::NewGuid().ToString('N'))
$sfData = Join-Path $sfTestRoot 'data'
[System.IO.Directory]::CreateDirectory($sfData) | Out-Null
$sfReport = Join-Path $sfTestRoot 'result.json'
[System.IO.File]::WriteAllText((Join-Path $sfData 'settings.json'),
  '{"chat_provider":"deepseek","deepseek_model":"deepseek-flash","background_learning_enabled":false}', [System.Text.UTF8Encoding]::new($false))
$sfVariables = @('PATH','STUDYFORGE_DATA_DIR','STUDYFORGE_SMOKE_REPORT','STUDYFORGE_SMOKE_MODELS')
$sfOriginal = @{}
foreach ($sfName in $sfVariables) { $sfOriginal[$sfName] = [System.Environment]::GetEnvironmentVariable($sfName, 'Process') }
$sfProcess = $null
try {
  # Simulate a machine without the CLI while keeping unrelated local tools.
  $env:PATH = (($sfOriginal['PATH'] -split ';') | Where-Object {
    $sfEntry = $_.Trim('"')
    $sfEntry -and -not ((Test-Path -LiteralPath (Join-Path $sfEntry 'codex.exe')) -or
      (Test-Path -LiteralPath (Join-Path $sfEntry 'codex.cmd')) -or
      (Test-Path -LiteralPath (Join-Path $sfEntry 'codex')))
  }) -join ';'
  $env:STUDYFORGE_DATA_DIR = $sfData
  $env:STUDYFORGE_SMOKE_REPORT = $sfReport
  $env:STUDYFORGE_SMOKE_MODELS = '0'
  $sfLaunch = @{FilePath=(Join-Path $sfRoot 'node_modules\electron\dist\electron.exe');
    ArgumentList=('"' + $sfRoot + '"');WorkingDirectory=$sfRoot;WindowStyle='Hidden';PassThru=$true;
    RedirectStandardOutput=(Join-Path $sfTestRoot 'desktop.log');RedirectStandardError=(Join-Path $sfTestRoot 'desktop-error.log')}
  if ($AcceptanceLauncher) {
    $sfLaunch.FilePath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $sfLaunch.ArgumentList = '"' + (Join-Path $sfRoot '验收最新版.vbs') + '"'
  }
  $sfProcess = Start-Process @sfLaunch
  if (-not $sfProcess.WaitForExit(45000)) { throw '独立桌面启动自检超时' }
  if ($AcceptanceLauncher) {
    $sfDeadline = [DateTime]::UtcNow.AddSeconds(40)
    while (-not (Test-Path -LiteralPath $sfReport) -and [DateTime]::UtcNow -lt $sfDeadline) {
      Start-Sleep -Milliseconds 250
    }
  }
  if (-not (Test-Path -LiteralPath $sfReport)) { throw "桌面未返回自检结果：$sfTestRoot" }
  $sfResult = Get-Content -LiteralPath $sfReport -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $sfResult.ok -or $sfResult.health.codex_available -or $sfResult.health.codex_required -or
    $sfResult.ui.provider -ne 'deepseek' -or $sfResult.ui.codexRequests.Count -ne 0) {
    throw ('独立桌面自检失败：' + ($sfResult | ConvertTo-Json -Depth 8 -Compress))
  }
  $sfDesktop = Get-Process -Id $sfResult.desktop_pid -ErrorAction SilentlyContinue
  if ($sfDesktop -and -not $sfDesktop.WaitForExit(5000)) { throw '桌面自检退出超时' }
  $sfBackend = Get-Process -Id $sfResult.backend_pid -ErrorAction SilentlyContinue
  if ($sfBackend -and -not $sfBackend.WaitForExit(1500)) {
    throw '桌面退出后自检后台仍在运行'
  }
  [ordered]@{ok=$true;codex_available=$false;codex_requests=0;provider=$sfResult.ui.provider;
    native_desktop_started=$true;acceptance_launcher=[bool]$AcceptanceLauncher;
    assessment_controls=$sfResult.ui.assessmentControls;file_imported=$true;own_backend_stopped=$true;report=$sfReport} | ConvertTo-Json
} finally {
  if ($sfProcess -and -not $sfProcess.HasExited) { Stop-Process -Id $sfProcess.Id -Force }
  foreach ($sfName in $sfVariables) { [System.Environment]::SetEnvironmentVariable($sfName, $sfOriginal[$sfName], 'Process') }
}
