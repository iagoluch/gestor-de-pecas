[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Invoke-CodeMirror {
    param([string]$Source, [string]$Destination)

    robocopy $Source $Destination /MIR /XF .env /XD dados dev_reports backups | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy falhou com código $LASTEXITCODE"
    }
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("gestor-deploy-mirror-" + [guid]::NewGuid())
$source = Join-Path $root "source"
$destination = Join-Path $root "destination"

try {
    New-Item -ItemType Directory -Path $source, $destination | Out-Null
    Set-Content -LiteralPath (Join-Path $source "novo.py") -Value "novo" -NoNewline
    Set-Content -LiteralPath (Join-Path $destination "obsoleto.py") -Value "obsoleto" -NoNewline
    New-Item -ItemType Directory -Path (Join-Path $destination "dados"), (Join-Path $destination "dev_reports"), (Join-Path $destination "backups") | Out-Null
    Set-Content -LiteralPath (Join-Path $destination ".env") -Value "SEGREDO=preservado" -NoNewline
    Set-Content -LiteralPath (Join-Path $destination "dados\desenho.pdf") -Value "desenho" -NoNewline
    Set-Content -LiteralPath (Join-Path $destination "dev_reports\report.txt") -Value "relatorio" -NoNewline
    Set-Content -LiteralPath (Join-Path $destination "backups\backup.sql") -Value "backup" -NoNewline

    Invoke-CodeMirror -Source $source -Destination $destination
    Invoke-CodeMirror -Source $source -Destination $destination

    if (-not (Test-Path -LiteralPath (Join-Path $destination "novo.py"))) { throw "Código novo não foi copiado." }
    if (Test-Path -LiteralPath (Join-Path $destination "obsoleto.py")) { throw "Código obsoleto não foi removido." }
    foreach ($path in @(".env", "dados\desenho.pdf", "dev_reports\report.txt", "backups\backup.sql")) {
        if (-not (Test-Path -LiteralPath (Join-Path $destination $path))) { throw "Dado de runtime removido: $path" }
    }

    Write-Host "Deploy mirror seguro e idempotente validado."
} finally {
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
