# Registra nesta VM o runner self-hosted do GitHub Actions (label gestor-pecas-vm) que
# executa o job "deploy" do .github/workflows/deploy.yml. Rodar como Administrador DEPOIS
# do instalar_vm.ps1 (o runner so enxerga o pg_dump no PATH se subir depois dele).
#
# O runner roda numa conta virtual do Windows (NT SERVICE\<servico>, sem senha) com o
# minimo que o deploy usa: escrever em C:\gestor-pecas (e no snapshot .previous), ler o
# .env (backup pre-deploy), parar/iniciar os servicos gestor-pecas e nginx e regravar
# C:\nginx\conf\nginx.conf. NETWORK SERVICE, o padrao do runner, nao faz nada disso.
# O nginx tambem roda em conta virtual (instalar_vm.ps1): um conf adulterado alcanca so
# o que o nginx le (a chave TLS). As tres contas perdem SeImpersonatePrivilege (sc privs),
# o que fecha o caminho para SYSTEM.
#
# Token: Settings > Actions > Runners > New self-hosted runner (vale 1 h; nao o imprima nem o guarde).
# Sem -Token, o script pede sem ecoar. Reexecutar e seguro: download, registro e
# permissoes ja feitos sao mantidos.
[CmdletBinding()]
param(
    [string]$Token,
    [string]$Repo = "https://github.com/iagoluch/gestor-de-pecas",
    [string]$RunnerDir = "C:\actions-runner",
    [string]$AppDir = "C:\gestor-pecas",
    [string]$NginxDir = "C:\nginx"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Versao = "2.337.0"
$Sha256 = "1150692afa94e71f872017e254ea55b6eece1eece3fe7e3a6d4c93d0a1b85cfc"

function Passo([string]$t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Executar([string]$exe, [string[]]$argumentos) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "$exe falhou (codigo $LASTEXITCODE)." }
}

foreach ($s in "gestor-pecas", "nginx") {
    if (-not (Get-Service $s -ErrorAction SilentlyContinue)) { throw "Servico $s nao existe: rode o instalar_vm.ps1 antes." }
}
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) { throw "pg_dump fora do PATH: rode o instalar_vm.ps1 antes." }
if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) { throw "PowerShell 7 (pwsh) ausente: o deploy.yml usa shell: pwsh." }

Passo "Runner $Versao em $RunnerDir"
New-Item -ItemType Directory -Force $RunnerDir | Out-Null
# Sem a heranca de C:\ (Users criam arquivos na raiz) antes de executar qualquer coisa aqui.
Executar icacls @($RunnerDir, "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "/Q")
# Ainda nao registrado: extrai de novo, conferido, por cima do que houver na pasta.
if (-not (Test-Path "$RunnerDir\.runner")) {
    $zip = "$env:TEMP\actions-runner-win-x64-$Versao.zip"
    curl.exe -fsSL --retry 3 -o $zip "https://github.com/actions/runner/releases/download/v$Versao/actions-runner-win-x64-$Versao.zip"
    if ($LASTEXITCODE) { throw "Download do runner falhou ($LASTEXITCODE)." }
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $Sha256) { throw "SHA-256 do runner nao confere: download adulterado ou versao trocada." }
    Executar tar.exe @("-xf", $zip, "-C", $RunnerDir)
    Remove-Item $zip
}

Passo "Registro no GitHub"
if (-not (Test-Path "$RunnerDir\.runner")) {
    if (-not $Token) {
        $seguro = Read-Host "Token de registro do runner" -AsSecureString
        $Token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro))
    }
    Push-Location $RunnerDir
    try {
        Executar .\config.cmd @("--unattended", "--url", $Repo, "--token", $Token, "--name", $env:COMPUTERNAME.ToLower(),
            "--labels", "gestor-pecas-vm", "--runasservice", "--replace")
    } finally { Pop-Location }
} else {
    Write-Host "Ja registrado: mantido. Para trocar de repositorio: .\config.cmd remove --token <token> e rode de novo."
}
$servico = (Get-Content "$RunnerDir\.service" -TotalCount 1).Trim()
# O runner escreve no .service: so um nome de servico de runner chega ao sc config.
if ($servico -notmatch '^actions\.runner\.[\w.-]+$') { throw "Nome de servico inesperado em $RunnerDir\.service." }
$conta = "NT SERVICE\$servico"

Passo "Conta do servico: $conta"
Stop-Service $servico
Executar sc.exe @("config", $servico, "obj=", $conta)
# Sem SeImpersonatePrivilege (grupo SERVICE), que leva a SYSTEM por exploits "potato".
Executar sc.exe @("privs", $servico, "SeChangeNotifyPrivilege/SeCreateGlobalPrivilege")
Executar icacls @($RunnerDir, "/grant", "${conta}:(OI)(CI)M", "/Q")
Executar icacls @($AppDir, "/grant", "${conta}:(OI)(CI)M", "/Q")
# Snapshot do rollback (deploy_release.ps1): mesma restricao da pasta do app.
New-Item -ItemType Directory -Force "$AppDir.previous" | Out-Null
Executar icacls @("$AppDir.previous", "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
    "${conta}:(OI)(CI)M", "/Q")
# So o arquivo, nao a pasta.
Executar icacls @("$NginxDir\conf\nginx.conf", "/grant", "${conta}:M", "/Q")

# Consultar, parar e iniciar (sem DELETE, WRITE_DAC nem controle customizado) os servicos
# que o deploy reinicia. Uma ACE anterior desta conta e trocada pela atual.
$sid = (New-Object Security.Principal.NTAccount $conta).Translate([Security.Principal.SecurityIdentifier]).Value
foreach ($s in "gestor-pecas", "nginx") {
    $atual = (sc.exe sdshow $s | Where-Object { $_.Trim() }) -join ""
    $sddl = $atual -replace "\(A;;[A-Z]+;;;$sid\)", ""
    $i = $sddl.IndexOf("S:")
    $ace = "(A;;CCLCSWRPWPLORC;;;$sid)"
    $novo = if ($i -ge 0) { $sddl.Insert($i, $ace) } else { $sddl + $ace }
    if ($novo -ne $atual) { Executar sc.exe @("sdset", $s, $novo) }
}

Start-Service $servico
Write-Host "`nRunner ativo ($servico). Confira em $Repo/settings/actions/runners (status Idle)." -ForegroundColor Green
