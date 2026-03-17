; boostpaw desktop NSIS installer. Run makensis from repo root after
; building dist/win-unpacked (see scripts/pack/build_win.ps1).
; Usage: makensis /DCOPAW_VERSION=1.2.3 /DOUTPUT_EXE=dist\boostpaw-setup-1.2.3.exe scripts\pack\copaw_desktop.nsi

!include "MUI2.nsh"
!define MUI_ABORTWARNING
; Use custom icon from unpacked env (copied by build_win.ps1)
!define MUI_ICON "${UNPACKED}\icon.ico"
!define MUI_UNICON "${UNPACKED}\icon.ico"

!ifndef COPAW_VERSION
  !define COPAW_VERSION "0.0.0"
!endif
!ifndef OUTPUT_EXE
  !define OUTPUT_EXE "dist\boostpaw-setup-${COPAW_VERSION}.exe"
!endif

Name "boostpaw desktop"
OutFile "${OUTPUT_EXE}"
InstallDir "$LOCALAPPDATA\boostpaw"
InstallDirRegKey HKCU "Software\boostpaw" "InstallPath"
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

Section "boostpaw desktop" SEC01
  SetOutPath "$INSTDIR"
  File /r /x "*.pyc" /x "__pycache__" "${UNPACKED}\*.*"
  WriteRegStr HKCU "Software\boostpaw" "InstallPath" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Main shortcut - uses VBS to hide console window
  CreateShortcut "$SMPROGRAMS\boostpaw desktop.lnk" "$INSTDIR\boostpaw desktop.vbs" "" "$INSTDIR\icon.ico" 0
  CreateShortcut "$DESKTOP\boostpaw desktop.lnk" "$INSTDIR\boostpaw desktop.vbs" "" "$INSTDIR\icon.ico" 0
  
  ; Debug shortcut - shows console window for troubleshooting
  CreateShortcut "$SMPROGRAMS\boostpaw desktop (Debug).lnk" "$INSTDIR\boostpaw desktop (Debug).bat" "" "$INSTDIR\icon.ico" 0
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\boostpaw desktop.lnk"
  Delete "$SMPROGRAMS\boostpaw desktop (Debug).lnk"
  Delete "$DESKTOP\boostpaw desktop.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\boostpaw"
SectionEnd
