@echo off
rem Abre o OpenCode (Nemotron) com interface, isolado no WSL, num worktree limpo de origin/master.
rem Cole ali o prompt do Claude. Ao sair (Ctrl+C / /exit), o patch vai para ..\nemo-<data-hora>.patch
setlocal
set "BASH=C:\Users\iago.luchtenberg\AppData\Local\Programs\Git\usr\bin\bash.exe"
cd /d "%~dp0.."
set "MSYS_NO_PATHCONV=1"
wsl.exe -d Ubuntu-24.04 -u nemo -- bash -c "cat > /tmp/nemo-tela.json" < opencode.json
"%BASH%" -c "tr -d '\r' < scripts/nemo-tela.sh | wsl.exe -d Ubuntu-24.04 -u nemo -- bash -c 'cat > ~/nemo-tela.sh'"
wsl.exe -d Ubuntu-24.04 -u nemo --cd ~ -- bash ~/nemo-tela.sh
for /f %%s in ('wsl.exe -d Ubuntu-24.04 -u nemo -- cat /tmp/nemo-tela.slug') do set "SLUG=%%s"
wsl.exe -d Ubuntu-24.04 -u nemo -- cat /tmp/nemo-tela.patch > "..\nemo-%SLUG%.patch"
echo.
echo Patch salvo em ..\nemo-%SLUG%.patch  -  avise o Claude para revisar e aplicar.
pause
