@echo off
rem Fallback installer: Soundboard's Voice tab has an Install button that does the same.
rem Needs Python 3.10+ on PATH (python.org). About 300 MB with the speech model.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt || goto :fail
.venv\Scripts\python.exe helper.py --download base.en || goto :fail
echo.
echo Live voice-to-speech is installed. Press Refresh in Soundboard's Voice tab.
pause
exit /b 0
:fail
echo.
echo Install failed - see the messages above.
pause
exit /b 1
