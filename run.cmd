@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo ERROR: Virtual environment not found in %~dp0. Use README_SETUP.md to create it.
  exit /b 1
)
.venv\Scripts\python.exe scanner.py
