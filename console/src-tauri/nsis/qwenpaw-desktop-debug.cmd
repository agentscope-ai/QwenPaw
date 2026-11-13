@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not defined QWENPAW_LOG_LEVEL set "QWENPAW_LOG_LEVEL=debug"
set "QWENPAW_DESKTOP_DEBUG=1"
set "RUST_BACKTRACE=1"
if not defined WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS set "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222"

set "QWENPAW_DEBUG_DIR=%QWENPAW_WORKING_DIR%"
if not defined QWENPAW_DEBUG_DIR if defined COPAW_WORKING_DIR set "QWENPAW_DEBUG_DIR=%COPAW_WORKING_DIR%"
if not defined QWENPAW_DEBUG_DIR if exist "%USERPROFILE%\.copaw" set "QWENPAW_DEBUG_DIR=%USERPROFILE%\.copaw"
if not defined QWENPAW_DEBUG_DIR set "QWENPAW_DEBUG_DIR=%USERPROFILE%\.qwenpaw"
set "QWENPAW_BACKEND_LOGS=%QWENPAW_DEBUG_DIR%\desktop.log;%QWENPAW_DEBUG_DIR%\qwenpaw.log"
set "QWENPAW_SHELL_LOGS=%LOCALAPPDATA%\io.agentscope.qwenpaw.desktop\logs\qwenpaw-desktop.log;%LOCALAPPDATA%\com.qwenpaw.desktop\logs\qwenpaw-desktop.log"

echo ====================================
echo QwenPaw Desktop - Debug Mode
echo ====================================
echo Log level: %QWENPAW_LOG_LEVEL%
echo Working directory: %QWENPAW_DEBUG_DIR%
echo Press Ctrl+C to stop watching logs.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0qwenpaw-desktop-debug.ps1"
