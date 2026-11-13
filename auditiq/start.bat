@echo off
rem AuditIQ, live: starts Kafka, streams the mock ledger through it, audits what arrives and opens the web
rem application. Everything it does is in scripts\live.py.
rem
rem   start.bat                       a fresh run: an empty store, new topics, everything streamed and audited
rem   start.bat --keep                open the last run again; nothing is published
rem   start.bat --ledger bench_seed_202 --limit 1000
rem   start.bat stop                  stop the Kafka broker
rem   start.bat reset                 stop it and delete the topics and messages of every run
setlocal
cd /d "%~dp0"

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 or later is needed: https://www.python.org/downloads/
    pause
    exit /b 1
)

"%PYTHON%" scripts\live.py %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%
