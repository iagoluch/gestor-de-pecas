param([switch]$SkipPlugins)
$ErrorActionPreference = "Continue"

python scripts/validate_ai_workforce.py
if ($LASTEXITCODE -ne 0) { throw "IA Workforce invalida." }

if (-not $SkipPlugins) {
  if (Get-Command claude -ErrorAction SilentlyContinue) {
    claude plugin marketplace add upstash/context7 2>$null
    claude plugin install context7@context7-marketplace 2>$null
  } else { Write-Host "Claude CLI nao encontrado; .mcp.json ficou preparado." }

  if (Get-Command codex -ErrorAction SilentlyContinue) {
    codex plugin marketplace add upstash/context7 2>$null
    codex plugin add context7@context7-marketplace 2>$null
  } else { Write-Host "Codex CLI nao encontrado; .codex/config.toml ficou preparado." }
}
Write-Host "IA Workforce pronta. Reinicie Claude/Codex para recarregar configuracao."
