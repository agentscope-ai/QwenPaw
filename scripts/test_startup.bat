@echo off
REM Quick startup timing test for desktop optimization
REM This script measures the time from startup to loading page and backend ready

set QWENPAW_DESKTOP_APP=1
set QWENPAW_LOG_LEVEL=info

echo ========================================
echo  Startup Timing Test
echo ========================================
echo Start time: %time%
echo.

echo [Test] Starting QwenPaw desktop...
echo [Test] Watch for these key events:
echo   1. "Creating webview window with loading page" - Loading page appears
echo   2. "HTTP backend is ready" - Backend is ready
echo   3. "Backend ready, navigating to app URL" - Navigation happens
echo.

python -u -m qwenpaw desktop --log-level info

echo.
echo ========================================
echo  Test complete
echo ========================================
pause
