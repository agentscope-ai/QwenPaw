; boostclaw desktop NSIS installer. Run makensis from repo root after
; building dist/win-unpacked (see scripts/pack/build_win.ps1).
; Usage: makensis /DCOPAW_VERSION=1.2.3 /DOUTPUT_EXE=dist\boostclaw-setup-1.2.3.exe scripts\pack\boostclaw_desktop.nsi

!include "MUI2.nsh"
!define MUI_ABORTWARNING
; Use custom icon from unpacked env (copied by build_win.ps1)
!define MUI_ICON "${UNPACKED}\icon.ico"
!define MUI_UNICON "${UNPACKED}\icon.ico"

!define APP_SLUG "boostclaw"
!define APP_DISPLAY_NAME "BoostClaw Desktop"
!define APP_STARTMENU_DIR "BoostClaw"

!ifndef COPAW_VERSION
  !define COPAW_VERSION "0.0.0"
!endif
!ifndef OUTPUT_EXE
  !define OUTPUT_EXE "dist\boostclaw-setup-${COPAW_VERSION}.exe"
!endif

Name "${APP_DISPLAY_NAME}"
OutFile "${OUTPUT_EXE}"
InstallDir "$LOCALAPPDATA\${APP_SLUG}"
InstallDirRegKey HKCU "Software\${APP_SLUG}" "InstallPath"
RequestExecutionLevel user

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

; Pass /DUNPACKED=full_path from build_win.ps1 so path works when cwd != repo root
!ifndef UNPACKED
  !define UNPACKED "dist\win-unpacked"
!endif

Section "${APP_DISPLAY_NAME}" SEC01
  SetOutPath "$INSTDIR"
  File /r /x "*.pyc" /x "__pycache__" "${UNPACKED}\*.*"
  WriteRegStr HKCU "Software\${APP_SLUG}" "InstallPath" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Start Menu folder
  CreateDirectory "$SMPROGRAMS\${APP_STARTMENU_DIR}"

  ; Main shortcut - uses VBS to hide console window
  CreateShortcut "$SMPROGRAMS\${APP_STARTMENU_DIR}\${APP_DISPLAY_NAME}.lnk" "$INSTDIR\boostclaw desktop.vbs" "" "$INSTDIR\icon.ico" 0
  CreateShortcut "$DESKTOP\${APP_DISPLAY_NAME}.lnk" "$INSTDIR\boostclaw desktop.vbs" "" "$INSTDIR\icon.ico" 0
  
  ; Debug shortcut - shows console window for troubleshooting
  CreateShortcut "$SMPROGRAMS\${APP_STARTMENU_DIR}\${APP_DISPLAY_NAME} (Debug).lnk" "$INSTDIR\boostclaw desktop (Debug).bat" "" "$INSTDIR\icon.ico" 0
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\${APP_STARTMENU_DIR}\${APP_DISPLAY_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_STARTMENU_DIR}\${APP_DISPLAY_NAME} (Debug).lnk"
  RMDir "$SMPROGRAMS\${APP_STARTMENU_DIR}"
  Delete "$DESKTOP\${APP_DISPLAY_NAME}.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\${APP_SLUG}"
SectionEnd
