@echo off
cd /d %~dp0
.venv\Scripts\python.exe main.py >> logs\run.log 2>&1
