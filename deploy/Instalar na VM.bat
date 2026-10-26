@echo off
rem Duplo clique na VM: pede Administrador sozinho e roda o instalador sem depender da politica de scripts.
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath cmd -ArgumentList /c \"\"%~f0\"\"" & exit /b)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
pause
