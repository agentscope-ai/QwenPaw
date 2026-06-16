@echo off
REM Quick startup test - run this and watch the output
REM Press Ctrl+C to stop after you see the key events

set QWENPAW_DESKTOP_APP=1
set QWENPAW_LOG_LEVEL=info

echo ========================================
echo  Startup Timing Test
echo ========================================
echo Start time: %time%
echo.
echo Key events to watch:
echo   1. "Creating webview window with loading page"
echo   2. "HTTP backend is ready"
echo   3. "Backend ready, navigating to app URL"
echo.
echo ========================================
echo.

python -u -m qwenpaw desktop --log-level info 2>&1 | findstr /i "loading page HTTP backend Backend ready Server subprocess elapsed_ms"

echo.
echo ========================================
echo  Test complete. Press Ctrl+C to exit.
echo ========================================
pause
