@echo off
rem Task Scheduler entry point: run one snapshot from the repo folder and append its report
rem to data\logs\snapshot_YYYY-MM-DD.log. Exit code is snapshot.py's, so failures show in
rem the task's "Last Run Result".
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
echo ===== %DATE% %TIME% ===== >> "data\logs\snapshot_%TODAY%.log"
".venv\Scripts\python.exe" scripts\snapshot.py >> "data\logs\snapshot_%TODAY%.log" 2>&1
exit /b %ERRORLEVEL%
