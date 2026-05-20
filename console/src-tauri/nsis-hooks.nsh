!macro QWENPAW_STOP_BACKEND_SIDECAR
  ; The Python backend is a Tauri sidecar, not a user-facing window. If it is
  ; left behind during update/uninstall, stop only the copy under $INSTDIR and
  ; wait for the PyInstaller backend bundle to release its file handles.
  nsExec::ExecToStack `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$$ErrorActionPreference = 'SilentlyContinue'; $$installDir = [System.IO.Path]::GetFullPath('$INSTDIR').TrimEnd('\') + '\'; $$targets = Get-CimInstance Win32_Process -Filter \"Name = 'qwenpaw-backend.exe'\" | Where-Object { $$_.ExecutablePath -and [System.IO.Path]::GetFullPath($$_.ExecutablePath).StartsWith($$installDir, [System.StringComparison]::OrdinalIgnoreCase) }; $$ids = @($$targets | ForEach-Object { $$_.ProcessId }); $$ids | ForEach-Object { Stop-Process -Id $$_ -Force }; if ($$ids.Count -gt 0) { Wait-Process -Id $$ids -Timeout 8 }"`
  Pop $0
  Pop $1
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
!macroend
