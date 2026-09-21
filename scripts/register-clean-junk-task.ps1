# Registra uma tarefa agendada do Windows que roda clean-junk.ps1 (via
# run-clean-junk.bat) diariamente. Rode este script UMA VEZ manualmente;
# não precisa ser admin (tarefa fica por-usuário). Para reagendar, rode de
# novo - o -Force sobrescreve a tarefa existente com o mesmo nome.
param(
    [string]$TaskName = "GestorPecas-LimpezaInterna",
    [string]$Time = "03:00"
)

$scriptPath = Join-Path $PSScriptRoot "run-clean-junk.bat"
if (-not (Test-Path $scriptPath)) {
    throw "Não encontrei $scriptPath"
}

$action = New-ScheduledTaskAction -Execute $scriptPath
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Limpeza automática de arquivos/logs temporários: metadata do OneDrive/Drive, __pycache__, simulation_runs/ e dev_reports/ com mais de 30 dias, e _quarentena_revisar/. Log em %USERPROFILE%\.cache\junk-cleanup.log." |
    Out-Null

Write-Output "Tarefa '$TaskName' registrada: roda diariamente às $Time. Para remover: Unregister-ScheduledTask -TaskName '$TaskName'"
