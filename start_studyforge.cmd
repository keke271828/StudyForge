@echo off
cd /d "%~dp0"
if exist "dist\win-unpacked\StudyForge.exe" (
  start "" "%~dp0dist\win-unpacked\StudyForge.exe"
  exit /b 0
)
if not exist "node_modules\electron\dist\electron.exe" (
  echo StudyForge is not installed. Run setup_studyforge.cmd first.
  pause
  exit /b 1
)
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0"
exit /b 0
