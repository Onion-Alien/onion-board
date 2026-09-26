@echo off
rem run Onion Board from source (scripts\install.bat sets up .venv first)
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" main.py
