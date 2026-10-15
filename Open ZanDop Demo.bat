@echo off
setlocal
cd /d "%~dp0"
title ZanDop - Local Demo
echo.
echo ZanDop - Local Demo
echo First launch installs dependencies. Keep this window open while using ZanDop.
echo.
py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>&1
if not errorlevel 1 (
    py -3.12 scripts\local_demo.py --demo
    goto finished
)
python -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>&1
if not errorlevel 1 (
    python scripts\local_demo.py --demo
    goto finished
)
echo Python 3.12 is required for this version of ZanDop.
echo Install Python 3.12 using the official Python Install Manager:
echo https://www.python.org/downloads/windows/
echo After installing the manager, run: py install 3.12
echo Then double-click this file again.
:finished
echo.
echo You may close this window. If startup failed, the reason is shown above.
pause
