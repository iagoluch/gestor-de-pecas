# Backup diario do banco: pg_dump em C:\gestor-pecas\backups, copia na pasta externa
# (copia-externa.txt ao lado deste script) e retencao dos dois lados. Roda como SYSTEM
# pela tarefa agendada que o instalar.ps1 cria, a partir de C:\gestor-backup: fora de
# C:\gestor-pecas de proposito, porque o runner escreve la e um script dele rodando como
# SYSTEM seria um atalho para SYSTEM. Resultado de cada execucao em backup.log.
param(
    [string]$AppDir = "C:\gestor-pecas",
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [int]$RetencaoDias = 14
)
$ErrorActionPreference = "Stop"
$Log = "$PSScriptRoot\backup.log"
function Log([string]$t) { Add-Content $Log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $t" }
function Podar([string]$pasta) {
    # So os dumps deste script: os pre-deploy-*.dump do pipeline ficam.
    Get-ChildItem $pasta -Filter "diario-*.dump" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetencaoDias) } | Remove-Item
}

try {
    # Mesma leitura do deploy.yml.
    $linha = Get-Content -LiteralPath "$AppDir\.env" | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
    $dsn = ($linha -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"', "'")
    if (-not $dsn) { throw "DATABASE_URL ausente em $AppDir\.env." }
    $pasta = "$AppDir\backups"
    New-Item -ItemType Directory -Force $pasta | Out-Null
    $arquivo = Join-Path $pasta ("diario-{0:yyyyMMdd-HHmmss}.dump" -f (Get-Date))
    & "$PgBin\pg_dump.exe" --format=custom --file "$arquivo" --dbname "$dsn"
    if ($LASTEXITCODE) { throw "pg_dump falhou ($LASTEXITCODE)." }
    Podar $pasta
    Log "OK $arquivo ($([math]::Round((Get-Item $arquivo).Length / 1MB, 1)) MB)"

    $externa = if (Test-Path "$PSScriptRoot\copia-externa.txt") { (Get-Content "$PSScriptRoot\copia-externa.txt" -TotalCount 1).Trim() }
    if ($externa) {
        # SYSTEM chega na rede como a conta do computador (<VM>$): o compartilhamento
        # precisa dar escrita a ela.
        Copy-Item $arquivo $externa
        Podar $externa
        Log "OK copia em $externa"
    }
} catch {
    Log "ERRO $_"
    exit 1
}
