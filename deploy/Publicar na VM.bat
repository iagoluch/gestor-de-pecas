@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publicar_na_vm.ps1" %*
pause
