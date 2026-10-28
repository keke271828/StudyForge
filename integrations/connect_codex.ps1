$ErrorActionPreference = 'Stop'
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw '未找到 Codex CLI。请先安装 Codex 并登录。'
}
$pythonFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.studyforge-python'
if (Test-Path -LiteralPath $pythonFile) {
    $studyforgePython = (Get-Content -LiteralPath $pythonFile -Raw).Trim()
} elseif (Test-Path -LiteralPath "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") {
    $studyforgePython = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
} else {
    $studyforgePython = (Get-Command python -ErrorAction Stop).Source
}
codex mcp add studyforge -- $studyforgePython -m studyforge.mcp_server
codex mcp list
