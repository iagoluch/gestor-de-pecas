# Instala em silencio os pre-requisitos da secao 3 do LEIA-ME (Python, PostgreSQL, nginx,
# NSSM, ODBC 18, PowerShell 7) numa VM limpa. Opcional: quem ja instalou a mao pula este
# script. A senha do postgres e gerada aqui, vai para ..\..\postgres-senha.txt (so
# Administradores e SYSTEM) e o instalar_vm.ps1 a le de la sem perguntar. Reexecutar e
# seguro: componente ja instalado e pulado. Versoes fixas: atualize as URLs quando envelhecerem.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Pacote = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SenhaArq = "$Pacote\postgres-senha.txt"
$Baixas = "$env:TEMP\gestor-prerequisitos"
New-Item -ItemType Directory -Force $Baixas | Out-Null

function Passo([string]$t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Baixar([string]$url, [string]$nome) {
    $destino = "$Baixas\$nome"
    if (-not (Test-Path $destino)) {
        curl.exe -fsSL --retry 3 -o "$destino.part" $url
        if ($LASTEXITCODE) { throw "Download falhou ($LASTEXITCODE): $url" }
        Move-Item "$destino.part" $destino
    }
    $destino
}
function Instalar([string]$exe, [string[]]$argumentos) {
    $p = Start-Process $exe -ArgumentList $argumentos -Wait -PassThru
    if ($p.ExitCode -notin 0, 3010) { throw "$exe saiu com codigo $($p.ExitCode)" }
}
function Adicionar-PathMaquina([string]$pasta) {
    $atual = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if (($atual -split ";") -notcontains $pasta) { [Environment]::SetEnvironmentVariable("Path", "$atual;$pasta", "Machine") }
}

Passo "Python 3.14 (todos os usuarios)"
if (-not (Test-Path "C:\Program Files\Python314\python.exe")) {
    Instalar (Baixar "https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.exe" "python.exe") @(
        "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_launcher=1", "InstallLauncherAllUsers=1", "Include_test=0")
}

Passo "PostgreSQL 17 (leva ~20 min numa VM de 2 vCPU)"
if (-not (Test-Path "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe")) {
    $b = New-Object byte[] 18; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    Set-Content $SenhaArq (-join ($b | ForEach-Object { $_.ToString("x2") })) -Encoding ASCII
    icacls $SenhaArq /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" /Q | Out-Null
    # ponytail: a senha passa pela linha de comando do instalador por alguns minutos; aceitavel
    # numa VM recem-criada so com o admin logado. Trocar por --optionfile se isso incomodar.
    Instalar (Baixar "https://get.enterprisedb.com/postgresql/postgresql-17.11-1-windows-x64.exe" "postgresql.exe") @(
        "--mode", "unattended", "--unattendedmodeui", "none", "--superpassword", (Get-Content $SenhaArq),
        "--serverport", "5432", "--disable-components", "pgAdmin,stackbuilder")
}

Passo "nginx"
if (-not (Test-Path "C:\nginx\nginx.exe")) {
    tar.exe -xf (Baixar "https://nginx.org/download/nginx-1.30.5.zip" "nginx.zip") -C C:\
    Rename-Item "C:\nginx-1.30.5" "C:\nginx"
}

Passo "NSSM"
if (-not (Test-Path "C:\tools\nssm\nssm.exe")) {
    tar.exe -xf (Baixar "https://nssm.cc/release/nssm-2.24.zip" "nssm.zip") -C $Baixas
    New-Item -ItemType Directory -Force "C:\tools\nssm" | Out-Null
    Copy-Item "$Baixas\nssm-2.24\win64\nssm.exe" "C:\tools\nssm\"
}
Adicionar-PathMaquina "C:\tools\nssm"

Passo "ODBC Driver 18 for SQL Server (aceita a licenca da Microsoft)"
if (-not (Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server" -ErrorAction SilentlyContinue)) {
    Instalar "msiexec.exe" @("/i", (Baixar "https://go.microsoft.com/fwlink/?linkid=2280794" "msodbcsql.msi"),
        "/qn", "IACCEPTMSODBCSQLLICENSETERMS=YES")
}

Passo "PowerShell 7"
if (-not (Test-Path "C:\Program Files\PowerShell\7\pwsh.exe")) {
    Instalar "msiexec.exe" @("/i", (Baixar "https://github.com/PowerShell/PowerShell/releases/download/v7.6.6/PowerShell-7.6.6-win-x64.msi" "pwsh.msi"),
        "/qn", "ADD_PATH=1")
}

Write-Host "`nPre-requisitos prontos. Abra um PowerShell NOVO como Administrador (PATH atualizado) e rode instalar_vm.ps1." -ForegroundColor Green
if (Test-Path $SenhaArq) { Write-Host "Guarde a senha do postgres ($SenhaArq) num cofre antes de apagar C:\instalacao." }
