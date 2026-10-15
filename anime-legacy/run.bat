@echo off
rem Anime Legacy auto farm (Python version). Close the AutoHotkey version first (F8):
rem both use the same F-keys.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python packages...
  py -3 -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install numpy opencv-python dxcam comtypes || goto :fail
)
".venv\Scripts\python.exe" farm.py
if errorlevel 1 pause
exit /b
:fail
echo Setup failed. Is Python installed? (py -3 --version)
pause
