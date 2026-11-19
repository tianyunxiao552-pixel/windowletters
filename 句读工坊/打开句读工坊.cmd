@echo off
cd /d "%~dp0"
if exist "C:\python\pythonw.exe" (
  start "" "C:\python\pythonw.exe" "%~dp0annotator.pyw"
  exit /b
)
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
  start "" pythonw.exe "%~dp0annotator.pyw"
  exit /b
)
echo Please install Python 3 with Tcl/Tk support.
pause
