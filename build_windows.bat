@echo off
REM =========================================================================
REM Keystone Office Audio Hub — Windows Single-File Executable Builder
REM Builds standalone ManagerHub.exe and EmployeeAgent.exe using PyInstaller
REM =========================================================================

echo [1/3] Setting up Python virtual environment...
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo [2/3] Installing build dependencies...
pip install --upgrade pip
pip install -r requirements.txt pyinstaller

echo [3/3] Compiling Standalone Executables...
python packaging\build_manager.py
python packaging\build_agent.py

echo.
echo =========================================================================
echo  Build Finished! Executables are located in: dist\
echo  - ManagerHub.exe
echo  - EmployeeAgent.exe
echo =========================================================================
pause
