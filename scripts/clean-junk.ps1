# Limpa lixo recorrente da raiz do projeto (OneDrive metadata, caches de Python,
# arquivos soltos gerados por erro de shell). NUNCA toca em .tmp.drivedownload/
# .tmp.driveupload - são staging ativo do OneDrive, mexer ali pode corromper sync.
param(
    [switch]$DryRun,
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

Set-Location $Root
$removed = @()

# 1. desktop.ini - metadata do OneDrive/Explorer, cosmético, recriado sozinho
Get-ChildItem -Path $Root -Recurse -Force -Filter "desktop.ini" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.tmp\.drive(upload|download)\\' } |
    ForEach-Object {
        $removed += $_.FullName
        if (-not $DryRun) { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
    }

# 2. Thumbs.db
Get-ChildItem -Path $Root -Recurse -Force -Filter "Thumbs.db" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $removed += $_.FullName
        if (-not $DryRun) { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
    }

# 3. Caches Python (__pycache__, .pyc, .pytest_cache) fora de .venv
Get-ChildItem -Path $Root -Recurse -Force -Directory -Include "__pycache__", ".pytest_cache" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
    ForEach-Object {
        $removed += $_.FullName
        if (-not $DryRun) { Remove-Item -Force -Recurse -ErrorAction SilentlyContinue $_.FullName }
    }
Get-ChildItem -Path $Root -Recurse -Force -File -Include "*.pyc" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
    ForEach-Object {
        $removed += $_.FullName
        if (-not $DryRun) { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
    }

# 3b. Staging do Google Drive (.tmp.drivedownload/.tmp.driveupload) - só arquivos
#     com mais de 2 dias parados (sync ativo/recente não é tocado, risco de corromper
#     um upload/download em andamento).
$staleCutoff = (Get-Date).AddDays(-2)
foreach ($driveTmpDir in @(".tmp.drivedownload", ".tmp.driveupload")) {
    $p = Join-Path $Root $driveTmpDir
    if (Test-Path $p) {
        Get-ChildItem -Path $p -Force -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $staleCutoff } |
            ForEach-Object {
                $removed += $_.FullName
                if (-not $DryRun) { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
            }
    }
}

# 4. npm-debug.log / node crash logs soltos na raiz
Get-ChildItem -Path $Root -Force -File -Include "npm-debug.log*", "yarn-error.log" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $removed += $_.FullName
        if (-not $DryRun) { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
    }

# 5. Arquivos vazios (0 bytes) soltos na RAIZ do projeto - sinal de comando de
#    shell/script que escapou errado e virou nome de arquivo em vez de rodar
#    (ex: "fs.writeFileSync(__dirname"). Só na raiz (não recursivo - um __init__.py
#    ou .gitkeep vazio em subpasta é intencional), e pula os nomes que o projeto
#    de fato usa vazios de propósito.
$knownEmptyOk = @(".gitkeep", ".keep", "__init__.py")
Get-ChildItem -Path $Root -Force -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -eq 0 -and ($knownEmptyOk -notcontains $_.Name) } |
    ForEach-Object {
        $removed += $_.FullName
        if (-not $DryRun) { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
    }

$logPath = Join-Path $env:USERPROFILE ".cache\junk-cleanup.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
if ($removed.Count -gt 0) {
    "=== $stamp ($(if($DryRun){'dry-run'}else{'removed'})) ===" | Out-File -Append -Encoding utf8 $logPath
    $removed | Out-File -Append -Encoding utf8 $logPath
    Write-Output "$($removed.Count) item(ns) $(if($DryRun){'encontrados (dry-run)'}else{'removidos'}). Log: $logPath"
} else {
    Write-Output "Nada para limpar."
}
