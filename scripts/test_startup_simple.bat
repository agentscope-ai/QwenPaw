@echo off
REM Simple startup timing test
REM Usage: Double-click to run, or execute from command line

set QWENPAW_DESKTOP_APP=1
set QWENPAW_LOG_LEVEL=info

echo ========================================
echo  Startup Timing Test
echo ========================================
echo Start time: %time%
echo.
echo Starting QwenPaw desktop...
echo Watch for these key events in the output:
echo   - "Creating webview window with loading page"
echo   - "HTTP backend is ready"
echo   - "Backend ready, navigating to app URL"
echo.
echo ========================================
echo.

python -u -m qwenpaw desktop --log-level info

echo.
echo ========================================
echo  Test complete. Press any key to exit.
echo ========================================
pause >nul
