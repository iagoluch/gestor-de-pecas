# Aplica uma atualizacao NA VM, sem NSSM e sem WinRM. Roda como Administrador, a partir do pacote
# gerado no notebook por deploy\gerar_pacote_vm.ps1 (este arquivo vai dentro do zip).
#
#   Expand-Archive D:\instalacao\gestor-pecas-XXXX.zip -DestinationPath D:\gestor-deploy -Force
#   D:\gestor-deploy\release\aplicar_atualizacao.ps1 -TarefaApp "<nome da tarefa do app>"
#
# Faz: backup do banco -> copia do codigo atual (.previous) -> para o app -> troca os arquivos
# (preserva .env, dados, backups, .venv) -> pip so se requirements.lock mudou -> inicia -> confere
# /ready -> se nao subir, volta o codigo anterior. O banco NUNCA e restaurado sozinho.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$TarefaApp,
    [string]$AppDir = "D:\gestor-pecas",
    [string]$PgBin = "D:\postgresql\bin",
    [string]$NginxDir = "D:\nginx-1.30.6",
    # Troca tambem o nginx.conf do pacote. Desligado por padrao: o da VM foi ajustado a mao.
    [switch]$AtualizarNginxConf
)
$ErrorActionPreference = "Stop"
$release = $PSScriptRoot

function Falha([string]$m) { Write-Host "`nNAO APLICADO: $m" -ForegroundColor Red; exit 1 }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("Administrator")) {
    Falha "rode o PowerShell como Administrador."
}
if (-not (Get-ScheduledTask -TaskName $TarefaApp -ErrorAction SilentlyContinue)) {
    Falha "nao existe tarefa agendada '$TarefaApp'. Nomes: Get-ScheduledTask | Where-Object TaskName -match 'gestor'"
}
foreach ($f in "$release\scripts\deploy_release.ps1", "$release\requirements.lock", "$release\web\dist\index.html") {
    if (-not (Test-Path -LiteralPath $f)) { Falha "pacote incompleto, falta: $f" }
}
$versao = if (Test-Path "$release\VERSAO.txt") { (Get-Content "$release\VERSAO.txt" -Raw).Trim() } else { "(sem VERSAO.txt)" }
Write-Host "Aplicando: $versao" -ForegroundColor Cyan

# pip so roda se as dependencias mudaram (a VM pode nao ter internet). Compara antes do espelhamento.
$pipPrecisa = (Get-FileHash "$release\requirements.lock").Hash -ne (Get-FileHash "$AppDir\requirements.lock" -ErrorAction SilentlyContinue).Hash

$parar = {
    Stop-ScheduledTask -TaskName $TarefaApp -ErrorAction SilentlyContinue
    # Garante que nenhum uvicorn do app fique segurando arquivos ou a porta 8000.
    Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "backend\.api\.main" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
$iniciar = { Start-ScheduledTask -TaskName $TarefaApp }

try {
    & "$release\scripts\deploy_release.ps1" -Source $release -AppDir $AppDir `
        -BackupDatabase {
            $linha = Get-Content -LiteralPath "$AppDir\.env" | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
            $dsn = ($linha -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"', "'")
            if (-not $dsn) { throw "DATABASE_URL ausente no .env da VM: sem backup nao ha atualizacao." }
            $pasta = Join-Path $AppDir "backups"
            New-Item -ItemType Directory -Force -Path $pasta | Out-Null
            $arquivo = Join-Path $pasta ("pre-deploy-{0:yyyyMMdd-HHmmss}.dump" -f (Get-Date))
            & "$PgBin\pg_dump.exe" --format=custom --file "$arquivo" --dbname "$dsn"
            if ($LASTEXITCODE -ne 0) { throw "pg_dump falhou ($LASTEXITCODE): nada foi alterado." }
            $arquivo
        } `
        -InstallDependencies {
            if ($pipPrecisa) {
                & "$AppDir\.venv\Scripts\pip.exe" install --require-hashes -r "$AppDir\requirements.lock"
                if ($LASTEXITCODE -ne 0) { throw "pip install falhou ($LASTEXITCODE)." }
            } else { Write-Host "requirements.lock igual ao da VM: pip nao necessario." }
        } `
        -StopService $parar `
        -StartService $iniciar

    if ($AtualizarNginxConf) {
        $destino = "$NginxDir\conf\nginx.conf"
        $anterior = [IO.File]::ReadAllBytes($destino)
        Copy-Item "$release\deploy\nginx.conf" $destino -Force
        & "$NginxDir\nginx.exe" -p "$NginxDir" -t
        if ($LASTEXITCODE -ne 0) {
            [IO.File]::WriteAllBytes($destino, $anterior)
            throw "nginx.conf novo e invalido (nginx -t): o anterior foi restaurado."
        }
        & "$NginxDir\nginx.exe" -p "$NginxDir" -s reload
    }

    New-Item -ItemType Directory -Force "$AppDir\dados" | Out-Null
    Set-Content "$AppDir\dados\ultima-publicacao.txt" "$versao em $(Get-Date -Format s)" -Encoding UTF8
    Write-Host "`nAPLICADO: $versao" -ForegroundColor Green
} catch {
    Falha $_.Exception.Message
}
