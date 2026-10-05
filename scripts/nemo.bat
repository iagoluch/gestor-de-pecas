@echo off
rem Arraste um arquivo de prompt (.txt) para este .bat, ou rode: nemo.bat <arquivo-do-prompt>
rem Roda o Nemotron no WSL em worktree isolado e devolve ../nemo-<slug>.patch
setlocal
set "BASH=C:\Users\iago.luchtenberg\AppData\Local\Programs\Git\usr\bin\bash.exe"
if "%~1"=="" (
  echo Arraste o arquivo de prompt para este .bat.
  pause & exit /b 1
)
cd /d "%~dp0.."
set "SLUG=%~n1"
echo [nemo] slug=%SLUG%  prompt=%~1
"%BASH%" -lc "scripts/nemo.sh '%SLUG%' '%~1'"
echo.
echo Pronto. Cole o resultado acima no Claude para revisar o patch.
pause
