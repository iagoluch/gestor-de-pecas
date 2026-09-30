# Instalacao completa da VM num comando so: confere o ambiente, faz no inicio as unicas
# perguntas que faltam (token do runner e pasta externa do backup) e depois roda sem parar:
# instalar_prerequisitos.ps1 -> instalar_vm.ps1 -> instalar_runner.ps1 -> backup diario
# agendado -> apaga o pacote (dump do REAL e chave TLS) -> checklist final.
#
#   powershell -ExecutionPolicy Bypass -File C:\instalacao\gestor-pecas-deploy\app\deploy\instalar.ps1
#
# Reexecutar e seguro: cada script pula o que ja esta feito e nada e perguntado de novo.
[CmdletBinding()]
param(
    [string]$AppDir = "C:\gestor-pecas",
    [string]$BackupDir = "C:\gestor-backup",
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [string]$RunnerDir = "C:\actions-runner",
    [string]$HoraBackup = "02:00",
    [int]$RetencaoDias = 14,
    [switch]$ManterPacote
)
$ErrorActionPreference = "Stop"
$Pacote = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Tarefa = "Gestor de Pecas - backup diario"

function Passo([string]$t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Exigir([bool]$ok, [string]$mensagem) { if (-not $ok) { throw $mensagem } }
function Restringir([string]$pasta) {
    icacls $pasta /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" /Q | Out-Null
    Exigir ($LASTEXITCODE -eq 0) "icacls falhou em $pasta."
}

# --- Checagem previa ----------------------------------------------------------
Passo "Checagem previa"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
Exigir $admin "Rode como Administrador."
foreach ($item in "gestor_pecas.dump", "gestor.env.base", "certs", "app\requirements.lock") {
    Exigir (Test-Path "$Pacote\$item") "Pacote incompleto: falta $Pacote\$item. Remonte com deploy/montar_pacote.py."
}
$livreGb = [math]::Floor((Get-PSDrive C).Free / 1GB)
Exigir ($livreGb -ge 15) "So $livreGb GB livres em C: (minimo 15 GB)."
if ((Get-TimeZone).Id -ne "E. South America Standard Time") {
    Set-TimeZone -Id "E. South America Standard Time"  # turnos e OEE usam o relogio de Brasilia
    Write-Host "Fuso ajustado para Brasilia."
}

# --- Perguntas (so o que falta) -----------------------------------------------
Passo "Perguntas"
$token = $null
if (-not (Test-Path "$RunnerDir\.runner")) {
    Write-Host "Token do runner: GitHub > Settings > Actions > Runners > New self-hosted runner (vale 1 h)."
    $seguro = Read-Host "Token (Enter = instalar o runner depois)" -AsSecureString
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro))
}
New-Item -ItemType Directory -Force $BackupDir | Out-Null
Restringir $BackupDir
$externaArq = "$BackupDir\copia-externa.txt"
if (-not (Test-Path $externaArq)) {
    Write-Host "Copia externa do backup: pasta fora desta VM (ex.: \\servidor\backups\gestor-pecas)."
    Write-Host "A tarefa roda como SYSTEM, que entra na rede como $env:COMPUTERNAME`$: de escrita a essa conta no compartilhamento."
    $externa = (Read-Host "Pasta (Enter = so backup local por enquanto)").Trim()
    if ($externa) {
        Exigir (Test-Path $externa) "Pasta externa $externa inacessivel daqui."
        Set-Content $externaArq $externa -Encoding ASCII
    }
}
Write-Host "Daqui em diante roda sozinho (o PostgreSQL leva ~20 min numa VM pequena)."

# --- Instaladores -------------------------------------------------------------
function Atualizar-Path {
    # O que os instaladores gravaram no PATH da maquina vale ja nesta sessao, sem abrir outro console.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
Passo "1/4 Pre-requisitos"
& "$PSScriptRoot\instalar_prerequisitos.ps1"
Atualizar-Path
Passo "2/4 Aplicacao, banco, nginx e servicos"
& "$PSScriptRoot\instalar_vm.ps1" -AppDir $AppDir -PgBin $PgBin
Atualizar-Path
Passo "3/4 Runner do GitHub Actions"
if (Test-Path "$RunnerDir\.runner") {
    & "$PSScriptRoot\instalar_runner.ps1" -RunnerDir $RunnerDir -AppDir $AppDir  # reaplica as permissoes
} elseif ($token) {
    & "$PSScriptRoot\instalar_runner.ps1" -Token $token -RunnerDir $RunnerDir -AppDir $AppDir
} else {
    Write-Warning "Runner pulado (sem token)."
}
$token = $null

# --- Backup diario ------------------------------------------------------------
Passo "4/4 Backup diario as $HoraBackup (retencao $RetencaoDias dias)"
Copy-Item "$PSScriptRoot\backup_diario.ps1" "$BackupDir\backup_diario.ps1" -Force
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    "-NoProfile -ExecutionPolicy Bypass -File `"$BackupDir\backup_diario.ps1`" -AppDir `"$AppDir`" -PgBin `"$PgBin`" -RetencaoDias $RetencaoDias")
$gatilho = New-ScheduledTaskTrigger -Daily -At $HoraBackup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask $Tarefa -Action $acao -Trigger $gatilho -Principal $principal -Settings $ajustes -Force | Out-Null
# Primeira execucao agora: prova que dump e copia externa funcionam antes de confiar na agenda.
$antes = (Get-ScheduledTaskInfo $Tarefa).LastRunTime
Start-ScheduledTask $Tarefa
$prazo = (Get-Date).AddMinutes(30)
do { Start-Sleep -Seconds 3; $info = Get-ScheduledTaskInfo $Tarefa }
while (($info.LastRunTime -eq $antes -or (Get-ScheduledTask $Tarefa).State -eq "Running") -and (Get-Date) -lt $prazo)
$resultado = $info.LastTaskResult
Exigir ($resultado -eq 0) "Backup de teste falhou (codigo $resultado). Veja $BackupDir\backup.log."

# --- Limpeza do pacote --------------------------------------------------------
$senhaArq = "$Pacote\postgres-senha.txt"
if (Test-Path $senhaArq) {
    # Fora do pacote antes de apaga-lo: DROP DATABASE e manutencao precisam dela.
    Move-Item $senhaArq "$BackupDir\postgres-senha.txt" -Force
}
$runnerOk = Test-Path "$RunnerDir\.runner"
if ($ManterPacote -or -not $runnerOk) {
    Write-Warning "Pacote mantido em $Pacote (dump do REAL e chave TLS). Apague-o depois do runner."
} else {
    Set-Location $env:SystemDrive\
    Remove-Item $Pacote -Recurse -Force
    # Pasta de trabalho do LEIA-ME (zip baixado + pacote extraido): so ela, nunca outra pasta-mae.
    $mae = Split-Path -Parent $Pacote
    if ((Split-Path -Leaf $mae) -eq "instalacao") {
        # Falha se o console que chamou o script esta dentro dela; o que importa (pacote) ja saiu.
        Remove-Item $mae -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $mae) { Write-Warning "$mae em uso: apague-a depois de sair dela (cd \)." }
    }
    Write-Host "Pacote apagado."
}

# --- Checklist ----------------------------------------------------------------
function Item([bool]$ok, [string]$texto) {
    if ($ok) { Write-Host "  [OK]       $texto" -ForegroundColor Green } else { Write-Host "  [PENDENTE] $texto" -ForegroundColor Yellow }
}
$https = & curl.exe -k -s -o NUL -w "%{http_code}" "https://localhost/api/v1/system/ready"
$ultimo = Get-ChildItem "$AppDir\backups" -Filter "diario-*.dump" | Sort-Object LastWriteTime | Select-Object -Last 1
$runner = Get-Service "actions.runner.*" -ErrorAction SilentlyContinue | Select-Object -First 1

Write-Host "`n===================== CHECKLIST =====================" -ForegroundColor Cyan
Item ((Get-Service gestor-pecas).Status -eq "Running") "Servico gestor-pecas rodando"
Item ((Get-Service nginx).Status -eq "Running") "Servico nginx rodando"
Item ($https -eq "200") "https://localhost/api/v1/system/ready responde 200"
Item ($runner -and $runner.Status -eq "Running") "Runner do GitHub Actions ativo (confira 'Idle' no GitHub)"
Item ([bool]$ultimo) "Backup diario agendado as $HoraBackup; ultimo: $(if ($ultimo) { $ultimo.Name })"
Item (Test-Path $externaArq) "Copia externa do backup ($externaArq)"
Item (-not (Test-Path $Pacote)) "Pacote de instalacao apagado"
Item (-not (Test-Path "$BackupDir\postgres-senha.txt")) "Senha do postgres guardada no cofre e apagada de $BackupDir"
Write-Host "  [EXTERNO]  Certificado corporativo no lugar do autoassinado (LEIA-ME secao 8)"
Write-Host "  [EXTERNO]  IP do Protheus na allowlist SOAP, pasta de rede dos desenhos, Telegram (LEIA-ME secao 8)"
Write-Host "=====================================================" -ForegroundColor Cyan
