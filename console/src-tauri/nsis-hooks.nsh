!include LogicLib.nsh

!macro QWENPAW_UPDATE_CLI_PATH ACTION
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-update-path.ps1 "..\..\..\..\nsis\update-qwenpaw-path.ps1"
  nsExec::ExecToStack `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\qwenpaw-update-path.ps1" -Action "${ACTION}" -Path "$INSTDIR\binaries\qwenpaw-backend"`
  Pop $0
  Pop $1
!macroend

!macro QWENPAW_REMOVE_CLI_PATH
  !insertmacro QWENPAW_UPDATE_CLI_PATH "Remove"
  ${If} $0 != 0
    DetailPrint "$(qwenpawCliPathUpdateFailed)"
    DetailPrint "$1"
  ${EndIf}
!macroend

!macro QWENPAW_STOP_BACKEND_SIDECAR
  ; The Python backend is a Tauri sidecar, not a user-facing window. A leftover
  ; (possibly orphaned, see #5550) backend keeps its PyInstaller ``.pyd`` modules
  ; memory-mapped, which locks them on Windows. The installer then fails to
  ; overwrite those files and shows the cryptic native "can't write file"
  ; abort/retry/ignore dialog.
  ;
  ; The helper stops only backend processes whose executable lives under
  ; $INSTDIR, so a coexisting QwenPaw install is left untouched. It is
  ; ConstrainedLanguage-safe (WDAC/AppLocker): no ``[System.*]`` static calls,
  ; which throw in that mode and made the previous helper give up silently. It
  ; exits non-zero while a scoped backend is still running; if that persists we
  ; surface a friendly retry prompt rather than the raw OS dialog.
  Push $0
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-stop-backend-sidecar.ps1 "..\..\..\..\nsis\stop-backend-sidecar.ps1"
  ${Do}
    nsExec::Exec `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\qwenpaw-stop-backend-sidecar.ps1" -InstallDir "$INSTDIR"`
    Pop $0
    ${If} $0 == 0
      ${ExitDo}
    ${EndIf}
    ; Still running (or could not be stopped). Ask the user; default to Cancel
    ; for silent installs.
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(qwenpawStopBackendPrompt)" /SD IDCANCEL IDRETRY +2
    Quit
  ${Loop}
  Pop $0
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
!macroend

!macro NSIS_HOOK_POSTINSTALL
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
  !insertmacro QWENPAW_REMOVE_CLI_PATH
!macroend
