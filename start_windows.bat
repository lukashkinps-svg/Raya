@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
echo [%date% %time%] Launcher started >> "logs\launcher.log"

rem Verify dependencies quietly. Install only when absent.
py -3 -c "import PySide6, PIL" >nul 2>&1
if errorlevel 1 (
    echo [%date% %time%] Installing missing dependencies... >> "logs\launcher.log"
    py -3 -m pip install -r "requirements.txt" >> "logs\launcher.log" 2>&1
    if errorlevel 1 goto :pip_failed
)

rem Python's GUI launcher does not attach Raya to this console.
where pyw.exe >nul 2>&1
if errorlevel 1 goto :pyw_missing
start "" /D "%~dp0" pyw -3 "%~dp0raya.py"
if errorlevel 1 goto :launch_failed

echo [%date% %time%] Launched Raya in a separate windowless process. >> "logs\launcher.log"
exit /b 0

:pip_failed
echo [%date% %time%] ERROR: Dependency installation failed. >> "logs\launcher.log"
echo Unable to install dependencies. See logs\launcher.log
if /I not "%~1"=="--hidden" pause
exit /b 1

:pyw_missing
echo [%date% %time%] ERROR: pyw.exe not found. >> "logs\launcher.log"
echo The console-free Python launcher pyw.exe is not found. See logs\launcher.log
if /I not "%~1"=="--hidden" pause
exit /b 1

:launch_failed
echo [%date% %time%] ERROR: Could not start Raya via pyw. >> "logs\launcher.log"
echo Could not start Raya. Check logs\launcher.log and logs\raya.log
if /I not "%~1"=="--hidden" pause
exit /b 1
