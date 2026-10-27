@echo off
REM Quick launcher for Employee Agent
if exist "dist\EmployeeAgent.exe" (
    start "" "dist\EmployeeAgent.exe"
) else (
    call .venv\Scripts\activate.bat
    python run_agent.py
)
