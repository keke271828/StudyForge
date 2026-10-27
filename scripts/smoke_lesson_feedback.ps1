param([switch]$Knowledge,[switch]$Profile,[switch]$Practice,[switch]$Quality,[switch]$Formats)
$ErrorActionPreference = 'Stop'
$sfRoot = Split-Path $PSScriptRoot -Parent
$sfTestRoot = Join-Path $sfRoot ('build\lesson-feedback-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($sfTestRoot) | Out-Null
$sfVariables = @('STUDYFORGE_DATA_DIR','STUDYFORGE_FEEDBACK_UI_CASE_PATH','STUDYFORGE_KNOWLEDGE_UI','STUDYFORGE_PROFILE_UI','STUDYFORGE_PRACTICE_UI','STUDYFORGE_QUALITY_UI','STUDYFORGE_FORMATS_UI','PYTHONUTF8')
$sfOriginal = @{}
foreach ($sfName in $sfVariables) { $sfOriginal[$sfName] = [System.Environment]::GetEnvironmentVariable($sfName, 'Process') }
$sfServer = $null; $sfDesktop = $null
try {
  $env:STUDYFORGE_DATA_DIR = Join-Path $sfTestRoot 'data'
  $env:STUDYFORGE_FEEDBACK_UI_CASE_PATH = Join-Path $sfTestRoot 'case.json'
  $env:PYTHONUTF8 = '1'
  if ($Knowledge) { $env:STUDYFORGE_KNOWLEDGE_UI = '1' }
  if ($Profile) { $env:STUDYFORGE_PROFILE_UI = '1' }
  if ($Practice) { $env:STUDYFORGE_PRACTICE_UI = '1' }
  if ($Quality) { $env:STUDYFORGE_QUALITY_UI = '1' }
  if ($Formats) { $env:STUDYFORGE_FORMATS_UI = '1' }
  $sfPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  $sfPythonConfig = Join-Path $sfRoot '.studyforge-python'
  if (Test-Path -LiteralPath $sfPythonConfig) { $sfPython = (Get-Content -LiteralPath $sfPythonConfig -Raw).Trim() }
  $sfServer = Start-Process -FilePath $sfPython -ArgumentList '-m scripts.smoke_lesson_feedback' -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfTestRoot 'server.log') -RedirectStandardError (Join-Path $sfTestRoot 'server-error.log')
  $sfDeadline = [DateTime]::UtcNow.AddSeconds(35)
  $sfReady = $false
  while ([DateTime]::UtcNow -lt $sfDeadline) {
    if ($sfServer.HasExited) { throw ('Test server exited: ' + (Get-Content -LiteralPath (Join-Path $sfTestRoot 'server-error.log') -Raw)) }
    if (Test-Path -LiteralPath $env:STUDYFORGE_FEEDBACK_UI_CASE_PATH) {
      $sfCase = Get-Content -LiteralPath $env:STUDYFORGE_FEEDBACK_UI_CASE_PATH -Raw -Encoding UTF8 | ConvertFrom-Json
      try { Invoke-RestMethod -Uri ($sfCase.url + '/api/health') -TimeoutSec 1 | Out-Null; $sfReady = $true; break } catch {}
    }
    Start-Sleep -Milliseconds 200
  }
  if (-not $sfReady) { throw 'Test server startup timed out' }
  $sfUiScript = if ($Formats) { 'scripts/smoke_deliverables_ui.js' } elseif ($Quality) { 'scripts/smoke_lesson_quality_ui.js' } elseif ($Practice) { 'scripts/smoke_practice_ui.js' } elseif ($Profile) { 'scripts/smoke_learning_profile_ui.js' } elseif ($Knowledge) { 'scripts/smoke_knowledge_ui.js' } else { 'scripts/smoke_lesson_feedback_ui.js' }
  $sfDesktop = Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') -ArgumentList $sfUiScript -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $sfTestRoot 'ui-result.json') -RedirectStandardError (Join-Path $sfTestRoot 'ui-error.log')
  if (-not $sfDesktop.WaitForExit(50000)) { throw 'Questionnaire UI test timed out' }
  if ($null -ne $sfDesktop.ExitCode -and $sfDesktop.ExitCode -ne 0) { throw ('Questionnaire UI failed: ' + (Get-Content -LiteralPath (Join-Path $sfTestRoot 'ui-error.log') -Raw -Encoding UTF8)) }
  $sfResult = Get-Content -LiteralPath (Join-Path $sfTestRoot 'ui-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $sfResult.ok) { throw ('Desktop UI returned failure: ' + (Get-Content -LiteralPath (Join-Path $sfTestRoot 'ui-error.log') -Raw -Encoding UTF8)) }
  $sfCalls = Get-Content -LiteralPath (Join-Path $sfTestRoot 'cloud_requests.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($Formats) {
    if ($sfResult.generation_cloud_requests -ne 7 -or $sfCalls.feedback_requests -ne 0) { throw 'Format transformation request count failed' }
  } elseif ($Quality) {
    if ($sfResult.controls_cloud_requests -ne 0 -or $sfResult.generation_cloud_requests -ne 1 -or $sfCalls.feedback_requests -ne 0) { throw 'Quality controls called AI or generation added review requests' }
  } elseif ($Practice) {
    if ($sfResult.controls_cloud_requests -ne 0 -or $sfCalls.grading_requests -ne 4 -or $sfCalls.feynman_requests -ne 1) { throw 'Practice controls used AI or grading request count failed' }
  } elseif ($Profile) {
    if ($sfResult.controls_cloud_requests -ne 0 -or $sfResult.tutor_cloud_requests -ne 2 -or -not $sfCalls.last_profile_corrected -or $sfCalls.last_profile_old) { throw 'Profile controls called AI or corrected mentor context failed' }
  } elseif ($Knowledge) {
    if ($sfCalls.knowledge_requests -ne 1 -or $sfCalls.feedback_requests -ne 0 -or -not $sfCalls.last_has_structure) { throw 'Knowledge request count or mentor context failed' }
  } elseif ($sfCalls.feedback_requests -ne 1) { throw 'Submitting/skipping duplicated AI supplement calls' }
  [ordered]@{ok=$true;ui=$sfResult;mock_cloud_calls=$sfCalls;report_dir=$sfTestRoot} | ConvertTo-Json -Depth 8
} finally {
  if ($sfDesktop -and -not $sfDesktop.HasExited) { Stop-Process -Id $sfDesktop.Id -Force }
  if ($sfServer -and -not $sfServer.HasExited) { Stop-Process -Id $sfServer.Id -Force }
  foreach ($sfName in $sfVariables) { [System.Environment]::SetEnvironmentVariable($sfName, $sfOriginal[$sfName], 'Process') }
}
