!macro QWENPAW_STOP_BACKEND_SIDECAR
  ; The Python backend is a Tauri sidecar, not a user-facing window. If it is
  ; left behind during update/uninstall, stop only the copy under $INSTDIR and
  ; wait for the PyInstaller backend bundle to release its file handles.
  ; The script is unpacked to NSIS' temporary plugin directory. Bypass is scoped
  ; to this unsigned local installer helper so user PowerShell policy is not
  ; permanently changed.
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-stop-backend-sidecar.ps1 "..\..\..\..\nsis\stop-backend-sidecar.ps1"
  nsExec::ExecToStack `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\qwenpaw-stop-backend-sidecar.ps1" -InstallDir "$INSTDIR"`
  Pop $0
  Pop $1
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
!macroend
