@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo ERROR: Virtual environment not found in %~dp0
  echo Run README_SETUP.md to create the environment first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe scanner.py
pause
