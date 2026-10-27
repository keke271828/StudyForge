@echo off
cd /d "%~dp0"
set "SF_PY="
if defined STUDYFORGE_PYTHON if exist "%STUDYFORGE_PYTHON%" set "SF_PY=%STUDYFORGE_PYTHON%"
if not defined SF_PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "SF_PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined SF_PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "SF_PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined SF_PY for %%P in (python.exe) do if not "%%~$PATH:P"=="" set "SF_PY=%%~$PATH:P"
if not defined SF_PY goto :error
"%SF_PY%" --version || goto :error
npm --version || goto :error
"%SF_PY%" -m pip install -e . || goto :error
npm ci || goto :error
> ".studyforge-python" echo %SF_PY%
echo.
echo StudyForge is installed. Double-click start_studyforge.cmd to open it.
pause
exit /b 0
:error
echo Setup failed. Install Python 3.12 or newer and Node.js 22 or newer, then try again.
pause
exit /b 1
