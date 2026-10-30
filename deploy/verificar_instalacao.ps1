# Verifica, SEM alterar nada, quais etapas do INSTALACAO_MANUAL.md ja foram feitas na VM.
# Nao precisa de Administrador (alguns itens ficam "?" sem ele). Nao imprime senhas.
# Uso:  powershell -ExecutionPolicy Bypass -File .\verificar_instalacao.ps1
# Saida: na tela e em  Desktop\verificacao-instalacao.txt  (cole o conteudo no chat).

$ErrorActionPreference = 'SilentlyContinue'
$app   = 'D:\gestor-pecas'
$pkg   = 'D:\instalacao\gestor-pecas-deploy'
$pg    = 'D:\postgresql'
$nssm  = 'C:\tools\nssm'
$nginx = 'C:\nginx'
$out   = New-Object System.Collections.ArrayList

function Linha($estado, $texto) {
    $l = ('[{0}] {1}' -f $estado, $texto)
    [void]$out.Add($l)
    $cor = @{ 'OK' = 'Green'; 'FALTA' = 'Red'; '?' = 'Yellow'; 'INFO' = 'Gray' }[$estado]
    Write-Host $l -ForegroundColor $cor
}
function Titulo($t) { [void]$out.Add(''); [void]$out.Add("== $t =="); Write-Host ''; Write-Host "== $t ==" -ForegroundColor Cyan }
function Teste($ok, $feito, $falta) { if ($ok) { Linha 'OK' $feito } else { Linha 'FALTA' $falta } }

$eAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Titulo 'Maquina'
Linha 'INFO' ("Servidor: {0} | usuario: {1} | {2}" -f $env:COMPUTERNAME, $env:USERNAME, (Get-Date -Format 'dd/MM/yyyy HH:mm'))
Linha 'INFO' ("SO: " + (Get-CimInstance Win32_OperatingSystem).Caption)
if ($eAdmin) { Linha 'OK' 'Janela do PowerShell esta como Administrador' } else { Linha 'FALTA' 'Janela NAO esta como Administrador (instalar programas/servicos exige)' }

Titulo 'Parte A - Banco (PostgreSQL)'
Teste (Test-Path "$pg\bin\psql.exe") "PostgreSQL instalado em $pg" "PostgreSQL NAO encontrado em $pg\bin"
$svcPg = Get-Service | Where-Object { $_.Name -like 'postgresql*' } | Select-Object -First 1
if ($svcPg) { Linha 'OK' ("Servico {0}: {1}" -f $svcPg.Name, $svcPg.Status) } else { Linha 'FALTA' 'Servico do PostgreSQL nao existe' }
Teste (Test-Path $pkg) "Pacote em $pkg" "Pacote NAO esta em $pkg"
$senhaArq = 'D:\instalacao\senha-gestor_app.txt'
Teste (Test-Path $senhaArq) 'Arquivo da senha do gestor_app existe' 'Arquivo senha-gestor_app.txt nao encontrado'
if ((Test-Path "$pg\bin\psql.exe") -and (Test-Path $senhaArq)) {
    $env:PGPASSWORD = ((Get-Content $senhaArq -Raw) -replace '\s', '')
    $v = & "$pg\bin\psql.exe" -h 127.0.0.1 -U gestor_app -d gestor_pecas -t -A -c 'select max(version) from schema_migrations' 2>$null
    Remove-Item Env:\PGPASSWORD
    if ($v -match '^\d+$') {
        if ([int]$v -eq 68) { Linha 'OK' "Banco gestor_pecas restaurado, versao $v (esperado 68)" }
        else { Linha '?' "Banco gestor_pecas na versao $v (esperado 68)" }
    } else { Linha '?' 'Nao consegui consultar a versao do banco (senha/servico?)' }
}

Titulo 'Parte B - Programas'
$py = & py -3.14 --version 2>$null
if ($py) { Linha 'OK' "Python: $py (py -3.14 funciona)" } else { Linha 'FALTA' 'py -3.14 nao funciona (Python 3.14 nao instalado ou sem o launcher)' }
Teste (Test-Path "$nginx\nginx.exe") "nginx em $nginx" "nginx NAO encontrado em $nginx"
$nssmExe = if (Test-Path "$nssm\nssm.exe") { "$nssm\nssm.exe" } else { (Get-Command nssm -ErrorAction SilentlyContinue).Source }
Teste ([bool]$nssmExe) "NSSM encontrado: $nssmExe" "NSSM nao encontrado (esperado em $nssm\nssm.exe)"
$pathMaq = [Environment]::GetEnvironmentVariable('Path', 'Machine')
Teste ($pathMaq -like "*$nssm*") 'PATH da maquina contem a pasta do NSSM' 'PATH da maquina NAO contem a pasta do NSSM'
$odbc = Test-Path 'HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server'
Teste $odbc 'ODBC Driver 18 for SQL Server instalado' 'ODBC Driver 18 NAO instalado'

Titulo 'Parte C - Codigo do sistema'
Teste (Test-Path "$app\backend\api\main.py") "Codigo copiado em $app" "Codigo NAO esta em $app"
Teste (Test-Path "$app\requirements.lock") 'requirements.lock presente' 'requirements.lock nao encontrado'
foreach ($p in 'dados\logs', 'backups', 'dev_reports') { Teste (Test-Path "$app\$p") "Pasta $p existe" "Pasta $p nao existe" }
$acl = (& icacls $app 2>$null) -join ' '
if ($acl) {
    if ($acl -match 'BUILTIN\\Users|Everyone|Authenticated Users') { Linha 'FALTA' 'Permissoes: ainda ha acesso para Users/Everyone na pasta (passo 11 nao feito)' }
    else { Linha 'OK' 'Permissoes: so Administradores/SYSTEM (ou contas de servico)' }
}

Titulo 'Parte E - Arquivo .env'
$envp = "$app\.env"
if (Test-Path $envp) {
    Linha 'OK' ".env existe em $envp"
    $b = [IO.File]::ReadAllBytes($envp)
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { Linha 'FALTA' '.env esta com BOM (precisa UTF-8 sem BOM)' } else { Linha 'OK' '.env sem BOM' }
    $linhas = Get-Content $envp | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' }
    $vazias = @(); $trocar = @(); $chaves = @{}
    foreach ($l in $linhas) {
        $k, $val = $l -split '=', 2
        $k = $k.Trim(); $val = $val.Trim()
        $chaves[$k] = $val
        if ($val -eq '') { $vazias += $k }
        if ($val -match 'TROCAR') { $trocar += $k }
    }
    $obrig = 'DATABASE_URL', 'GESTOR_WEB_SESSION_SECRET', 'GESTOR_WEB_ALLOWED_HOSTS', 'GESTOR_WEB_ALLOWED_ORIGINS', 'GESTOR_WEB_PUBLIC_HOST', 'SIGMANEST_PASSWORD'
    foreach ($k in $obrig) {
        if (-not $chaves.ContainsKey($k)) { Linha 'FALTA' "$k nao existe no .env" }
        elseif ($chaves[$k] -eq '' -or $chaves[$k] -match 'TROCAR') { Linha 'FALTA' "$k esta vazio/TROCAR" }
    }
    if ($chaves['DATABASE_URL'] -and $chaves['DATABASE_URL'] -notmatch 'D:|127\.0\.0\.1|localhost') { Linha '?' 'DATABASE_URL nao aponta para o banco local' }
    if ($vazias) { Linha 'INFO' ('Chaves vazias: ' + ($vazias -join ', ')) } else { Linha 'OK' 'Nenhuma chave vazia' }
    if ($trocar) { Linha 'FALTA' ('Ainda com TROCAR: ' + ($trocar -join ', ')) } else { Linha 'OK' 'Nenhum TROCAR restante' }
    Linha 'INFO' ('TELEGRAM_ENABLED=' + $chaves['TELEGRAM_ENABLED'] + ' | OUTBOX_ENABLED=' + $chaves['GESTOR_TOTVS_OUTBOX_ENABLED'])
} else {
    Linha 'FALTA' ".env NAO existe em $envp"
    if (Test-Path 'C:\Users\iago.luchtenberg\Desktop\env.txt') { Linha 'INFO' 'Existe env.txt na area de trabalho (ainda nao copiado para o lugar certo)' }
}

Titulo 'Parte F - Ambiente Python do sistema (.venv)'
$vpy = "$app\.venv\Scripts\python.exe"
Teste (Test-Path $vpy) '.venv criado' '.venv NAO criado'
if (Test-Path $vpy) {
    $imp = & $vpy -c "import fastapi, uvicorn, psycopg; print('ok')" 2>$null
    Teste ($imp -eq 'ok') 'Pacotes principais instalados (fastapi, uvicorn, psycopg)' 'Pacotes NAO instalados no .venv (pip nao concluiu)'
}

Titulo 'Parte G - nginx (https)'
if (Test-Path "$nginx\conf\nginx.conf") {
    Linha 'OK' 'nginx.conf existe'
    $conf = Get-Content "$nginx\conf\nginx.conf" -Raw
    Teste ($conf -match 'proxy_pass\s+http://127\.0\.0\.1:8000') 'nginx.conf aponta para 127.0.0.1:8000' 'nginx.conf nao aponta para 127.0.0.1:8000'
    $certs = Get-ChildItem $nginx -Recurse -Include *.pem, *.crt, *.key | ForEach-Object { $_.FullName }
    if ($certs) { Linha 'OK' ('Certificado/chave: ' + ($certs -join '; ')) } else { Linha 'FALTA' 'Nenhum certificado (.pem/.crt/.key) em C:\nginx' }
} else { Linha 'FALTA' 'nginx.conf nao encontrado' }

Titulo 'Parte H - Servicos, contas e firewall'
foreach ($s in 'gestor-pecas', 'nginx') {
    $svc = Get-Service $s
    if ($svc) {
        $w = Get-CimInstance Win32_Service -Filter "Name='$s'"
        Linha 'OK' ("Servico {0}: {1} | inicio {2} | conta {3}" -f $s, $svc.Status, $svc.StartType, $w.StartName)
    } else { Linha 'FALTA' "Servico $s NAO existe" }
}
try {
    $regras = Get-NetFirewallPortFilter | Where-Object { $_.LocalPort -in '80', '443' -and $_.Protocol -eq 'TCP' } | Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' }
    $portas = @($regras | Get-NetFirewallPortFilter | ForEach-Object { $_.LocalPort }) | Sort-Object -Unique
    Teste ($portas -contains '443') 'Firewall: entrada 443 liberada' 'Firewall: 443 NAO liberada'
    Teste ($portas -contains '80') 'Firewall: entrada 80 liberada' 'Firewall: 80 NAO liberada'
} catch { Linha '?' 'Nao consegui ler o firewall' }

Titulo 'Parte I - Sistema no ar'
$ouve = Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 80, 443, 5432, 8000 } | ForEach-Object { $_.LocalPort } | Sort-Object -Unique
Linha 'INFO' ('Portas escutando: ' + ($ouve -join ', '))
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
foreach ($u in 'http://127.0.0.1:8000/', 'https://127.0.0.1/') {
    try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 8; Linha 'OK' "$u respondeu HTTP $($r.StatusCode)" }
    catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code) { Linha '?' "$u respondeu HTTP $code" } else { Linha 'FALTA' "$u nao respondeu" }
    }
}

Titulo 'Parte J - Backup'
$tk = Get-ScheduledTask | Where-Object { $_.TaskName -like '*gestor*' -or $_.TaskName -like '*backup*' }
if ($tk) { foreach ($t in $tk) { Linha 'OK' ("Tarefa agendada: {0} ({1})" -f $t.TaskName, $t.State) } } else { Linha 'FALTA' 'Nenhuma tarefa de backup agendada' }
if (Test-Path 'C:\gestor-backup') {
    $ult = Get-ChildItem 'C:\gestor-backup' -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($ult) { Linha 'OK' ("Ultimo arquivo de backup: {0} ({1})" -f $ult.Name, $ult.LastWriteTime) } else { Linha 'INFO' 'Pasta C:\gestor-backup existe, ainda sem backup' }
} else { Linha 'FALTA' 'Pasta C:\gestor-backup nao existe' }

Titulo 'Parte K - Final'
if (Test-Path 'D:\instalacao') { Linha 'INFO' 'D:\instalacao ainda existe (apagar so no fim: tem dump e senhas)' } else { Linha 'OK' 'D:\instalacao ja apagado' }

$arq = Join-Path ([Environment]::GetFolderPath('Desktop')) 'verificacao-instalacao.txt'
$out | Out-File -FilePath $arq -Encoding utf8
Write-Host ''
Write-Host "Resultado salvo em: $arq" -ForegroundColor Cyan
Write-Host 'Cole o conteudo desse arquivo no chat.' -ForegroundColor Cyan
