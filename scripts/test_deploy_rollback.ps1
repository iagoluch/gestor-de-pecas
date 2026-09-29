[CmdletBinding()]
param()

# Prova o rollback do deploy_release.ps1 (BK-08) só com diretórios temporários
# e um serviço fake local; não toca a VM, o serviço real nem banco algum.

$ErrorActionPreference = "Stop"

$deploy = Join-Path $PSScriptRoot "deploy_release.ps1"
$python = (Get-Command python).Source
$root = Join-Path ([System.IO.Path]::GetTempPath()) ("gestor-deploy-rollback-" + [guid]::NewGuid())

# Serviço fake: lê a versão ao subir (como o uvicorn lê o código). A versão
# "quebrada" nunca fica pronta; a "migra" grava schema 2 em dados/, e a v1
# recusa schema mais novo, como o check de SCHEMA_VERSION do Gestor.
$fakeService = @'
import http.server, pathlib, sys
app, port = pathlib.Path(sys.argv[1]), int(sys.argv[2])
versao = (app / "versao.txt").read_text().strip()
schema = app / "dados" / "schema.txt"
if versao == "migra":
    schema.write_text("2")
pronto = versao not in ("quebrada", "migra") and not (versao == "v1" and schema.exists() and schema.read_text() == "2")
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if pronto else 503)
        self.end_headers()
    def log_message(self, *args):
        pass
http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'@

function New-Release {
    param([string]$Path, [string]$Versao)
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Path "versao.txt") -Value $Versao -NoNewline
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return $listener.LocalEndpoint.Port } finally { $listener.Stop() }
}

function Invoke-Cenario {
    param([string]$Nome, [string]$Versao, [switch]$BackupFalha)

    $case = Join-Path $root $Nome
    $app = Join-Path $case "app"
    $source = Join-Path $case "source"
    New-Release -Path $app -Versao "v1"
    New-Item -ItemType Directory -Path (Join-Path $app ".venv"), (Join-Path $app "dados") | Out-Null
    Set-Content -LiteralPath (Join-Path $app ".venv\deps.txt") -Value "v1" -NoNewline
    Set-Content -LiteralPath (Join-Path $app ".env") -Value "SEGREDO=preservado" -NoNewline
    Set-Content -LiteralPath (Join-Path $app "dados\apontamento.txt") -Value "producao" -NoNewline
    New-Release -Path $source -Versao $Versao

    # Tudo que os closures usam precisa ser local: GetNewClosure só copia este escopo.
    $py = $python
    $servico = $serviceFile
    $state = @{ Log = [System.Collections.Generic.List[string]]::new(); Proc = $null; Port = Get-FreePort }
    $start = {
        $state.Log.Add("start")
        $state.Proc = Start-Process -FilePath $py -ArgumentList @("`"$servico`"", "`"$app`"", $state.Port) -PassThru -WindowStyle Hidden
    }.GetNewClosure()
    $stop = {
        $state.Log.Add("stop")
        if ($state.Proc -and -not $state.Proc.HasExited) { $state.Proc.Kill(); $state.Proc.WaitForExit() }
    }.GetNewClosure()

    & $start
    $erro = $null
    try {
        & $deploy -Source $source -AppDir $app -HealthUrl "http://127.0.0.1:$($state.Port)/ready" -HealthTimeoutSeconds 6 `
            -BackupDatabase ({
                $state.Log.Add("backup")
                if ($BackupFalha) { throw "pg_dump indisponível" }
                "backups\pre-deploy.dump"
            }.GetNewClosure()) `
            -InstallDependencies ({
                $state.Log.Add("install")
                Set-Content -LiteralPath (Join-Path $app ".venv\deps.txt") -Value $Versao -NoNewline
            }.GetNewClosure()) `
            -StopService $stop -StartService $start
    } catch {
        $erro = $_.Exception.Message
    } finally {
        & $stop
    }
    return [pscustomobject]@{
        Erro = $erro
        Log = ($state.Log -join ",")
        Versao = Get-Content -LiteralPath (Join-Path $app "versao.txt") -Raw
        Deps = Get-Content -LiteralPath (Join-Path $app ".venv\deps.txt") -Raw
        Runtime = (Test-Path (Join-Path $app ".env")) -and (Test-Path (Join-Path $app "dados\apontamento.txt"))
    }
}

function Assert-Igual {
    param($Atual, $Esperado, [string]$Mensagem)
    if ($Atual -ne $Esperado) { throw "$Mensagem`: esperado '$Esperado', veio '$Atual'" }
}

try {
    New-Item -ItemType Directory -Path $root | Out-Null
    $serviceFile = Join-Path $root "fake_service.py"
    Set-Content -LiteralPath $serviceFile -Value $fakeService -Encoding ascii

    $ok = Invoke-Cenario -Nome "saudavel" -Versao "v2"
    Assert-Igual $ok.Erro $null "deploy saudável não deveria falhar"
    Assert-Igual $ok.Versao "v2" "deploy saudável aplica a versão nova"
    Assert-Igual $ok.Log "start,backup,stop,install,start,stop" "ordem do deploy saudável"
    Assert-Igual $ok.Runtime $true "deploy saudável preserva .env e dados"

    $volta = Invoke-Cenario -Nome "quebrada" -Versao "quebrada"
    if ($volta.Erro -notlike "*código anterior foi restaurado*") { throw "rollback sem mensagem esperada: $($volta.Erro)" }
    Assert-Igual $volta.Versao "v1" "rollback restaura o código anterior"
    Assert-Igual $volta.Deps "v1" "rollback restaura as dependências da .venv"
    Assert-Igual $volta.Log "start,backup,stop,install,start,stop,start,stop" "ordem do rollback"
    Assert-Igual $volta.Runtime $true "rollback preserva .env e dados"

    $semBackup = Invoke-Cenario -Nome "sem-backup" -Versao "v2" -BackupFalha
    if ($semBackup.Erro -notlike "*pg_dump indisponível*") { throw "falha de backup não abortou: $($semBackup.Erro)" }
    Assert-Igual $semBackup.Log "start,backup,stop" "sem backup o serviço não é parado pelo deploy"
    Assert-Igual $semBackup.Versao "v1" "sem backup o código não é tocado"

    $migrou = Invoke-Cenario -Nome "migrou" -Versao "migra"
    if ($migrou.Erro -notlike "*Restaure manualmente o backup pré-deploy do banco (backups\pre-deploy.dump)*") {
        throw "schema novo sem instrução de restauração manual: $($migrou.Erro)"
    }
    Assert-Igual $migrou.Versao "v1" "código volta mesmo quando o banco já migrou"

    Write-Host "Rollback do deploy validado: saudável, quebrada, sem backup e schema migrado."
} finally {
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
