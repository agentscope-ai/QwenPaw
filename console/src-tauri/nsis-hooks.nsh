!macro QWENPAW_CHECK_RUNNING_HELPERS
  !insertmacro CheckIfAppIsRunning "qwenpaw-backend.exe" "QwenPaw Desktop"
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro QWENPAW_CHECK_RUNNING_HELPERS
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro QWENPAW_CHECK_RUNNING_HELPERS
!macroend
