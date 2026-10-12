@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
if not exist "%~dp0vector-range.exe" (
  echo Put this launcher beside vector-range.exe in the fully extracted preview folder.
  pause
  exit /b 1
)
echo DX12 / Immediate / GPU timestamps requested
echo Run only one game instance at a time.
"%~dp0vector-range.exe" --renderer=dx12 --no-update --present-mode=immediate --gpu-timestamps
set "GAME_EXIT=%ERRORLEVEL%"
if not "%GAME_EXIT%"=="0" (
  echo Game exited with code %GAME_EXIT%. Keep the error above for the report.
  pause
)
exit /b %GAME_EXIT%
