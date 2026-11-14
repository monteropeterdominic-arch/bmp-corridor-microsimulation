@echo off
cd /d "%~dp0"
if not defined SUMO_HOME if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe" set "SUMO_HOME=C:\Program Files (x86)\Eclipse\Sumo"
if not defined SUMO_HOME if exist "C:\Program Files\Eclipse\Sumo\bin\sumo.exe" set "SUMO_HOME=C:\Program Files\Eclipse\Sumo"
echo SUMO_HOME=%SUMO_HOME% > replay_log.txt
python run_bmp.py --replay >> replay_log.txt 2>&1
echo EXIT CODE %ERRORLEVEL% >> replay_log.txt
echo Finished. See replay_log.txt
pause
