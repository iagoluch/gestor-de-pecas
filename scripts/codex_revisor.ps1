<#
Chama o Codex em modo enxuto (somente leitura) para revisar uma mudança.
Uso:
  powershell -File scripts\codex_revisor.ps1 -Tarefa "Revise por bugs e regressões"
  powershell -File scripts\codex_revisor.ps1 -Tarefa "..." -Arquivos src\a.py,src\b.py
Poupa tokens: CODEX_HOME isolado (~\.codex-lean: sem plugins/MCP/hooks/AGENTS global),
AGENTS.md do projeto desligado, MCPs do projeto desligados, esforço baixo, sem resumo de
raciocínio, sessão efêmera e o diff vai pelo stdin (Codex não precisa gastar passos lendo).
Pré-requisito: ~\.codex-lean\auth.json (cópia do login) e config.toml mínimo.
#>
param(
    [Parameter(Mandatory = $true)][string]$Tarefa,
    [string[]]$Arquivos,
    [ValidateSet('low', 'medium', 'high')][string]$Esforco = 'low',
    [int]$MaxChars = 60000,
    [string]$Base = 'HEAD'   # ex.: HEAD~1 para revisar o último commit
)

$raiz = Split-Path -Parent $PSScriptRoot
$lean = Join-Path $env:USERPROFILE '.codex-lean'
if (-not (Test-Path (Join-Path $lean 'auth.json'))) { throw "Falta $lean\auth.json (copie de ~\.codex\auth.json)" }
$saida = Join-Path $env:TEMP 'codex_revisor_ultima.txt'

Push-Location $raiz
try {
    if ($Arquivos) { $material = git diff $Base -- $Arquivos | Out-String } else { $material = git diff $Base | Out-String }
    if (-not $material.Trim()) { throw "Sem diff para revisar (git diff $Base vazio)." }
    if ($material.Length -gt $MaxChars) {
        $material = $material.Substring(0, $MaxChars) + "`n[... diff truncado em $MaxChars caracteres ...]"
    }

    $instrucao = @"
Você é revisor externo do Gestor de Peças (Python/FastAPI, React/TS, PostgreSQL).
Todo o material está abaixo; NÃO use ferramentas nem leia arquivos. Somente leitura.
Liste só achados concretos: arquivo:linha, problema, cenário de falha. Sem elogios nem resumo.
Se não houver problema real, responda 'sem achados'. Máximo 25 linhas.
TAREFA: $Tarefa
"@

    $vazio = Join-Path $lean 'vazio'   # pasta vazia: Codex não vê o repo (só o diff do stdin)
    New-Item -ItemType Directory -Force $vazio | Out-Null
    Remove-Item $saida -ErrorAction SilentlyContinue
    $env:CODEX_HOME = $lean
    $cfgEsforco = "model_reasoning_effort=`"$Esforco`""
    $material | codex exec `
        --ephemeral `        --sandbox read-only `
        --skip-git-repo-check `
        -C $vazio `
        -c $cfgEsforco `
        -c 'model_reasoning_summary="none"' `
        -c 'project_doc_max_bytes=0' `
        -o $saida `
        $instrucao | Out-Null

    if (Test-Path $saida) { Get-Content $saida -Encoding UTF8 }
}
finally {
    Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue
    Pop-Location
}
