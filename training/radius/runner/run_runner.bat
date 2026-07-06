@echo off
cd /d C:\GridFront\scout\training\radius\runner
set RADIUS_BATCH=28
set RADIUS_WORKERS=8
C:\GridFront\scout\training\radius\.venv\Scripts\python.exe runner.py >> logs\runner_boot.log 2>> logs\runner_boot.err
