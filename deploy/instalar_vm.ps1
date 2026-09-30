[CmdletBinding()]
param(
    [string]$AppDir = "C:\gestor-pecas",
    [string]$NginxDir = "C:\nginx",
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [string]$PublicHost = "gestor-peca",
    [string]$Database = "gestor_pecas",
    [string]$DbUser = "gestor_app"
)

# Primeira instalação do Gestor de Peças na VM (Windows Server + PostgreSQL 17
# nativo + nginx + NSSM). Roda uma vez, como Administrador, a partir do pacote
# montado por deploy/montar_pacote.py. Os deploys seguintes são do pipeline
# (.github/workflows/deploy.yml). Reexecutar é seguro: cada passo já feito é
# mantido (banco existente não é restaurado de novo, .env existente não é
# sobrescrito).

$ErrorActionPreference = "Stop"
$Pacote = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Servico = "gestor-pecas"

function Passo([string]$texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }

function Exigir([bool]$ok, [string]$mensagem) { if (-not $ok) { throw $mensagem } }

function Executar([string]$exe, [string[]]$argumentos) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "$exe falhou (código $LASTEXITCODE)." }
}

function Hex-Aleatorio([int]$bytes) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

function Restringir([string]$pasta) {
    # Só Administradores e SYSTEM, herdado por tudo abaixo: .env, backups do REAL e
    # chave TLS. As contas do app e do runner ganham acesso explícito depois.
    Executar icacls @($pasta, "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "/Q")
}

function Gravar-Utf8SemBom([string]$caminho, [string]$texto) {
    # python-dotenv lê o BOM como parte da primeira chave.
    [System.IO.File]::WriteAllText($caminho, $texto, (New-Object System.Text.UTF8Encoding $false))
}

# --- Pré-requisitos -----------------------------------------------------------
Passo "Conferindo pré-requisitos"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
Exigir $admin "Rode este script como Administrador."
Exigir ((Get-TimeZone).Id -eq "E. South America Standard Time") (
    "Fuso da VM não é o de Brasília. Rode: Set-TimeZone -Id 'E. South America Standard Time' e execute de novo.")
Exigir (Test-Path "$Pacote\gestor_pecas.dump") "Dump não encontrado em $Pacote\gestor_pecas.dump."
Exigir (Test-Path "$Pacote\gestor.env.base") "Env base não encontrado em $Pacote\gestor.env.base."
Exigir (Test-Path "$PgBin\pg_restore.exe") "PostgreSQL 17 não encontrado em $PgBin."
Exigir (Test-Path "$NginxDir\nginx.exe") "nginx não encontrado em $NginxDir."
Exigir ([bool](Get-Command nssm -ErrorAction SilentlyContinue)) "nssm.exe não está no PATH."
Exigir ([bool](Get-Command py -ErrorAction SilentlyContinue)) "Python 3.14 (launcher py) não encontrado."
$basePython = & py -3.14 -c "import sys; print(sys.base_prefix)"
Exigir ($LASTEXITCODE -eq 0) "Python 3.14 não encontrado pelo launcher py."
# A .venv aponta para o Python base: no perfil do admin, a conta de serviço e o runner não o leem.
Exigir ($basePython -notlike "C:\Users\*") (
    "Python 3.14 instalado só para o usuário ($basePython). Reinstale marcando 'Install for all users'.")
Exigir ([bool](Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server" -ErrorAction SilentlyContinue)) (
    "Driver ODBC 18 for SQL Server não instalado (necessário para o SigmaNEST).")
if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    Write-Warning "PowerShell 7 (pwsh) ausente: a instalação segue, mas o deploy.yml do pipeline exige pwsh."
}

# pg_dump no PATH da máquina: o deploy.yml faz o backup pré-deploy com ele.
$pathMaquina = [Environment]::GetEnvironmentVariable("Path", "Machine")
if (($pathMaquina -split ";") -notcontains $PgBin) {
    [Environment]::SetEnvironmentVariable("Path", "$pathMaquina;$PgBin", "Machine")
}
$env:Path = "$env:Path;$PgBin"

# --- Código -------------------------------------------------------------------
Passo "Copiando o código para $AppDir"
# /E e não /MIR: dados de runtime, .env e .venv de uma instalação anterior ficam.
# /XD: material de desenvolvimento (mesma lista do scripts/deploy_release.ps1).
robocopy "$Pacote\app" $AppDir /E /NFL /NDL /NJH /NJS `
    /XD docs tests .ai .agents .claude .codex .freebuff .github .impeccable .opencode | Out-Null
Exigir ($LASTEXITCODE -lt 8) "robocopy falhou (código $LASTEXITCODE)."
$Logs = "$AppDir\dados\logs"  # dentro de dados: o /MIR do deploy preserva essa pasta
New-Item -ItemType Directory -Force -Path $Logs, "$AppDir\backups", "$AppDir\dev_reports" | Out-Null
Restringir $AppDir

# --- Banco --------------------------------------------------------------------
Passo "Banco $Database"
$envPath = "$AppDir\.env"
# .env de uma instalação anterior: a senha do app vem dele. Só no formato que este script
# gera (48 hex): o runner escreve no .env e a senha entra no SQL que roda como postgres.
$urlAntiga = if (Test-Path $envPath) {
    Select-String -Path $envPath -Pattern '^DATABASE_URL=postgresql://[^:]+:([0-9a-f]{48})@' | Select-Object -First 1
}
# Reexecução: o próprio usuário do app confere o banco, sem pedir a senha do superusuário.
$bancoPronto = $false
if ($urlAntiga) {
    $env:PGPASSWORD = $urlAntiga.Matches[0].Groups[1].Value
    try { $bancoPronto = (& psql -h 127.0.0.1 -U $DbUser -d $Database -tAc "select 1" 2>$null) -eq "1" } catch { }
    Remove-Item Env:PGPASSWORD
}
if ($bancoPronto) {
    Write-Host "Banco já existe e o .env conecta nele: restore pulado (nada é sobrescrito)."
} else {
    $senhaArq = "$Pacote\postgres-senha.txt"  # gerado pelo instalar_prerequisitos.ps1
    if (Test-Path $senhaArq) {
        $env:PGPASSWORD = (Get-Content $senhaArq -TotalCount 1).Trim()
    } else {
        $senhaPostgres = Read-Host "Senha do superusuário postgres (definida na instalação do PostgreSQL)" -AsSecureString
        $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($senhaPostgres))
    }
    try {
        $existe = & psql -h 127.0.0.1 -U postgres -d postgres -tAc "select 1 from pg_database where datname = '$Database'"
        Exigir ($LASTEXITCODE -eq 0) "Não conectou no PostgreSQL como postgres."
        if ($existe -eq "1") {
            Write-Host "Banco já existe: restore pulado (nada é sobrescrito)."
            Exigir (Test-Path $envPath) (
                "Banco existe mas $envPath não. Para reinstalar do zero: DROP DATABASE $Database (como postgres) e execute de novo.")
        } else {
            # .env anterior (banco apagado para restaurar um dump novo): mantém a senha dele.
            Exigir ($urlAntiga -or -not (Test-Path $envPath)) (
                "DATABASE_URL de $envPath fora do formato gerado (senha de 48 hex): confira o arquivo.")
            $senhaApp = if ($urlAntiga) { $urlAntiga.Matches[0].Groups[1].Value } else { Hex-Aleatorio 24 }
            $temRole = & psql -h 127.0.0.1 -U postgres -d postgres -tAc "select 1 from pg_roles where rolname = '$DbUser'"
            $verbo = if ($temRole -eq "1") { "ALTER" } else { "CREATE" }
            # Pelo stdin: a senha não aparece na linha de comando do processo.
            "$verbo ROLE $DbUser LOGIN PASSWORD '$senhaApp';`nCREATE DATABASE $Database OWNER $DbUser ENCODING 'UTF8' TEMPLATE template0;" |
                & psql -h 127.0.0.1 -U postgres -d postgres -q -v ON_ERROR_STOP=1
            Exigir ($LASTEXITCODE -eq 0) "Falha ao criar o role $DbUser ou o banco $Database."
            $env:PGPASSWORD = $senhaApp
            try {
                Executar pg_restore @("-h", "127.0.0.1", "-U", $DbUser, "-d", $Database,
                    "--no-owner", "--no-acl", "--exit-on-error", "$Pacote\gestor_pecas.dump")
            } catch {
                # Banco pela metade bloquearia a reexecução: o dono o apaga e o erro segue.
                & psql -h 127.0.0.1 -U $DbUser -d postgres -c "DROP DATABASE $Database" | Out-Null
                throw
            }
            $versao = & psql -h 127.0.0.1 -U $DbUser -d $Database -tAc "select max(version) from schema_migrations"
            Write-Host "Restore concluído: schema $versao."
        }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

# --- .env ---------------------------------------------------------------------
Passo "Arquivo .env"
if (Test-Path $envPath) {
    Write-Host ".env já existe: mantido."
} else {
    $ips = @(Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { $_.IPAddress })
    $hosts = @($PublicHost, $env:COMPUTERNAME.ToLower(), "localhost", "127.0.0.1") + $ips | Select-Object -Unique
    $origens = ($hosts | ForEach-Object { "https://$_" }) -join ","
    $maquina = @"

# --- Gerado por deploy/instalar_vm.ps1 em $(Get-Date -Format "yyyy-MM-dd HH:mm") ---
GESTOR_WEB_ENV=production
DATABASE_URL=postgresql://${DbUser}:$senhaApp@127.0.0.1:5432/$Database
GESTOR_EXPECTED_DATABASE=$Database
GESTOR_WEB_SESSION_SECRET=$(Hex-Aleatorio 48)
GESTOR_DEVOBS_SESSION_SECRET=$(Hex-Aleatorio 48)
GESTOR_WEB_COOKIE_SECURE=true
GESTOR_WEB_SERVE_STATIC=true
GESTOR_WEB_PUBLIC_HOST=$PublicHost
GESTOR_WEB_ALLOWED_HOSTS=$($hosts -join ",")
GESTOR_WEB_ALLOWED_ORIGINS=$origens
GESTOR_DEV_OBSERVATORY_ENABLED=false
# Mesmo bot do notebook: ligar (true) só com o app do notebook parado (LEIA-ME §2).
TELEGRAM_ENABLED=false
GESTOR_TELEGRAM_BOT_POLLING_ENABLED=false
GESTOR_TELEGRAM_DIGEST_ENABLED=false
# Pastas de rede com os desenhos das peças (separadas por ;). Vazio = posto sem desenho.
GESTOR_OPERATOR_DRAWING_ROOTS=
"@
    Gravar-Utf8SemBom $envPath ((Get-Content -Raw -Encoding UTF8 "$Pacote\gestor.env.base") + $maquina)
    Write-Host ".env gerado. Hosts aceitos: $($hosts -join ', ')"
}

# --- Python -------------------------------------------------------------------
Passo "Ambiente Python"
# Serviço parado antes do pip: numa reexecução, os .pyd em uso não podem ser sobrescritos.
if (Get-Service $Servico -ErrorAction SilentlyContinue) { Stop-Service $Servico }
# Nada de $AppDir roda como Administrador: o runner escreve lá. A .venv é recriada e o
# lock vem do pacote.
if (Test-Path "$AppDir\.venv") { Remove-Item "$AppDir\.venv" -Recurse -Force }
Executar py @("-3.14", "-m", "venv", "$AppDir\.venv")
Executar "$AppDir\.venv\Scripts\python.exe" @("-m", "pip", "install", "--disable-pip-version-check",
    "--require-hashes", "-r", "$Pacote\app\requirements.lock")

# --- nginx --------------------------------------------------------------------
Passo "nginx (HTTPS)"
New-Item -ItemType Directory -Force -Path "$NginxDir\conf\certs" | Out-Null
Copy-Item "$Pacote\certs\*" "$NginxDir\conf\certs\" -Force
Restringir "$NginxDir\conf\certs"
Copy-Item "$Pacote\app\deploy\nginx.conf" "$NginxDir\conf\nginx.conf" -Force
Push-Location $NginxDir
try { Executar "$NginxDir\nginx.exe" @("-t", "-p", "$NginxDir\") } finally { Pop-Location }

# --- Serviços -----------------------------------------------------------------
Passo "Serviços Windows (NSSM)"
function Registrar-Servico([string]$nome, [string]$exe, [string]$argumentos, [string]$pasta) {
    if (-not (Get-Service $nome -ErrorAction SilentlyContinue)) { Executar nssm @("install", $nome, $exe) }
    else { Stop-Service $nome -ErrorAction SilentlyContinue }
    Executar nssm @("set", $nome, "Application", $exe)
    if ($argumentos) { Executar nssm @("set", $nome, "AppParameters", $argumentos) }
    Executar nssm @("set", $nome, "AppDirectory", $pasta)
    Executar nssm @("set", $nome, "Start", "SERVICE_AUTO_START")
    Executar nssm @("set", $nome, "AppExit", "Default", "Restart")
}
# 127.0.0.1: só o nginx fala com o Uvicorn; 1 processo (schedulers internos).
Registrar-Servico $Servico "$AppDir\.venv\Scripts\python.exe" `
    "-m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000" $AppDir
# Sem UTF-8 mode, um log com caractere fora do cp1252 derruba o print redirecionado.
Executar nssm @("set", $Servico, "AppEnvironmentExtra", "PYTHONUTF8=1")
Executar nssm @("set", $Servico, "AppStdout", "$Logs\gestor-pecas.log")
Executar nssm @("set", $Servico, "AppStderr", "$Logs\gestor-pecas.log")
Executar nssm @("set", $Servico, "AppRotateFiles", "1")
Executar nssm @("set", $Servico, "AppRotateBytes", "10485760")
Executar nssm @("set", $Servico, "AppRotateOnline", "1")  # sem isto, só rotaciona ao reiniciar
# Conta virtual do Windows (sem senha) no lugar de LocalSystem: o app lê o código e o
# .env e só escreve em dados\ e dev_reports\ (backend/api/config.py). Banco e SigmaNEST
# autenticam por usuário/senha.
# Toda conta de serviço herda SeImpersonatePrivilege (grupo SERVICE), que leva a SYSTEM
# por exploits "potato"; o sc privs deixa no token só estes dois, a partir do próximo start.
$Privilegios = "SeChangeNotifyPrivilege/SeCreateGlobalPrivilege"
Executar sc.exe @("config", $Servico, "obj=", "NT SERVICE\$Servico")
Executar sc.exe @("privs", $Servico, $Privilegios)
Executar icacls @($AppDir, "/grant", "NT SERVICE\${Servico}:(OI)(CI)RX", "/Q")
foreach ($pasta in "$AppDir\dados", "$AppDir\dev_reports") {
    Executar icacls @($pasta, "/grant", "NT SERVICE\${Servico}:(OI)(CI)M", "/Q")
}
Registrar-Servico "nginx" "$NginxDir\nginx.exe" "" $NginxDir
# nginx também em conta virtual: o runner regrava o nginx.conf e o reinicia, e como
# LocalSystem um conf adulterado leria ou escreveria qualquer arquivo da VM.
Executar sc.exe @("config", "nginx", "obj=", "NT SERVICE\nginx")
Executar sc.exe @("privs", "nginx", $Privilegios)
Restringir $NginxDir  # sem a herança de C:\, onde Users criam arquivos (DLL plantada)
Executar icacls @($NginxDir, "/grant", "NT SERVICE\nginx:(OI)(CI)RX", "/Q")
Executar icacls @("$NginxDir\conf\certs", "/grant", "NT SERVICE\nginx:(OI)(CI)R", "/Q")
foreach ($pasta in "$NginxDir\logs", "$NginxDir\temp") {
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    Executar icacls @($pasta, "/grant", "NT SERVICE\nginx:(OI)(CI)M", "/Q")
}
# nssm.exe é o executável dos dois serviços: mesma proteção, leitura para usuários e serviços.
$nssmDir = Split-Path (Get-Command nssm).Source
Restringir $nssmDir
Executar icacls @($nssmDir, "/grant", "*S-1-5-11:(OI)(CI)RX", "*S-1-5-6:(OI)(CI)RX", "/Q")

# --- Firewall -----------------------------------------------------------------
Passo "Firewall (80/443 de entrada)"
if (-not (Get-NetFirewallRule -DisplayName "Gestor de Pecas HTTPS" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Gestor de Pecas HTTPS" -Direction Inbound -Protocol TCP `
        -LocalPort 80, 443 -Action Allow | Out-Null
}

# --- Subida e validação -------------------------------------------------------
Passo "Subindo e validando"
Start-Service $Servico
$prazo = (Get-Date).AddSeconds(120)
$pronto = $false
do {
    try { $pronto = (Invoke-WebRequest "http://127.0.0.1:8000/api/v1/system/ready" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 }
    catch { Start-Sleep -Seconds 2 }
} while (-not $pronto -and (Get-Date) -lt $prazo)
Exigir $pronto "O app não ficou pronto em 120 s. Veja $Logs\gestor-pecas.log."
Start-Service nginx
foreach ($tentativa in 1..10) {
    $https = & curl.exe -k -s -o NUL -w "%{http_code}" "https://localhost/api/v1/system/ready"
    if ($https -eq "200") { break }
    Start-Sleep -Seconds 1
}
Exigir ($https -eq "200") "App responde em 127.0.0.1:8000, mas o nginx devolveu HTTP $https. Veja $NginxDir\logs\error.log."

Write-Host "`nPronto: https://$PublicHost (e https://localhost na própria VM)." -ForegroundColor Green
