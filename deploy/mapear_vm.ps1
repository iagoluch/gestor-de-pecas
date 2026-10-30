# Mapa da VM: SOMENTE LEITURA. Nao altera nada, nao precisa de Administrador (algumas linhas saem vazias sem ele).
# Gera Desktop\mapa-vm.txt. Nao grava senhas: do .env so saem NOMES e se estao preenchidos.
#   powershell -ExecutionPolicy Bypass -File mapear_vm.ps1
$ErrorActionPreference = "SilentlyContinue"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "mapa-vm.txt"
function T([string]$t) { "`n== $t ==" }
$app = "D:\gestor-pecas"

& {
    T "Maquina"
    "$env:COMPUTERNAME | $(Get-Date -Format 'dd/MM/yyyy HH:mm') | fuso: $((Get-TimeZone).Id)"
    (Get-CimInstance Win32_OperatingSystem).Caption
    "Admin: $(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrator'))"

    T "Discos"
    Get-PSDrive -PSProvider FileSystem | ForEach-Object { "{0}: livre {1:N1} GB de {2:N1} GB" -f $_.Name, ($_.Free/1GB), (($_.Used+$_.Free)/1GB) }

    T "Tarefas agendadas (nao-Microsoft)"
    Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\Microsoft\*' } | ForEach-Object {
        $i = $_ | Get-ScheduledTaskInfo
        "{0} | estado={1} | usuario={2} | ultimo={3} | resultado={4}" -f $_.TaskName, $_.State, $_.Principal.UserId, $i.LastRunTime, $i.LastTaskResult
        foreach ($a in $_.Actions) { "    acao: $($a.Execute) $($a.Arguments) | pasta: $($a.WorkingDirectory)" }
        foreach ($g in $_.Triggers) { "    gatilho: $($g.CimClass.CimClassName) $($g.StartBoundary)" }
        "    limite=$($_.Settings.ExecutionTimeLimit) reiniciar=$($_.Settings.RestartCount)x/$($_.Settings.RestartInterval)"
    }

    T "Servicos relevantes"
    Get-Service | Where-Object { $_.Name -match 'gestor|nginx|postgres|nssm|winrm' } | ForEach-Object { "{0} | {1} | {2}" -f $_.Name, $_.Status, $_.StartType }

    T "Processos relevantes"
    Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|nginx|postgres|uvicorn' } | ForEach-Object { "{0} (pid {1}) | {2}" -f $_.Name, $_.ProcessId, $_.CommandLine }

    T "Portas escutando"
    Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 80,443,8000,8001,8002,5432,5985,5986,3389 } | Sort-Object LocalPort | ForEach-Object { "{0}:{1} pid {2}" -f $_.LocalAddress, $_.LocalPort, $_.OwningProcess }

    T "Firewall (regras habilitadas de entrada nas portas do sistema)"
    Get-NetFirewallRule -Direction Inbound -Enabled True | ForEach-Object {
        $p = $_ | Get-NetFirewallPortFilter
        if ($p.LocalPort -match '^(80|443|8000|5432|5985|5986)$') { "{0} | porta {1} | acao {2} | perfil {3}" -f $_.DisplayName, $p.LocalPort, $_.Action, $_.Profile }
    }

    T "WinRM"
    "Servico: $((Get-Service WinRM).Status)"
    "TrustedHosts: $((Get-Item WSMan:\localhost\Client\TrustedHosts).Value)"
    "Escuta: " + ((Get-ChildItem WSMan:\localhost\Listener | ForEach-Object { $_.Name }) -join ", ")

    T "Pasta do sistema ($app) - nivel 1"
    Get-ChildItem $app -Force | ForEach-Object { "{0,-28} {1}" -f $_.Name, $(if ($_.PSIsContainer) { "<pasta>" } else { "{0:N0} KB" -f ($_.Length/1KB) }) }

    T "Tamanho das pastas de dados"
    foreach ($d in "dados","backups","dev_reports","web\dist","dados\logs") {
        $p = Join-Path $app $d
        if (Test-Path $p) { "{0,-14} {1:N1} MB" -f $d, ((Get-ChildItem $p -Recurse -File -Force | Measure-Object Length -Sum).Sum/1MB) } else { "$d : NAO EXISTE" }
    }

    T "Ultimos logs"
    Get-ChildItem "$app\dados\logs" -File -Force | Sort-Object LastWriteTime -Descending | Select-Object -First 8 | ForEach-Object { "{0} | {1:N0} KB | {2}" -f $_.Name, ($_.Length/1KB), $_.LastWriteTime }

    T ".env (so nomes; * = preenchido, vazio = vazio)"
    Get-Content "$app\.env" | Where-Object { $_ -match '^\s*[A-Z_0-9]+=' } | ForEach-Object {
        $k, $v = $_ -split '=', 2
        $k = $k.Trim(); $v = $v.Trim()
        $show = if ($v -eq '') { 'VAZIO' } elseif ($v -match 'TROCAR') { 'TROCAR' } elseif ($k -match 'ENABLED|ENV$|PORT$|HOST$|ORIGINS$|ENDPOINT$|ROOTS$') { $v } else { '*' }
        "{0} = {1}" -f $k, $show
    }

    T "nginx"
    $ng = Get-ChildItem D:\ -Filter nginx* -Directory | Select-Object -First 1
    if ($ng) {
        "pasta: $($ng.FullName)"
        Get-ChildItem "$($ng.FullName)\conf\certs" -Force | ForEach-Object { "cert: $($_.Name) | $($_.LastWriteTime)" }
        Get-ChildItem "$($ng.FullName)\logs" -Force | ForEach-Object { "log: $($_.Name) | {0:N0} KB" -f ($_.Length/1KB) }
        Get-Content "$($ng.FullName)\conf\nginx.conf" | Where-Object { $_ -match 'listen|server_name|proxy_pass|ssl_certificate|client_max_body_size' }
    } else { "nginx nao encontrado em D:\" }

    T "Python e dependencias"
    & "$app\.venv\Scripts\python.exe" --version
    & "$app\.venv\Scripts\python.exe" -m pip list --format=freeze | Select-String -Pattern 'fastapi|uvicorn|psycopg|pydantic|httpx|pyodbc|sqlalchemy'

    T "Banco"
    "Servico: $((Get-Service postgresql*).Name) $((Get-Service postgresql*).Status)"

    T "Backups (pasta e tarefa)"
    foreach ($p in "$app\backups","C:\gestor-backup","D:\gestor-backup") { if (Test-Path $p) { "$p : $((Get-ChildItem $p -File -Recurse | Measure-Object).Count) arquivos | mais novo: $((Get-ChildItem $p -File -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime)" } }

    T "Pastas do pacote de instalacao"
    Get-ChildItem D:\instalacao -Force | ForEach-Object { $_.Name }
} 2>&1 | Out-File -FilePath $out -Encoding utf8

Write-Host "Pronto: $out" -ForegroundColor Green
