@echo off
REM =====================================================================
REM  Q2E launcher for Windows. Double-click this file.
REM  First run installs everything it needs (5-15 minutes). Later runs start in seconds.
REM  To stop Q2E, close this window.
REM =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo.
echo   Q2E - Question to Evidence
echo   ------------------------------------------------------------

REM 1. Python
set "PY="
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul && set "PY=py -3")
if not defined PY (
  where python >nul 2>nul && (python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul && set "PY=python")
)
if not defined PY (
  echo   Python 3.10 or newer is not installed.
  echo   Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo   then double-click this file again.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)

REM 2. R  (R does not add itself to PATH on Windows, so look in Program Files)
set "RS="
where Rscript >nul 2>nul && set "RS=Rscript"
if not defined RS (
  for /d %%D in ("%ProgramFiles%\R\R-*") do if exist "%%D\bin\Rscript.exe" set "RS=%%D\bin\Rscript.exe"
)
if not defined RS (
  for /d %%D in ("%LOCALAPPDATA%\Programs\R\R-*") do if exist "%%D\bin\Rscript.exe" set "RS=%%D\bin\Rscript.exe"
)
if not defined RS (
  echo   R is not installed.
  echo   Install it from https://cloud.r-project.org/  ^(Download R for Windows ^> base^)
  echo   then double-click this file again.
  start "" "https://cloud.r-project.org/bin/windows/base/"
  pause
  exit /b 1
)
set "Q2E_RSCRIPT=%RS%"

REM 3. One-time setup
if not exist ".venv\q2e_ready.txt" (
  echo   First-time setup: installing Python components...
  %PY% -m venv .venv
  if errorlevel 1 ( echo   Could not create a Python environment. & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  if errorlevel 1 ( echo   Python install failed - check your internet connection. & pause & exit /b 1 )
  echo   First-time setup: installing R statistics packages ^(this is the slow part^)...
  "%RS%" r\install_packages.R
  if errorlevel 1 ( echo   R package install failed - check your internet connection. & pause & exit /b 1 )
  echo ready> ".venv\q2e_ready.txt"
)
if not exist "data\synthetic\P_DEMO.xpt" (
  echo   Creating the synthetic demo dataset...
  "%RS%" r\synth\make_synthetic_nhanes.R data\synthetic 12000 20261010 >nul
)
if not exist "data\nhanes" mkdir "data\nhanes"
if not exist "workspace" mkdir "workspace"

REM 4. Start and open the browser
echo.
echo   Starting Q2E at http://127.0.0.1:8000
echo   Keep this window open while you use Q2E. Close it to stop.
echo.
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start "" http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m q2e serve --port 8000
pause
