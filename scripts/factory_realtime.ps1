param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Data = Join-Path $Root "dados\factory_realtime"
$Runner = Join-Path $Root "scripts\run_factory_realtime.py"
$Web = Join-Path $Root "scripts\run_factory_test_web.py"
$RunnerPid = Join-Path $Data "simulator.pid"
$WebPid = Join-Path $Data "web.pid"

New-Item -ItemType Directory -Force -Path $Data | Out-Null

function Get-OwnedProcess([string]$PidFile, [string]$ScriptName) {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $idText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($idText -notmatch '^\d+$') { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $idText" -ErrorAction SilentlyContinue
    if ($null -eq $proc -or $proc.CommandLine -notlike "*$ScriptName*") { return $null }
    return $proc
}

function Start-OwnedProcess([string]$Script, [string]$PidFile, [string]$OutLog, [string]$ErrLog) {
    $existing = Get-OwnedProcess $PidFile ([IO.Path]::GetFileName($Script))
    if ($null -ne $existing) { return [int]$existing.ProcessId }
    $proc = Start-Process -FilePath $Python -ArgumentList @("`"$Script`"") -WorkingDirectory $Root `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog
    Set-Content -LiteralPath $PidFile -Value $proc.Id -Encoding ascii
    Start-Sleep -Seconds 2
    if ($proc.HasExited) {
        throw "Processo encerrou ao iniciar: $Script. Veja $ErrLog."
    }
    return $proc.Id
}

function Stop-OwnedTree([string]$PidFile, [string]$ScriptName) {
    $proc = Get-OwnedProcess $PidFile $ScriptName
    if ($null -eq $proc) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return
    }
    $descendants = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $proc.ProcessId })
    foreach ($child in $descendants) {
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $proc.ProcessId -Force
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

switch ($Action) {
    "start" {
        $webId = Start-OwnedProcess $Web $WebPid (Join-Path $Data "web.out.log") (Join-Path $Data "web.err.log")
        $runnerId = Start-OwnedProcess $Runner $RunnerPid (Join-Path $Data "simulator.out.log") (Join-Path $Data "simulator.err.log")
        Start-Sleep -Seconds 1
        $webOwned = Get-OwnedProcess $WebPid "run_factory_test_web.py"
        $runnerOwned = Get-OwnedProcess $RunnerPid "run_factory_realtime.py"
        if ($webOwned) { $webId = [int]$webOwned.ProcessId }
        if ($runnerOwned) { $runnerId = [int]$runnerOwned.ProcessId }
        Write-Output "Fábrica TESTE iniciada. servidor_pid=$webId simulador_pid=$runnerId"
    }
    "stop" {
        Stop-OwnedTree $RunnerPid "run_factory_realtime.py"
        Stop-OwnedTree $WebPid "run_factory_test_web.py"
        Write-Output "Fábrica TESTE encerrada."
    }
    "status" {
        $runnerProc = Get-OwnedProcess $RunnerPid "run_factory_realtime.py"
        $webProc = Get-OwnedProcess $WebPid "run_factory_test_web.py"
        $state = $null
        $statePath = Join-Path $Data "state.json"
        if (Test-Path -LiteralPath $statePath) {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        }
        $health = "offline"
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:8002/api/v1/system/health"
            if ($response.Headers["X-Gestor-Factory-Test"] -eq "gestor_pecas_test") {
                $health = "HTTP $($response.StatusCode) TESTE confirmado"
            } else {
                $health = "recusado: marcador TESTE ausente"
            }
        } catch {}
        [pscustomobject]@{
            servidor_pid = if ($webProc) { $webProc.ProcessId } else { $null }
            simulador_pid = if ($runnerProc) { $runnerProc.ProcessId } else { $null }
            health = $health
            ativos = if ($state) { $state.active_count } else { $null }
            fila_elegivel = if ($state) { $state.eligible_queue_count } else { $null }
            atualizado_em = if ($state) { $state.updated_at } else { $null }
            log = Join-Path $Data "simulator.jsonl"
        } | Format-List
    }
}
