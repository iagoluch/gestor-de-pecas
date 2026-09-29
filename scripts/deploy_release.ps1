[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Source,
    [Parameter(Mandatory)] [string]$AppDir,
    [string]$HealthUrl = "http://127.0.0.1:8000/api/v1/system/ready",
    [int]$HealthTimeoutSeconds = 60,
    # Backup do banco ANTES do restart: as migrations rodam no startup e não
    # têm down, então só este dump desfaz uma migration já aplicada.
    [Parameter(Mandatory)] [scriptblock]$BackupDatabase,
    [Parameter(Mandatory)] [scriptblock]$InstallDependencies,
    [Parameter(Mandatory)] [scriptblock]$StopService,
    [Parameter(Mandatory)] [scriptblock]$StartService
)

# Deploy com rollback de código (BK-08). Nunca restaura o banco sozinho:
# restaurar produção apaga apontamentos feitos depois do dump, então isso fica
# para uma pessoa decidir com o caminho do backup em mãos.

$ErrorActionPreference = "Stop"

# Dados de runtime nunca entram no espelho nem no snapshot.
$RuntimeDirs = @("dados", "dev_reports", "backups")
$SourceOnlyDirs = @(".venv", ".git", "node_modules", "web\node_modules")
$Snapshot = "$AppDir.previous"

function Invoke-Mirror {
    param([string]$From, [string]$To, [string[]]$ExcludeDirs)

    robocopy $From $To /MIR /XF .env /XD @ExcludeDirs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To falhou com código $LASTEXITCODE" }
}

function Wait-Healthy {
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    do {
        try {
            $resposta = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
            if ($resposta.StatusCode -eq 200) { return $true }
        } catch {
            Write-Host "Aguardando o serviço responder: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return $false
}

$temAnterior = (Test-Path -LiteralPath $AppDir) -and [bool](Get-ChildItem -LiteralPath $AppDir -Force | Select-Object -First 1)
if ($temAnterior) {
    # Inclui a .venv: o rollback volta código e dependências juntos.
    Invoke-Mirror -From $AppDir -To $Snapshot -ExcludeDirs $RuntimeDirs
}

# Sem backup não há deploy: nada foi parado nem sobrescrito até aqui.
$backup = & $BackupDatabase
Write-Host "Backup pré-deploy do banco: $backup"

try {
    & $StopService
    Invoke-Mirror -From $Source -To $AppDir -ExcludeDirs ($SourceOnlyDirs + $RuntimeDirs)
    & $InstallDependencies
    & $StartService
    if (-not (Wait-Healthy)) { throw "O serviço não ficou pronto em $HealthTimeoutSeconds segundos ($HealthUrl)." }
    Write-Host "Deploy concluído e saudável."
} catch {
    $falha = $_.Exception.Message
    if (-not $temAnterior) { throw "Deploy falhou e não há versão anterior para voltar: $falha" }

    Write-Warning "Deploy falhou ($falha). Voltando a versão anterior."
    try { & $StopService } catch { Write-Warning "Parada do serviço no rollback falhou: $($_.Exception.Message)" }
    Invoke-Mirror -From $Snapshot -To $AppDir -ExcludeDirs $RuntimeDirs
    & $StartService
    if (Wait-Healthy) {
        throw "Deploy falhou e o código anterior foi restaurado com sucesso: $falha"
    }
    # Típico de migration já aplicada: o código antigo recusa schema mais novo.
    throw ("Deploy falhou e o código anterior também não ficou pronto. Restaure manualmente " +
        "o backup pré-deploy do banco ($backup) e reinicie o serviço. Falha original: $falha")
}
