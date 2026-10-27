$ErrorActionPreference = 'Stop'
$sfRoot = Split-Path $PSScriptRoot -Parent
$sfTestRoot = Join-Path $sfRoot ('build\desktop-tray-' + [guid]::NewGuid().ToString('N'))
$sfData = Join-Path $sfTestRoot 'data'
[System.IO.Directory]::CreateDirectory($sfData) | Out-Null
$sfVariables = @('STUDYFORGE_DATA_DIR','STUDYFORGE_SMOKE_REPORT','STUDYFORGE_SMOKE_TRAY','STUDYFORGE_TRAY_PHASE','STUDYFORGE_SMOKE_MODELS')
$sfOriginal = @{}
foreach ($sfName in $sfVariables) { $sfOriginal[$sfName] = [System.Environment]::GetEnvironmentVariable($sfName, 'Process') }
$sfProcess = $null
$sfResults = @()
try {
  $env:STUDYFORGE_DATA_DIR = $sfData
  $env:STUDYFORGE_SMOKE_TRAY = '1'
  $env:STUDYFORGE_SMOKE_MODELS = '0'
  foreach ($sfPhase in @(1,2)) {
    $env:STUDYFORGE_TRAY_PHASE = [string]$sfPhase
    $sfReport = Join-Path $sfTestRoot ("phase-$sfPhase.json")
    $env:STUDYFORGE_SMOKE_REPORT = $sfReport
    $sfProcess = Start-Process -FilePath (Join-Path $sfRoot 'node_modules\electron\dist\electron.exe') `
      -ArgumentList ('"' + $sfRoot + '"') -WorkingDirectory $sfRoot -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $sfTestRoot "desktop-$sfPhase.log") `
      -RedirectStandardError (Join-Path $sfTestRoot "desktop-error-$sfPhase.log")
    if (-not $sfProcess.WaitForExit(50000)) { throw "托盘第 $sfPhase 阶段验收超时：$sfTestRoot" }
    if (-not (Test-Path -LiteralPath $sfReport)) { throw "桌面未返回结果：$sfTestRoot" }
    $sfResult = Get-Content -LiteralPath $sfReport -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $sfResult.ok) { throw ('托盘验收失败：' + ($sfResult | ConvertTo-Json -Depth 8 -Compress)) }
    foreach ($sfOwnPid in @($sfResult.backend_pid, $sfResult.child_pid)) {
      $sfOwnProcess = Get-Process -Id $sfOwnPid -ErrorAction SilentlyContinue
      if ($sfOwnProcess -and -not $sfOwnProcess.WaitForExit(2500)) { throw "完全退出后自己的子进程仍存活：$sfOwnPid" }
    }
    $sfPort = ([uri]$sfResult.url).Port
    $sfSocket = [System.Net.Sockets.TcpClient]::new()
    try {
      $sfConnect = $sfSocket.BeginConnect('127.0.0.1',$sfPort,$null,$null)
      if ($sfConnect.AsyncWaitHandle.WaitOne(500)) {
        try { $sfSocket.EndConnect($sfConnect) } catch { }
      }
      if ($sfSocket.Connected) { throw '完全退出后本机服务端口仍可访问' }
    } finally { $sfSocket.Dispose() }
    $sfResult | Add-Member -NotePropertyName own_backend_and_child_stopped -NotePropertyValue $true
    $sfResults += $sfResult
  }
  if ($sfResults[0].partial_artifact_id -ne $sfResults[1].restored_artifact_id) { throw '重开后未复用原来的讲解成果' }
  $sfSummary = [ordered]@{ok=$true;native_windows_tray=$true;model_requests='isolated mock only';
    closed_window_generation_completed=$sfResults[0].generated_while_hidden;
    unsent_draft_and_chat_preserved=$sfResults[0].same_window_draft_and_chat;
    second_launch_restores_same_window=$sfResults[0].second_launch_restores_same_window;
    manual_restart_resume=$sfResults[1].restart_requires_explicit_resume;
    cached_lecture_and_artifact_reused=$sfResults[1].saved_lecture_reused;
    exercise_docx_separate=$sfResults[1].exercise_docx_separate;
    own_backend_and_child_stopped=$true;reports=@($sfResults | ForEach-Object { Join-Path $sfTestRoot ("phase-$($_.phase).json") })}
  [System.IO.File]::WriteAllText((Join-Path $sfTestRoot 'result.json'),($sfSummary | ConvertTo-Json -Depth 6),[System.Text.UTF8Encoding]::new($false))
  $sfSummary | ConvertTo-Json -Depth 6
} finally {
  if ($sfProcess -and -not $sfProcess.HasExited) { Stop-Process -Id $sfProcess.Id -Force }
  # Only PIDs created by this isolated run are eligible for cleanup.
  foreach ($sfPhase in @(1,2)) {
    $sfPidFile = Join-Path $sfData "tray-process-$sfPhase.json"
    if (Test-Path -LiteralPath $sfPidFile) {
      $sfPids = Get-Content -LiteralPath $sfPidFile -Raw -Encoding UTF8 | ConvertFrom-Json
      foreach ($sfOwnPid in @($sfPids.backend_pid,$sfPids.child_pid)) {
        $sfOwnProcess = Get-Process -Id $sfOwnPid -ErrorAction SilentlyContinue
        if ($sfOwnProcess) { Stop-Process -Id $sfOwnPid -Force -ErrorAction SilentlyContinue }
      }
    }
  }
  foreach ($sfName in $sfVariables) { [System.Environment]::SetEnvironmentVariable($sfName, $sfOriginal[$sfName], 'Process') }
}
