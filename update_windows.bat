@echo off
setlocal
cd /d "%~dp0"
echo Checking for updates...
where git >nul 2>&1
if errorlevel 1 (
  echo Git is not installed. Install Git for Windows from https://git-scm.com/downloads/win
  echo Existing version is unaffected.
  pause
  exit /b 1
)
if not exist ".git" (
  echo This folder is not linked to a Git repository yet.
  echo Once Raya Prime is published to GitHub, install it with git clone,
  echo or link this folder to the repository following README_RU.md.
  echo No files were changed.
  pause
  exit /b 1
)
git pull --ff-only
if errorlevel 1 (
 echo Update stopped safely. See Git message above; no forced overwrite was attempted.
 pause
 exit /b 1
)
py -3 -m pip install -r requirements.txt
if errorlevel 1 (
 echo Dependencies could not be updated. See details above.
 pause
 exit /b 1
)
echo Update completed. Restart Raya Prime to apply it.
pause
