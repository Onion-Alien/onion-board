@echo off
rem Fallback installer: Soundboard's Voice tab has an Install button that does the same.
rem Needs Python 3.12+ (python.org). About 300 MB with the speech model.
rem   install.bat --quiet   no "press a key" at the end (SoundboardSetup.exe uses this)
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt || goto :fail
.venv\Scripts\python.exe helper.py --download base.en || goto :fail
echo.
echo Live voice-to-speech is installed. Press Refresh in Soundboard's Voice tab.
if /i not "%~1"=="--quiet" pause
exit /b 0
:fail
echo.
echo Install failed - see the messages above.
if /i not "%~1"=="--quiet" pause
exit /b 1
