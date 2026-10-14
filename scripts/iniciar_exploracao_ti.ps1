# Sobe o Gestor (banco de TESTE) acessível na rede interna para a TI explorar.
# Sem integrações externas (TOTVS/Telegram/SigmaNEST/relatórios). Porta 8001 (já liberada no firewall pela regra do Andon), HTTP.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\iniciar_exploracao_ti.ps1
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$env:GESTOR_WEB_ENV = "development"
$env:GESTOR_EXPECTED_DATABASE = "gestor_pecas_test"
$env:GESTOR_WEB_COOKIE_SECURE = "0"
$env:GESTOR_WEB_SERVE_STATIC = "1"
$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "10.*" }).IPAddress -join ","
$nome = $env:COMPUTERNAME
$env:GESTOR_WEB_ALLOWED_HOSTS = "127.0.0.1,localhost,$nome,$nome.gtsdobrasil.com.br,$ips"
foreach ($v in "GESTOR_TOTVS_ENABLED","GESTOR_TOTVS_SOAP_ENABLED","GESTOR_TOTVS_OUTBOX_WORKER_ENABLED",
               "GESTOR_SIGMANEST_SYNC_ENABLED","TELEGRAM_ENABLED","GESTOR_TELEGRAM_BOT_POLLING_ENABLED",
               "GESTOR_TELEGRAM_DIGEST_ENABLED","GESTOR_REPORT_AUTOMATION_ENABLED","GESTOR_DEV_OBSERVATORY_ENABLED") {
    Set-Item -Path "Env:$v" -Value "false"
}
Write-Host "Gestor (TESTE) em http://$nome`:8001  e  http://$($ips -split ',' | Select-Object -First 1):8001"
& "$raiz\.venv\Scripts\python.exe" -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8001
