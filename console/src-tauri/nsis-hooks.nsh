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

!macro QWENPAW_INSTALL_DEBUG_LAUNCHER
  SetOutPath "$INSTDIR"
  File /oname=qwenpaw-desktop-debug.cmd "..\..\..\..\nsis\qwenpaw-desktop-debug.cmd"
  File /oname=qwenpaw-desktop-debug.ps1 "..\..\..\..\nsis\qwenpaw-desktop-debug.ps1"
  CreateShortcut "$SMPROGRAMS\QwenPaw Desktop (Debug).lnk" "$INSTDIR\qwenpaw-desktop-debug.cmd" "" "$INSTDIR\qwenpaw-desktop.exe" 0
!macroend

!macro QWENPAW_REMOVE_DEBUG_LAUNCHER
  Delete "$SMPROGRAMS\QwenPaw Desktop (Debug).lnk"
  Delete "$INSTDIR\qwenpaw-desktop-debug.cmd"
  Delete "$INSTDIR\qwenpaw-desktop-debug.ps1"
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

!macro QWENPAW_DEFINE_INSTALL_FUNCTIONS PREFIX
Function ${PREFIX}QWENPAW_RESTORE_INSTALL_STATE
  Push $0
  Push $1
  IfFileExists "$PLUGINSDIR\qwenpaw-manage-install-processes.ps1" 0 qwenpaw_restore_done
  nsExec::ExecToStack `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\qwenpaw-manage-install-processes.ps1" -InstallDir "$INSTDIR" -Action Restore`
  Pop $0
  Pop $1
  ${If} $0 != 0
    DetailPrint "$(qwenpawRestoreInstallStateFailed)"
    DetailPrint "$1"
  ${EndIf}
  qwenpaw_restore_done:
  Pop $1
  Pop $0
FunctionEnd

Function ${PREFIX}QWENPAW_PREPARE_INSTALL
  Push $0
  Push $1
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-manage-install-processes.ps1 "..\..\..\..\nsis\manage-install-processes.ps1"

  qwenpaw_prepare_retry:
  nsExec::ExecToStack `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\qwenpaw-manage-install-processes.ps1" -InstallDir "$INSTDIR"`
  Pop $0
  Pop $1
  ${If} $0 == 0
    Goto qwenpaw_prepare_done
  ${Else}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(qwenpawStopProcessesPrompt)$\n$\n$1" /SD IDCANCEL IDRETRY qwenpaw_prepare_retry IDCANCEL qwenpaw_prepare_cancel
  ${EndIf}

  qwenpaw_prepare_cancel:
  Call ${PREFIX}QWENPAW_RESTORE_INSTALL_STATE
  Quit

  qwenpaw_prepare_done:
  Pop $1
  Pop $0
FunctionEnd
!macroend

!insertmacro QWENPAW_DEFINE_INSTALL_FUNCTIONS ""
!insertmacro QWENPAW_DEFINE_INSTALL_FUNCTIONS "un."

!macro NSIS_HOOK_PREINSTALL
  Call QWENPAW_PREPARE_INSTALL
!macroend

!macro NSIS_HOOK_POSTINSTALL
  Call QWENPAW_RESTORE_INSTALL_STATE
  !insertmacro QWENPAW_ADD_CLI_PATH_IF_SELECTED
  !insertmacro QWENPAW_INSTALL_DEBUG_LAUNCHER
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  Call un.QWENPAW_PREPARE_INSTALL
  !insertmacro QWENPAW_REMOVE_DEBUG_LAUNCHER
  !insertmacro QWENPAW_REMOVE_CLI_PATH
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Call un.QWENPAW_RESTORE_INSTALL_STATE
!macroend
