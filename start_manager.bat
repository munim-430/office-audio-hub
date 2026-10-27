@echo off
REM Quick launcher for Manager Hub
if exist "dist\ManagerHub.exe" (
    start "" "dist\ManagerHub.exe"
) else (
    call .venv\Scripts\activate.bat
    python run_hub.py
)
