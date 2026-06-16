@echo off
REM Quick startup timing test
REM Run this from the QwenPaw root directory

set QWENPAW_DESKTOP_APP=1
set QWENPAW_LOG_LEVEL=info

echo === Startup Timing Test ===
echo Start time: %time%
echo.
echo Starting QwenPaw desktop...
echo.

python -u -m qwenpaw desktop --log-level info 2>&1 | findstr /i "loading page HTTP ready Backend ready"

echo.
echo Test complete. Check the timestamps above.
pause
