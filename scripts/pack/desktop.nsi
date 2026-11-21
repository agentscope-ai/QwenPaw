; QwenPaw Desktop NSIS installer. Run makensis from repo root after
; building dist/win-unpacked (see scripts/pack/build_win.ps1).
; Usage: makensis /DQWENPAW_VERSION=1.2.3 /DOUTPUT_EXE=dist\QwenPaw-Setup-1.2.3.exe scripts\pack\desktop.nsi

!include "MUI2.nsh"
!include "LogicLib.nsh"
!define MUI_ABORTWARNING
; Use custom icon from unpacked env (copied by build_win.ps1)
!define MUI_ICON "${UNPACKED}\icon.ico"
!define MUI_UNICON "${UNPACKED}\icon.ico"

; WebView2 Runtime detection — GUID kept in sync with desktop_cmd.py (#3119)
!define WEBVIEW2_GUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define WEBVIEW2_BOOTSTRAPPER_URL "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

!ifndef QWENPAW_VERSION
  !define QWENPAW_VERSION "0.0.0"
!endif
!ifndef OUTPUT_EXE
  !define OUTPUT_EXE "dist\QwenPaw-Setup-${QWENPAW_VERSION}.exe"
!endif

Name "QwenPaw Desktop"
OutFile "${OUTPUT_EXE}"
InstallDir "$LOCALAPPDATA\QwenPaw"
InstallDirRegKey HKCU "Software\QwenPaw" "InstallPath"
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

; ---------------------------------------------------------------------------
; WebView2 Runtime: detect via registry, download + install if missing.
; The bootstrapper (~1.8 MB) supports per-user install — no admin needed.
; ---------------------------------------------------------------------------
Function _DetectWebView2
  ; Check HKLM 64-bit registry view
  SetRegView 64
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
  ${If} $0 != ""
  ${AndIf} $0 != "0.0.0.0"
    SetRegView lastused
    StrCpy $1 "1"
    Return
  ${EndIf}

  ; Check HKLM 32-bit registry view
  SetRegView 32
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
  ${If} $0 != ""
  ${AndIf} $0 != "0.0.0.0"
    SetRegView lastused
    StrCpy $1 "1"
    Return
  ${EndIf}
  SetRegView lastused

  ; Check HKCU (not affected by registry redirection)
  ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WEBVIEW2_GUID}" "pv"
  ${If} $0 != ""
  ${AndIf} $0 != "0.0.0.0"
    StrCpy $1 "1"
    Return
  ${EndIf}

  StrCpy $1 "0"
FunctionEnd

; Hidden section (runs automatically, not shown in component list)
Section "-WebView2"
  Call _DetectWebView2
  ${If} $1 == "1"
    DetailPrint "WebView2 Runtime already installed ($0), skipping."
    Goto webview2_done
  ${EndIf}

  DetailPrint "WebView2 Runtime not found, downloading bootstrapper..."
  NSISdl::download "${WEBVIEW2_BOOTSTRAPPER_URL}" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
  Pop $0
  ${If} $0 == "success"
    DetailPrint "Installing WebView2 Runtime (this may take a moment)..."
    ExecWait '"$TEMP\MicrosoftEdgeWebview2Setup.exe" /silent /install' $0
    Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
    ; Verify actual installation instead of relying solely on exit code
    Call _DetectWebView2
    ${If} $1 == "1"
      DetailPrint "WebView2 Runtime installed successfully (version $0)."
    ${Else}
      DetailPrint "WebView2 not detected after install (exit code $0)"
      MessageBox MB_YESNO|MB_ICONEXCLAMATION \
        "WebView2 运行时安装未成功。$\n$\n\
缺少 WebView2 将导致 QwenPaw Desktop 启动后白屏，无法正常使用。$\n$\n\
是否仍要继续安装 QwenPaw？$\n\
（选择「否」将终止安装）" \
        IDYES webview2_cont_inst
      Abort
      webview2_cont_inst:
      StrCpy $R9 "1"
    ${EndIf}
  ${Else}
    Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
    MessageBox MB_YESNO|MB_ICONEXCLAMATION \
      "WebView2 运行时下载失败（$0）。$\n$\n\
缺少 WebView2 将导致 QwenPaw Desktop 启动后白屏，无法正常使用。$\n$\n\
是否仍要继续安装 QwenPaw？$\n\
（选择「否」将终止安装）" \
      IDYES webview2_cont_dl
    Abort
    webview2_cont_dl:
    StrCpy $R9 "1"
  ${EndIf}

  webview2_done:
SectionEnd

Section "QwenPaw Desktop" SEC01
  SetOutPath "$INSTDIR"
  File /r "${UNPACKED}\*.*"
  WriteRegStr HKCU "Software\QwenPaw" "InstallPath" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Main shortcut - uses VBS to hide console window
  CreateShortcut "$SMPROGRAMS\QwenPaw Desktop.lnk" "$INSTDIR\QwenPaw Desktop.vbs" "" "$INSTDIR\icon.ico" 0
  CreateShortcut "$DESKTOP\QwenPaw Desktop.lnk" "$INSTDIR\QwenPaw Desktop.vbs" "" "$INSTDIR\icon.ico" 0

  ; Debug shortcut - shows console window for troubleshooting
  CreateShortcut "$SMPROGRAMS\QwenPaw Desktop (Debug).lnk" "$INSTDIR\QwenPaw Desktop (Debug).bat" "" "$INSTDIR\icon.ico" 0

  ; Remind user only if auto-install failed AND WebView2 is still missing
  ${If} $R9 == "1"
    Call _DetectWebView2
    ${If} $1 == "0"
      MessageBox MB_OK|MB_ICONINFORMATION \
        "安装完成！$\n$\n\
提醒：您的系统缺少 WebView2 运行时，QwenPaw Desktop 暂时无法正常使用。$\n$\n\
请前往以下地址下载安装：$\n\
https://developer.microsoft.com/zh-cn/microsoft-edge/webview2/$\n$\n\
安装 WebView2 后即可正常使用 QwenPaw Desktop。"
    ${EndIf}
  ${EndIf}
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\QwenPaw Desktop.lnk"
  Delete "$SMPROGRAMS\QwenPaw Desktop (Debug).lnk"
  Delete "$DESKTOP\QwenPaw Desktop.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\QwenPaw"
SectionEnd
