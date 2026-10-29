@echo off
cd /d "C:\Users\thoma\Desktop\Claude Code Projects\whoop-export"

:: Kill any existing dashboard server on port 8080
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080.*LISTENING"') do taskkill /PID %%a /F >nul 2>&1

:: Run the export
python whoop.py export

:: Start the dashboard server in the background
start /B python -m http.server 8080
