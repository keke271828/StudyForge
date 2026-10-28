@echo off
setlocal
cd /d "%~dp0"
if not exist "node_modules\electron\dist\electron.exe" (
  echo Source runtime is missing. Run setup_studyforge.cmd first.
  pause
  exit /b 1
)
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0"
exit /b 0
