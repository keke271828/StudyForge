param([string]$Application = '', [switch]$UseSystemTools)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Application) { $Application = Join-Path $projectRoot 'dist\win-unpacked\StudyForge.exe' }
$Application = (Resolve-Path -LiteralPath $Application).Path
$testRoot = Join-Path $projectRoot ('build\installed-smoke-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$savedPath = $env:PATH
$savedData = $env:STUDYFORGE_DATA_DIR
$savedReport = $env:STUDYFORGE_SMOKE_REPORT
$savedModels = $env:STUDYFORGE_SMOKE_MODELS
$startupEntry = 'StudyForge.Acceptance.' + (Split-Path $testRoot -Leaf)
try {
    # Exercise the installed application without Python, Node, or repository cwd.
    if (-not $UseSystemTools) { $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot" }
    $env:STUDYFORGE_SMOKE_MODELS = if ($UseSystemTools) { '1' } else { '0' }
    $env:STUDYFORGE_DATA_DIR = Join-Path $testRoot 'data'
    $env:STUDYFORGE_SMOKE_REPORT = Join-Path $testRoot 'report.json'
    New-Item -ItemType Directory -Path $env:STUDYFORGE_DATA_DIR | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $env:STUDYFORGE_DATA_DIR 'settings.json'),
      '{"chat_provider":"deepseek","background_learning_enabled":false}',[System.Text.UTF8Encoding]::new($false))
    # Verify a real source-to-packaged migration under a test-owned name.
    $startupSourceExecutable = Join-Path $projectRoot 'node_modules\electron\dist\electron.exe'
    $startupSourceArguments = @($projectRoot,'--studyforge-autostart','--studyforge-start-hidden')
    $startupFixture = @{enabled=$true;start_hidden=$true;launch=@{path=$startupSourceExecutable;args=$startupSourceArguments}}
    New-Item -ItemType Directory -Path (Join-Path $env:STUDYFORGE_DATA_DIR 'desktop') | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $env:STUDYFORGE_DATA_DIR 'desktop\startup.json'),
      ($startupFixture | ConvertTo-Json -Depth 4),[System.Text.UTF8Encoding]::new($false))
    $startupRunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $startupApprovalKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    if (-not (Test-Path -LiteralPath $startupRunKey)) { New-Item -Path $startupRunKey | Out-Null }
    if (-not (Test-Path -LiteralPath $startupApprovalKey)) { New-Item -Path $startupApprovalKey | Out-Null }
    $startupSourceCommand = '"' + $startupSourceExecutable + '" "' + $projectRoot + '" --studyforge-autostart --studyforge-start-hidden'
    New-ItemProperty -LiteralPath $startupRunKey -Name $startupEntry -Value $startupSourceCommand -PropertyType String -Force | Out-Null
    New-ItemProperty -LiteralPath $startupApprovalKey -Name $startupEntry -Value ([byte[]]@(2,0,0,0,0,0,0,0,0,0,0,0)) -PropertyType Binary -Force | Out-Null
    $process = Start-Process -FilePath $Application -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
    $startupMigrated = $false
    $startupMigratedCommand = $null
    $startupDeadline = [DateTime]::UtcNow.AddSeconds(90)
    while (-not $process.HasExited -and [DateTime]::UtcNow -lt $startupDeadline) {
        $startupRunSnapshot = Get-ItemProperty -LiteralPath $startupRunKey
        $startupCommandProperty = $startupRunSnapshot.PSObject.Properties[$startupEntry]
        $startupActualCommand = if ($startupCommandProperty) { $startupCommandProperty.Value } else { $null }
        if ($startupActualCommand -and $startupActualCommand.StartsWith(('"' + $Application + '"'),[StringComparison]::OrdinalIgnoreCase)) {
            $startupMigrated = $true
            $startupMigratedCommand = $startupActualCommand
        }
        $process.WaitForExit(200) | Out-Null
    }
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        throw 'Packaged application did not finish its smoke test within 90 seconds.'
    }
    if (-not (Test-Path -LiteralPath $env:STUDYFORGE_SMOKE_REPORT)) { throw 'No packaged application report was produced.' }
    $report = Get-Content -LiteralPath $env:STUDYFORGE_SMOKE_REPORT -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $report.ok -or -not $report.packaged) { throw "Packaged application failed: $($report | ConvertTo-Json -Depth 10)" }
    if (-not $startupMigrated) { throw 'Source startup entry did not migrate to the packaged application' }
    $report | Add-Member -NotePropertyName startup_migration -NotePropertyValue @{verified=$startupMigrated;command=$startupMigratedCommand}
    [System.IO.File]::WriteAllText($env:STUDYFORGE_SMOKE_REPORT,($report | ConvertTo-Json -Depth 10),[System.Text.UTF8Encoding]::new($false))
    # The backend drains an acknowledged shutdown before its process exits.
    # Give that bounded cleanup time even when package checks run concurrently.
    $backendStillRunning = $true
    for ($cleanupIndex = 0; $cleanupIndex -lt 50; $cleanupIndex++) {
        $backendStillRunning = [bool](Get-Process -Id $report.backend_pid -ErrorAction SilentlyContinue)
        if (-not $backendStillRunning) { break }
        Start-Sleep -Milliseconds 200
    }
    if ($backendStillRunning) { throw 'Backend remained running after GUI exited.' }
    $report | ConvertTo-Json -Depth 10
} finally {
    Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $startupEntry -ErrorAction SilentlyContinue
    Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run' -Name $startupEntry -ErrorAction SilentlyContinue
    $env:PATH = $savedPath
    $env:STUDYFORGE_DATA_DIR = $savedData
    $env:STUDYFORGE_SMOKE_REPORT = $savedReport
    $env:STUDYFORGE_SMOKE_MODELS = $savedModels
}
