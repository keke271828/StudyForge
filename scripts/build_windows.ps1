param([switch]$BackendOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if (-not $env:ELECTRON_BUILDER_CACHE) {
    $env:ELECTRON_BUILDER_CACHE = Join-Path $projectRoot 'build\installer-tools'
}

$pythonCandidates = @($env:STUDYFORGE_PYTHON)
$savedPython = Join-Path $projectRoot '.studyforge-python'
if (Test-Path -LiteralPath $savedPython) {
    $pythonCandidates += (Get-Content -LiteralPath $savedPython -Raw).Trim()
}
foreach ($version in @('Python312', 'Python313', 'Python314')) {
    $pythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\$version\python.exe"
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
$buildPython = $pythonCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $buildPython) { throw 'Build requires Python 3.12+ with StudyForge and PyInstaller installed.' }

& $buildPython -c 'import PyInstaller, studyforge'
if ($LASTEXITCODE -ne 0) { throw 'Install build dependencies: python -m pip install -e . pyinstaller' }
& node scripts/vendor_web.js
if ($LASTEXITCODE -ne 0) { throw 'Web rendering asset bundling failed.' }
& $buildPython scripts/make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
& $buildPython -m PyInstaller --noconfirm --distpath build/backend --workpath build/pyinstaller scripts/backend.spec
if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed.' }
if (-not $BackendOnly) {
    & node scripts/release_config.js
    if ($LASTEXITCODE -ne 0) { throw 'Release update configuration is invalid.' }
    & npx.cmd electron-builder --config build/release-builder.json --win --x64 --publish never
    if ($LASTEXITCODE -ne 0) { throw 'Windows application packaging failed.' }
}
