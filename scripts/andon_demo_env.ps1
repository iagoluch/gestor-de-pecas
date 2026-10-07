# Carregue com dot-source antes do comando uvicorn oficial:
#   . .\scripts\andon_demo_env.ps1

$env:GESTOR_ANDON_DEMO_MODE = "1"
$env:GESTOR_EXPECTED_DATABASE = "gestor_pecas_test_andon_demo"
$env:GESTOR_TEST_MODE = "1"
$env:GESTOR_WEB_ENV = "development"
$env:GESTOR_WEB_SERVE_STATIC = "1"
$env:GESTOR_WEB_PUBLIC_HOST = "10.10.1.248"
$env:GESTOR_SIMULATION_MODE = "1"
$env:GESTOR_SIMULATION_NOW = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
$env:GESTOR_SIMULATION_TIME_SCALE = "1"

# Defesa em profundidade contra valores herdados do .env. O profile DEMO do
# backend também os recusa, mas o terminal fica seguro antes do import.
$env:GESTOR_TOTVS_ENABLED = "0"
$env:GESTOR_TOTVS_SOAP_ENABLED = "0"
$env:GESTOR_TOTVS_OUTBOX_ENABLED = "0"
$env:GESTOR_TOTVS_OUTBOX_WORKER_ENABLED = "0"
$env:GESTOR_SIGMANEST_SYNC_ENABLED = "0"
$env:TELEGRAM_ENABLED = "0"
$env:GESTOR_TELEGRAM_BOT_POLLING_ENABLED = "0"
$env:GESTOR_TELEGRAM_DIGEST_ENABLED = "0"
$env:GESTOR_REPORT_AUTOMATION_ENABLED = "0"
$env:GESTOR_AI_ENABLED = "0"
$env:GESTOR_DEV_OBSERVATORY_ENABLED = "0"
$env:GESTOR_TOTVS_OP_PULL_ENDPOINT = ""
$env:GESTOR_TOTVS_OUTBOUND_ENDPOINT = ""
$env:TELEGRAM_BOT_TOKEN = ""
$env:GROQ_API_KEY = ""
$env:SIGMANEST_ODBC_DSN = ""
$env:SIGMANEST_SERVER = ""
$env:SIGMANEST_DATABASE = ""
$env:GESTOR_DEVOBS_REAL_DATABASE_URL = ""
$env:DATABASE_URL = ""

# O backend precisa receber o DSN do alvo dedicado em TEST_DATABASE_URL. A
# derivação ocorre somente em memória neste terminal; o .env permanece intacto
# e a credencial nunca é impressa nem gravada em outro arquivo.
$demoEnvFile = Join-Path $PSScriptRoot "..\.env"
$demoLine = Get-Content -LiteralPath $demoEnvFile | Where-Object {
    $_ -match '^\s*TEST_DATABASE_URL\s*='
} | Select-Object -Last 1
if (-not $demoLine) {
    throw "TEST_DATABASE_URL não encontrada no .env; perfil DEMO recusado."
}
$demoSourceDsn = ($demoLine -replace '^\s*TEST_DATABASE_URL\s*=\s*', '').Trim()
if (($demoSourceDsn.StartsWith('"') -and $demoSourceDsn.EndsWith('"')) -or
    ($demoSourceDsn.StartsWith("'") -and $demoSourceDsn.EndsWith("'"))) {
    $demoSourceDsn = $demoSourceDsn.Substring(1, $demoSourceDsn.Length - 2)
}
if ($demoSourceDsn -match '(?i)^postgres(?:ql)?://') {
    $demoUri = [System.UriBuilder]::new($demoSourceDsn)
    $demoUri.Path = "/gestor_pecas_test_andon_demo"
    $env:TEST_DATABASE_URL = $demoUri.Uri.AbsoluteUri
} elseif ($demoSourceDsn -match '(?i)(^|\s)dbname=') {
    $env:TEST_DATABASE_URL = [regex]::Replace(
        $demoSourceDsn,
        '(?i)(^|\s)dbname=("[^"]*"|''[^'']*''|\S+)',
        '$1dbname=gestor_pecas_test_andon_demo',
        1
    )
} else {
    throw "TEST_DATABASE_URL sem dbname explícito; perfil DEMO recusado."
}
Remove-Variable demoLine, demoSourceDsn, demoUri -ErrorAction SilentlyContinue

Write-Host "Perfil Andon DEMO carregado para este terminal: banco dedicado, integrações externas bloqueadas."
