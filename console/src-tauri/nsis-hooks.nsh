!include LogicLib.nsh
!include nsDialogs.nsh

Var QwenPawCliPathCheckbox
Var QwenPawCliPathState

Page custom QWENPAW_CLI_PATH_PAGE QWENPAW_CLI_PATH_PAGE_LEAVE

!macro QWENPAW_UPDATE_CLI_PATH ACTION
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-update-path.ps1 "..\..\..\..\nsis\update-qwenpaw-path.ps1"
  nsExec::ExecToStack `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\qwenpaw-update-path.ps1" -Action "${ACTION}" -Path "$INSTDIR\binaries\qwenpaw-backend"`
  Pop $0
  Pop $1
!macroend

!macro QWENPAW_ADD_CLI_PATH_IF_SELECTED
  ${If} $QwenPawCliPathState == 0
    DetailPrint "$(qwenpawCliPathSkipped)"
  ${Else}
    IfFileExists "$INSTDIR\binaries\qwenpaw-backend\qwenpaw.exe" 0 qwenpaw_cli_path_missing
    !insertmacro QWENPAW_UPDATE_CLI_PATH "Add"
    ${If} $0 == 0
      DetailPrint "$(qwenpawCliPathAdded)"
    ${Else}
      DetailPrint "$(qwenpawCliPathUpdateFailed)"
      DetailPrint "$1"
    ${EndIf}
    Goto qwenpaw_cli_path_done
    qwenpaw_cli_path_missing:
      DetailPrint "$(qwenpawCliPathMissing)"
    qwenpaw_cli_path_done:
  ${EndIf}
!macroend

!macro QWENPAW_REMOVE_CLI_PATH
  !insertmacro QWENPAW_UPDATE_CLI_PATH "Remove"
  ${If} $0 != 0
    DetailPrint "$(qwenpawCliPathUpdateFailed)"
    DetailPrint "$1"
  ${EndIf}
!macroend

Function QWENPAW_CLI_PATH_PAGE
  ${GetOptions} $CMDLINE "/NO_QWENPAW_PATH" $0
  ${IfNot} ${Errors}
    StrCpy $QwenPawCliPathState 0
    Abort
  ${EndIf}

  ${GetOptions} $CMDLINE "/P" $0
  ${IfNot} ${Errors}
    StrCpy $QwenPawCliPathState 1
    Abort
  ${EndIf}

  ${If} ${Silent}
    StrCpy $QwenPawCliPathState 1
    Abort
  ${EndIf}

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  !insertmacro MUI_HEADER_TEXT "$(qwenpawCliPathPageTitle)" "$(qwenpawCliPathPageSubtitle)"
  ${NSD_CreateLabel} 0 0 100% 28u "$(qwenpawCliPathPageDescription)"
  Pop $0
  ${NSD_CreateCheckbox} 0 44u 100% 12u "$(qwenpawCliPathCheckbox)"
  Pop $QwenPawCliPathCheckbox

  ${If} $QwenPawCliPathState == 0
    SendMessage $QwenPawCliPathCheckbox ${BM_SETCHECK} 0 0
  ${Else}
    SendMessage $QwenPawCliPathCheckbox ${BM_SETCHECK} 1 0
  ${EndIf}

  nsDialogs::Show
FunctionEnd

Function QWENPAW_CLI_PATH_PAGE_LEAVE
  ${NSD_GetState} $QwenPawCliPathCheckbox $QwenPawCliPathState
FunctionEnd

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
  !insertmacro QWENPAW_ADD_CLI_PATH_IF_SELECTED
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro QWENPAW_STOP_BACKEND_SIDECAR
  !insertmacro QWENPAW_REMOVE_CLI_PATH
!macroend
