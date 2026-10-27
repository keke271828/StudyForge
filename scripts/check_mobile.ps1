$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
$pythonPath = 'C:/Users/Lenovo/AppData/Local/Programs/Python/Python312/python.exe'
$electronPath = Join-Path $repoPath 'node_modules/electron/dist/electron.exe'
$runPath = Join-Path $repoPath ('build/mobile-e2e-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runPath | Out-Null
$env:STUDYFORGE_MOBILE_CASE = Join-Path $runPath 'case.json'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $repoPath
$fixture = $null
try {
  $fixture = Start-Process -FilePath $pythonPath -ArgumentList @('-u', 'scripts/smoke_mobile.py') -WorkingDirectory $repoPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runPath 'server.log') -RedirectStandardError (Join-Path $runPath 'server-error.log')
  for ($index=0; $index -lt 240; $index++) {
    if (Test-Path -LiteralPath $env:STUDYFORGE_MOBILE_CASE) { break }
    if ($fixture.HasExited) { throw 'Mobile fixture exited before startup; inspect server-error.log' }
    Start-Sleep -Milliseconds 200
  }
  if (-not (Test-Path -LiteralPath $env:STUDYFORGE_MOBILE_CASE)) { throw 'Mobile fixture did not start' }
  @'
import json, os, ssl, urllib.request
from pathlib import Path
case=json.loads(Path(os.environ['STUDYFORGE_MOBILE_CASE']).read_text(encoding='utf-8'))
context=ssl.create_default_context()
context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(Path(case['certificate']).read_bytes()))
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
with opener.open(case['mobile_url']+'/',timeout=10) as response:
    assert response.status==200 and b'StudyForge' in response.read()
print('Trusted HTTPS handshake passed')
'@ | & $pythonPath -
  if ($LASTEXITCODE -ne 0) { throw 'TLS verification failed' }
  $uiProcess = Start-Process -FilePath $electronPath -ArgumentList @('scripts/smoke_mobile_ui.js') -WorkingDirectory $repoPath -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $runPath 'ui.log') -RedirectStandardError (Join-Path $runPath 'ui-error.log')
  Get-Content -LiteralPath (Join-Path $runPath 'ui.log')
  if ($uiProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $runPath 'ui-report.json'))) {
    Get-Content -LiteralPath (Join-Path $runPath 'ui-error.log')
    throw ('Mobile interface check failed: ' + $runPath)
  }
  & $pythonPath (Join-Path $repoPath 'scripts/check_mobile_downloads.py')
  if ($LASTEXITCODE -ne 0) { throw 'Downloaded DOCX is invalid' }
  Write-Output ('MOBILE_CHECK_PASS ' + $runPath)
} finally {
  if ($fixture -and -not $fixture.HasExited) { Stop-Process -Id $fixture.Id -ErrorAction SilentlyContinue }
}
