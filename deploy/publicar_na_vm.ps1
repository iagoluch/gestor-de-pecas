# Botao manual: publica o HEAD deste notebook na VM (substitui o runner do GitHub).
# Roda NO NOTEBOOK. Faz o mesmo que o deploy automatico: backup do banco, troca o codigo,
# reinicia, confere /ready e, se nao subir, volta o codigo anterior (scripts/deploy_release.ps1).
#
#   deploy\Publicar na VM.bat        (duplo clique)
#
# Pre-requisito (TI, uma vez): WinRM ligado na VM e o notebook liberado nele (deploy/GUIA_TI.md, item 10).
[CmdletBinding()]
param(
    [string]$Vm = "gestor-peca",
    [string]$AppDir = "C:\gestor-pecas",
    [string]$NginxDir = "C:\nginx"
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Falha([string]$m) { Write-Host "`nNAO PUBLICADO: $m" -ForegroundColor Red; exit 1 }

# 1. So publica o que esta salvo no Git: o que a VM recebe e exatamente o que fica registrado.
if (git status --porcelain --untracked-files=no) { Falha "ha alteracoes nao commitadas. Commite antes de publicar." }
$commit = (git log -1 --format="%h %s").Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Host "Vai publicar na VM '$Vm':" -ForegroundColor Cyan
Write-Host "  $commit  (branch $branch)"
Write-Host "O banco da VM recebe backup antes. Se o sistema nao subir, o codigo anterior volta sozinho."
if ((Read-Host "Digite PUBLICAR para confirmar") -ne "PUBLICAR") { Falha "cancelado por voce." }

# 2. Conexao com a VM antes de gastar tempo no build.
$cred = Get-Credential -Message "Administrador da VM $Vm"
try { $sessao = New-PSSession -ComputerName $Vm -Credential $cred -Authentication Negotiate }
catch { Falha "nao conectei na VM ($($_.Exception.Message)). Veja o item 10 do GUIA_TI.md." }

try {
    # 3. Pacote: codigo do HEAD + site ja construido.
    $tmp = Join-Path $env:TEMP "gestor-publicar"
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory $tmp | Out-Null
    Push-Location (Join-Path $raiz "web"); npm run build; $ok = $LASTEXITCODE; Pop-Location
    if ($ok -ne 0) { Falha "build do site falhou." }
    $zip = Join-Path $tmp "release.zip"
    git archive --format=zip --prefix=release/ -o $zip HEAD
    if ($LASTEXITCODE -ne 0) { Falha "git archive falhou." }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $dist = Join-Path $raiz "web\dist"
    $z = [IO.Compression.ZipFile]::Open($zip, "Update")
    try {
        foreach ($f in Get-ChildItem $dist -Recurse -File) {
            $rel = $f.FullName.Substring($dist.Length + 1).Replace("\", "/")
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $f.FullName, "release/web/dist/$rel") | Out-Null
        }
    } finally { $z.Dispose() }

    # 4. Envia e implanta na VM.
    Write-Host "`nEnviando para a VM..." -ForegroundColor Cyan
    Invoke-Command $sessao { New-Item -ItemType Directory -Force C:\gestor-deploy | Out-Null; Remove-Item C:\gestor-deploy\release* -Recurse -Force -ErrorAction SilentlyContinue }
    Copy-Item $zip -Destination C:\gestor-deploy\release.zip -ToSession $sessao
    Write-Host "Implantando..." -ForegroundColor Cyan
    Invoke-Command $sessao -ArgumentList $AppDir, $NginxDir, $commit {
        param($AppDir, $NginxDir, $commit)
        $ErrorActionPreference = "Stop"
        Expand-Archive C:\gestor-deploy\release.zip -DestinationPath C:\gestor-deploy -Force
        Set-Location C:\gestor-deploy\release
        & .\scripts\deploy_release.ps1 -Source . -AppDir $AppDir `
            -BackupDatabase {
                $linha = Get-Content -LiteralPath "$AppDir\.env" | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
                $dsn = ($linha -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"', "'")
                if (-not $dsn) { throw "DATABASE_URL ausente no .env da VM: sem backup nao ha deploy." }
                $pasta = Join-Path $AppDir "backups"
                New-Item -ItemType Directory -Force -Path $pasta | Out-Null
                $arquivo = Join-Path $pasta ("pre-deploy-{0:yyyyMMdd-HHmmss}.dump" -f (Get-Date))
                pg_dump --format=custom --file "$arquivo" --dbname "$dsn"
                if ($LASTEXITCODE -ne 0) { throw "pg_dump falhou ($LASTEXITCODE): nada foi alterado." }
                $arquivo
            } `
            -InstallDependencies {
                & "$AppDir\.venv\Scripts\pip.exe" install --require-hashes -r "$AppDir\requirements.lock"
                if ($LASTEXITCODE -ne 0) { throw "pip install falhou ($LASTEXITCODE)." }
            } `
            -StopService { Stop-Service -Name gestor-pecas } `
            -StartService { Start-Service -Name gestor-pecas }

        # nginx.conf so muda se mudou no codigo; se o novo nao subir, volta o anterior.
        $destino = "$NginxDir\conf\nginx.conf"
        $novo = [IO.File]::ReadAllBytes("C:\gestor-deploy\release\deploy\nginx.conf")
        $atual = [IO.File]::ReadAllBytes($destino)
        if ([Convert]::ToBase64String($novo) -ne [Convert]::ToBase64String($atual)) {
            [IO.File]::WriteAllBytes($destino, $novo)
            Restart-Service nginx
            $codigo = & curl.exe -k -s -o NUL -w "%{http_code}" --retry 5 --retry-all-errors --retry-delay 1 https://localhost/api/v1/system/ready
            if ($codigo -ne "200") {
                [IO.File]::WriteAllBytes($destino, $atual); Restart-Service nginx
                throw "nginx.conf novo nao subiu (HTTP $codigo): anterior restaurado."
            }
        }
        Set-Content "$AppDir\dados\ultima-publicacao.txt" "$commit em $(Get-Date -Format s)" -Encoding UTF8
        Remove-Item C:\gestor-deploy\release* -Recurse -Force
    }
    Write-Host "`nPUBLICADO: $commit" -ForegroundColor Green
} catch {
    Falha $_.Exception.Message
} finally {
    Remove-PSSession $sessao -ErrorAction SilentlyContinue
}
