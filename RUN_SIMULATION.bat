@echo off
cd /d "%~dp0"
if not defined SUMO_HOME if exist "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe" set "SUMO_HOME=C:\Program Files (x86)\Eclipse\Sumo"
if not defined SUMO_HOME if exist "C:\Program Files\Eclipse\Sumo\bin\sumo.exe" set "SUMO_HOME=C:\Program Files\Eclipse\Sumo"
echo SUMO_HOME=%SUMO_HOME% > run_log.txt
where python >> run_log.txt 2>&1
python run_bmp.py >> run_log.txt 2>&1
echo EXIT CODE %ERRORLEVEL% >> run_log.txt
echo Finished. See run_log.txt
pause
