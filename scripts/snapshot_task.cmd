@echo off
rem Task Scheduler entry point: run one snapshot from the repo folder, then the settlement
rem check for earlier days, appending both reports
rem to data\logs\snapshot_YYYY-MM-DD.log. Exit code is snapshot.py's, so failures show in
rem the task's "Last Run Result" (a settlement mismatch shows only in the log).
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
echo ===== %DATE% %TIME% ===== >> "data\logs\snapshot_%TODAY%.log"
".venv\Scripts\python.exe" scripts\snapshot.py >> "data\logs\snapshot_%TODAY%.log" 2>&1
set SNAP=%ERRORLEVEL%
rem Earlier days' settlements (Kalshi settles ~3 hours after the close, so not today's).
".venv\Scripts\python.exe" scripts\check_settlement.py >> "data\logs\snapshot_%TODAY%.log" 2>&1
exit /b %SNAP%
