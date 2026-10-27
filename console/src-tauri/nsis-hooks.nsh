!include LogicLib.nsh
!include nsDialogs.nsh

Var QwenPawCliPathCheckbox
Var QwenPawCliPathState
Var QwenPawInstallLog

Page custom QWENPAW_CLI_PATH_PAGE QWENPAW_CLI_PATH_PAGE_LEAVE

; Keep diagnostics outside $PLUGINSDIR so they survive cancellation/uninstall,
; including failures before PowerShell can start. Logging must not block setup.
!macro QWENPAW_WRITE_INSTALL_LOG TEXT
  Push $9
  ${If} $QwenPawInstallLog != ""
    ClearErrors
    FileOpen $9 "$QwenPawInstallLog" a
    ${IfNot} ${Errors}
      FileSeek $9 0 END
      FileWriteUTF16LE $9 `${TEXT}$\r$\n`
      FileClose $9
    ${EndIf}
  ${EndIf}
  Pop $9
!macroend

!macro QWENPAW_EXEC_POWERSHELL SCRIPT ARGUMENTS
  ${If} $QwenPawInstallLog == ""
    Push $9
    System::Call 'kernel32::GetCurrentProcessId() i .r0'
    StrCpy $QwenPawInstallLog "$TEMP\qwenpaw-installer-$0.log"
    ClearErrors
    FileOpen $9 "$QwenPawInstallLog" w
    ${If} ${Errors}
      DetailPrint "Cannot create installer log: $QwenPawInstallLog"
      StrCpy $QwenPawInstallLog ""
    ${Else}
      FileWriteWord $9 0xFEFF
      FileClose $9
      DetailPrint "$(qwenpawInstallLogLocation)"
    ${EndIf}
    Pop $9
  ${EndIf}
  !insertmacro QWENPAW_WRITE_INSTALL_LOG `PowerShell: $SYSDIR\WindowsPowerShell\v1.0\powershell.exe`
  !insertmacro QWENPAW_WRITE_INSTALL_LOG `Script: ${SCRIPT}; install directory: $INSTDIR`
  !insertmacro QWENPAW_WRITE_INSTALL_LOG `Arguments: ${ARGUMENTS}`
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\${SCRIPT}" ${ARGUMENTS}`
  Pop $0
  Pop $1
  !insertmacro QWENPAW_WRITE_INSTALL_LOG `Result: $0$\r$\n$1`
  DetailPrint "${SCRIPT}: $0"
!macroend

!macro QWENPAW_UPDATE_CLI_PATH ACTION
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-update-path.ps1 "..\..\..\..\nsis\update-qwenpaw-path.ps1"
  !insertmacro QWENPAW_EXEC_POWERSHELL "qwenpaw-update-path.ps1" `-Action "${ACTION}" -Path "$INSTDIR\binaries\qwenpaw-backend"`
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
  !insertmacro QWENPAW_EXEC_POWERSHELL "qwenpaw-manage-install-processes.ps1" `-InstallDir "$INSTDIR" -Action Restore -LogPath "$QwenPawInstallLog"`
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
  Push $2
  Push $3
  InitPluginsDir
  File /oname=$PLUGINSDIR\qwenpaw-manage-install-processes.ps1 "..\..\..\..\nsis\manage-install-processes.ps1"
  System::Call 'kernel32::GetCurrentProcessId() i .r2'

  qwenpaw_prepare_retry:
  !insertmacro QWENPAW_EXEC_POWERSHELL "qwenpaw-manage-install-processes.ps1" `-InstallDir "$INSTDIR" -NsisProcessId $2 -LogPath "$QwenPawInstallLog"`
  ${If} $0 == 0
    Goto qwenpaw_prepare_done
  ${Else}
    StrCpy $3 "$(qwenpawPrepareInstallFailed)$\n$\n$(qwenpawInstallResult)"
    ${If} $QwenPawInstallLog != ""
      StrCpy $3 "$3$\n$\n$(qwenpawInstallLogLocation)"
    ${EndIf}
    StrCpy $3 "$3$\n$\n$1"
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$3" /SD IDCANCEL IDRETRY qwenpaw_prepare_retry IDCANCEL qwenpaw_prepare_cancel
  ${EndIf}

  qwenpaw_prepare_cancel:
  Call ${PREFIX}QWENPAW_RESTORE_INSTALL_STATE
  SetErrorLevel 1
  Quit

  qwenpaw_prepare_done:
  Pop $3
  Pop $2
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
