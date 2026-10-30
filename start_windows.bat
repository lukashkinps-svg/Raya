@echo off
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
echo [%date% %time%] Launcher started>> "logs\launcher.log"
py -3 -m pip install -r requirements.txt >> "logs\launcher.log" 2>&1
if errorlevel 1 (
 echo Cannot install dependencies. See logs\launcher.log
 pause
 exit /b 1
)
py -3 raya.py >> "logs\launcher.log" 2>&1
if errorlevel 1 (
 echo Raya encountered an error. See logs\raya.log and logs\launcher.log
 pause
 exit /b 1
)
