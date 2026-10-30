# Gera, NO NOTEBOOK, o zip de atualizacao para a VM (sem WinRM, sem acesso a VM).
#   powershell -ExecutionPolicy Bypass -File deploy\gerar_pacote_vm.ps1
# Saida: dev_reports\pacotes-vm\gestor-pecas-<commit>-<data>.zip  (copie para D:\instalacao na VM e
# rode deploy\aplicar_atualizacao.ps1 de dentro dele; ver cabecalho daquele script).
# Publica o que esta COMMITADO (HEAD) + web\dist recem-compilado. Alteracao nao commitada fica de fora.
[CmdletBinding()]
param(
    [switch]$PularBuild,
    [switch]$PermitirSujo
)
$ErrorActionPreference = "Stop"
$raiz = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
function Falha([string]$m) { Write-Host "`nPACOTE NAO GERADO: $m" -ForegroundColor Red; exit 1 }
Set-Location $raiz

$sujo = git status --porcelain --untracked-files=no
if ($sujo -and -not $PermitirSujo) {
    Write-Host "Ha alteracoes nao commitadas (ficariam FORA do pacote):" -ForegroundColor Yellow
    $sujo | Select-Object -First 10 | ForEach-Object { Write-Host "  $_" }
    Falha "commite antes, ou use -PermitirSujo se for de proposito."
}
$commit = (git rev-parse --short HEAD).Trim()
$agora = Get-Date -Format "yyyyMMdd-HHmm"

if (-not $PularBuild) {
    Push-Location (Join-Path $raiz "web")
    npm run build
    $ok = $LASTEXITCODE
    Pop-Location
    if ($ok -ne 0) { Falha "npm run build falhou." }
}
$dist = Join-Path $raiz "web\dist"
if (-not (Test-Path (Join-Path $dist "index.html"))) { Falha "web\dist\index.html nao existe." }

$saida = Join-Path $raiz "dev_reports\pacotes-vm"
New-Item -ItemType Directory -Force $saida | Out-Null
$zip = Join-Path $saida "gestor-pecas-$commit-$agora.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

git archive --format=zip --prefix=release/ -o $zip HEAD
if ($LASTEXITCODE -ne 0) { Falha "git archive falhou." }

Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$z = [IO.Compression.ZipFile]::Open($zip, "Update")
try {
    # web\dist nao e versionado: entra do build local.
    foreach ($f in Get-ChildItem $dist -Recurse -File) {
        $rel = $f.FullName.Substring($dist.Length + 1).Replace("\", "/")
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $f.FullName, "release/web/dist/$rel") | Out-Null
    }
    # Scripts de deploy ainda nao commitados entram da pasta de trabalho (sao so ferramenta, nao codigo do app).
    foreach ($rel in "deploy/aplicar_atualizacao.ps1", "scripts/deploy_release.ps1") {
        $src = Join-Path $raiz $rel
        $entrada = "release/$rel"
        if ((Test-Path $src) -and -not $z.GetEntry($entrada)) {
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $src, $entrada) | Out-Null
        }
    }
    # aplicar_atualizacao.ps1 usa $PSScriptRoot como pasta do pacote: precisa estar na raiz de release/.
    $aplicar = Join-Path $raiz "deploy\aplicar_atualizacao.ps1"
    if (-not (Test-Path $aplicar)) { throw "deploy\aplicar_atualizacao.ps1 nao encontrado." }
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $aplicar, "release/aplicar_atualizacao.ps1") | Out-Null

    $versao = "commit $commit gerado em $(Get-Date -Format 'dd/MM/yyyy HH:mm')" + $(if ($sujo) { " (COM alteracoes nao commitadas fora)" } else { "" })
    $e = $z.CreateEntry("release/VERSAO.txt")
    $w = New-Object IO.StreamWriter($e.Open(), [Text.UTF8Encoding]::new($false))
    $w.Write($versao); $w.Dispose()
} catch {
    $z.Dispose(); Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Falha $_.Exception.Message
}
$z.Dispose()

$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
"{0:N1} MB | SHA256 {1}" -f ((Get-Item $zip).Length / 1MB), $hash | Set-Content "$zip.sha256.txt"
Write-Host "`nPACOTE PRONTO: $zip" -ForegroundColor Green
Write-Host "Na VM:  Expand-Archive <zip> -DestinationPath D:\gestor-deploy -Force"
Write-Host "        D:\gestor-deploy\release\aplicar_atualizacao.ps1 -TarefaApp `"<nome da tarefa>`""
