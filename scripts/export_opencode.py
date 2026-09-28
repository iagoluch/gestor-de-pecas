"""Exporta a configuração do Claude Code para o OpenCode (uso com o Nemotron).

Fonte de verdade continua sendo o Claude Code (`~/.claude/` e `.claude/` do repo);
este script só gera cópias em `~/.config/opencode/` e é idempotente — roda de novo
sempre que algo mudar (o plugin do projeto o chama na inicialização do OpenCode).

Gera:
  - agents/<nome>.md      a partir de ~/.claude/agents/*.md (tools -> permission)
  - commands/<nome>.md    a partir de ~/.claude/commands/*.md (+ /executar)
  - skills/<nome>/        skills dos plugins do Claude (pg, claude-code-setup)
  - plugins/*.js          plugins globais versionados em .opencode/global-plugins/
  - AGENTS.md             regras globais = ~/.claude/CLAUDE.md sem o handoff + preâmbulo
  - opencode.json         merge: MCPs globais/plugins, bloqueio das skills composio,
                          modelo Nemotron no esforço máximo
  - <repo>/opencode.json  MCPs do projeto + CLAUDE.md do projeto como instrução

Arquivos gerados levam o marcador GENERATED; arquivos sem o marcador nunca são
sobrescritos nem removidos.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import yaml

HOME = Path.home()
CLAUDE = HOME / ".claude"
OPENCODE = HOME / ".config" / "opencode"
REPO = Path(__file__).resolve().parents[1]

GENERATED = "gerado por scripts/export_opencode.py"
MARK = f"<!-- {GENERATED} (Gestor de Peças); edite a fonte no Claude Code -->"

MODEL = "opencode/nemotron-3-ultra-free"
SMALL_MODEL = "opencode/nemotron-3.5-lightning-free"

# Coleções-fonte do composio (832 skills SaaS removidas de propósito) que o
# OpenCode redescobre ao varrer ~/.claude/skills recursivamente.
SKILL_PERMISSION = {
    "*": "allow",
    "*-automation": "deny",
    "* Automation": "deny",
    "ci-cd-and-automation": "allow",
}

HANDOFF_HEADING = "## Handoff externo"
HANDOFF_STEP = re.compile(r"^1b\. .*Nemotron.*\n", re.MULTILINE)

PREAMBLE = """\
# Contexto de execução: OpenCode + Nemotron

Você é o agente de desenvolvimento deste notebook quando o Claude Code não está
disponível ou quando o usuário te entrega um prompt de tarefa. As regras abaixo
foram exportadas do Claude Code e valem para você integralmente. Onde elas citam
ferramentas do Claude, use o equivalente do OpenCode:

| Claude Code | OpenCode |
|---|---|
| `Skill({skill:"x"})` / "invoque a skill x" | ferramenta `skill` com `name: "x"` |
| `Agent` / subagente / funcionário da workforce | ferramenta `task` com o subagente de mesmo nome (`@nome`) |
| `mcp__servidor__ferramenta` | ferramenta `servidor_ferramenta` (ex.: `headroom_headroom_compress`); no OpenCode 2.x (Desktop) as ferramentas MCP e de plugin ficam dentro de `execute` — ache o nome com `search` lá dentro |
| comando de terminal (`graphify`, `pytest`, `npm`...) | ferramenta `shell`/`bash` — nunca como ferramenta ou MCP |
| `Read` / `Edit` / `Write` / `Bash` / `Grep` / `Glob` | `read` / `edit` / `write` / `bash` / `grep` / `glob` |
| `TodoWrite` | `todowrite` |
| `WebFetch` | `webfetch` |

Os hooks do Claude Code (lembretes de ponytail, graphify, headroom, type-check,
impeccable, task-observer e memória do projeto) chegam a você por plugins do
OpenCode — trate essas mensagens como instruções do sistema.

## Esforço máximo

Você roda em modelo gratuito com contexto de 1M tokens: economizar tokens NÃO é
objetivo para você. As regras de "economia de tokens" abaixo foram escritas para
o Claude (custo); para você valem só no que diz respeito a escopo e tempo.
Portanto:

1. Raciocine com profundidade antes de agir: releia o pedido, liste o que precisa
   mudar e por quê.
2. Leia os arquivos afetados por completo (não só trechos) e os consumidores
   diretos antes de editar. Confirme contratos, imports e nomes reais — nunca
   invente função, campo, rota ou arquivo.
3. Mantenha o escopo: não altere nada fora do pedido, não remova o que não foi
   pedido, não refatore por conta própria.
4. Valide de verdade: rode os testes/checagens do que mudou e leia a saída. Se
   falhar, corrija e rode de novo até passar ou até provar que a falha é
   pré-existente (mostre a evidência).
5. Execute TODOS os passos até o fim na mesma resposta. Não pare no meio para
   perguntar "posso continuar?", não entregue plano no lugar de implementação,
   não deixe TODO. Pergunte apenas quando houver decisão de negócio ambígua.
6. Ao terminar: mostre `git diff --stat`, a saída da validação e um resumo curto
   do que mudou. Nunca faça commit nem push (o commit dispara push automático) —
   isso é decisão do usuário.
7. Responda sempre em português do Brasil. Explique decisões não óbvias em um
   bloco curto:
   `✶ Insight ─────` / 2-3 pontos / `─────`.

---

"""

EXECUTAR_COMMAND = f"""\
---
description: Executa um prompt de tarefa até o fim, com validação e sem commit.
---
{MARK}
Execute a tarefa abaixo até o fim, no esforço máximo, seguindo o AGENTS.md.

<tarefa>
$ARGUMENTS
</tarefa>

Disciplina obrigatória:
1. Antes de editar, leia por completo cada arquivo citado e os consumidores
   diretos; confirme que nomes, funções e caminhos existem de fato.
2. Siga os passos na ordem, sem pular nenhum e sem sair do escopo; respeite o
   "Não altere".
3. Rode exatamente a validação pedida e leia a saída. Se falhar, corrija e rode
   de novo. Não declare pronto sem a validação passando.
4. Confira cada item do "Pronto quando".
5. Termine com: `git diff --stat`, a saída da validação e um resumo de 3-5
   linhas. Não faça commit nem push.
"""


def say(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg)


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body.lstrip("\n")


def render(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=10_000)
    return f"---\n{fm}---\n{MARK}\n{body}"


def is_generated(path: Path) -> bool:
    try:
        return GENERATED in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def sync_dir(target: Path, files: dict[str, str]) -> None:
    """Escreve os arquivos gerados e remove gerados órfãos; preserva os manuais."""
    target.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        dest = target / name
        if dest.exists() and not is_generated(dest):
            continue
        if not dest.exists() or dest.read_text(encoding="utf-8") != content:
            dest.write_text(content, encoding="utf-8", newline="\n")
    for old in target.glob("*.md"):
        if old.name not in files and is_generated(old):
            old.unlink()


def claude_tools(meta: dict) -> set[str]:
    raw = meta.get("tools")
    if raw is None:
        return {"read", "bash", "glob", "grep", "edit", "write", "webfetch"}
    items = raw if isinstance(raw, list) else str(raw).split(",")
    return {t.strip().lower() for t in items if t.strip()}


def export_agents() -> dict[str, str]:
    files = {}
    for src in sorted((CLAUDE / "agents").glob("*.md")):
        meta, body = split_frontmatter(src.read_text(encoding="utf-8"))
        tools = claude_tools(meta)
        body = re.sub(r"<!-- gerado por .*?-->\n?", "", body, count=1)
        if meta.get("skills"):
            skills = ", ".join(f"`{s}`" for s in meta["skills"])
            body = f"Ao iniciar, carregue com a ferramenta `skill`: {skills}.\n\n{body}"
        out = {
            "description": meta.get("description", src.stem),
            "mode": "subagent",
            "permission": {
                "edit": "allow" if tools & {"edit", "write"} else "deny",
                "bash": "allow" if "bash" in tools else "deny",
                "webfetch": "allow" if tools & {"webfetch", "websearch"} else "deny",
            },
        }
        files[f"{meta.get('name', src.stem)}.md"] = render(out, body)
    return files


def export_commands() -> dict[str, str]:
    files = {"executar.md": EXECUTAR_COMMAND}
    for src in sorted((CLAUDE / "commands").glob("*.md")):
        meta, body = split_frontmatter(src.read_text(encoding="utf-8"))
        out = {"description": meta.get("description", src.stem)}
        files[f"{meta.get('name', src.stem)}.md"] = render(out, body)
    return files


def installed_plugins() -> list[Path]:
    manifest = CLAUDE / "plugins" / "installed_plugins.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    enabled = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8")).get(
        "enabledPlugins", {}
    )
    paths = []
    for key, installs in data.get("plugins", {}).items():
        if not enabled.get(key):
            continue
        for inst in installs:
            path = Path(inst["installPath"])
            if path.exists():
                paths.append(path)
    return paths


def plugin_mcp_servers(root: Path) -> dict:
    servers: dict = {}
    for candidate in (root / ".mcp.json", root / ".claude-plugin" / "plugin.json"):
        if candidate.exists():
            servers.update(json.loads(candidate.read_text(encoding="utf-8")).get("mcpServers", {}))
    market = root / ".claude-plugin" / "marketplace.json"
    if market.exists():
        for plugin in json.loads(market.read_text(encoding="utf-8")).get("plugins", []):
            if isinstance(plugin.get("mcpServers"), dict):
                servers.update(plugin["mcpServers"])
    return servers


def export_plugin_skills(quiet: bool) -> None:
    target = OPENCODE / "skills"
    target.mkdir(parents=True, exist_ok=True)
    for root in installed_plugins():
        for skill_md in (root / "skills").glob("*/SKILL.md"):
            dest = target / skill_md.parent.name
            if dest.exists() and not (dest / ".exported").exists():
                continue  # skill criada manualmente no OpenCode: não mexer
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(skill_md.parent, dest)
            (dest / ".exported").write_text(GENERATED, encoding="utf-8")
            say(f"skill: {dest.name}", quiet)


def export_global_plugins() -> None:
    target = OPENCODE / "plugins"
    target.mkdir(parents=True, exist_ok=True)
    for src in (REPO / ".opencode" / "global-plugins").glob("*.js"):
        dest = target / src.name
        content = src.read_text(encoding="utf-8")
        if not dest.exists() or dest.read_text(encoding="utf-8") != content:
            dest.write_text(content, encoding="utf-8", newline="\n")


# `uv tool` rodado de dentro do Claude Desktop (app MSIX) instala o venv no
# AppData virtualizado do pacote: o lançador em ~/.local/bin só funciona para o
# Claude e, no serviço do OpenCode, morre com "uv trampoline failed to
# canonicalize script path" (MCP "Connection closed"). As ferramentas
# reinstaladas com UV_TOOL_DIR=~/.local/share/uv/tools valem para qualquer processo.
LOCAL_BIN = HOME / ".local" / "bin"
SHARED_BIN = HOME / ".local" / "share" / "uv" / "bin"


def shared_launcher(command: str) -> str:
    exe = Path(command)
    shared = SHARED_BIN / exe.name
    return str(shared) if exe.parent == LOCAL_BIN and shared.is_file() else command


def to_opencode_mcp(server: dict) -> dict:
    kind = server.get("type", "stdio")
    if kind in ("http", "sse") or "url" in server:
        url = server["url"]
        # O endpoint /oauth do context7 exige login; o público funciona sem chave.
        url = url.replace("mcp.context7.com/mcp/oauth", "mcp.context7.com/mcp")
        out = {"type": "remote", "url": url, "enabled": True}
        if server.get("headers"):
            out["headers"] = server["headers"]
        return out
    out = {
        "type": "local",
        "command": [shared_launcher(server["command"]), *server.get("args", [])],
        "enabled": True,
    }
    if server.get("env"):
        out["environment"] = server["env"]
    return out


def export_rules() -> str:
    text = (CLAUDE / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.find(HANDOFF_HEADING)
    if start != -1:
        end = text.find("\n## ", start + len(HANDOFF_HEADING))
        text = text[:start] + (text[end + 1 :] if end != -1 else "")
    text = HANDOFF_STEP.sub("", text)
    return f"{MARK}\n{PREAMBLE}{text}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8", newline="\n")


def export_global_config() -> None:
    path = OPENCODE / "opencode.json"
    cfg = load_json(path)
    cfg.setdefault("$schema", "https://opencode.ai/config.json")
    cfg["model"] = MODEL
    cfg["small_model"] = SMALL_MODEL

    mcp = cfg.setdefault("mcp", {})
    servers = dict(load_json(HOME / ".claude.json").get("mcpServers", {}))
    for root in installed_plugins():
        servers.update(plugin_mcp_servers(root))
    for name, server in servers.items():
        mcp[name] = to_opencode_mcp(server)

    permission = cfg.setdefault("permission", {})
    permission["skill"] = SKILL_PERMISSION
    write_json(path, cfg)

    # O opencode.jsonc (provider ollama) é carregado depois e venceria o model.
    jsonc = OPENCODE / "opencode.jsonc"
    if jsonc.exists():
        text = jsonc.read_text(encoding="utf-8")
        new = re.sub(r'(?m)^  "model":\s*"[^"]*"', f'  "model": "{MODEL}"', text)
        if new != text:
            jsonc.write_text(new, encoding="utf-8", newline="\n")


def export_project_config() -> None:
    path = REPO / "opencode.json"
    cfg = load_json(path)
    cfg.setdefault("$schema", "https://opencode.ai/config.json")
    instructions = cfg.setdefault("instructions", [])
    if "CLAUDE.md" not in instructions:
        instructions.append("CLAUDE.md")
    servers = load_json(REPO / ".mcp.json").get("mcpServers", {})
    if servers:
        mcp = cfg.setdefault("mcp", {})
        for name, server in servers.items():
            mcp[name] = to_opencode_mcp(server)
    write_json(path, cfg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true")
    quiet = parser.parse_args().quiet

    agents = export_agents()
    sync_dir(OPENCODE / "agents", agents)
    commands = export_commands()
    sync_dir(OPENCODE / "commands", commands)
    export_plugin_skills(quiet)
    export_global_plugins()

    rules = OPENCODE / "AGENTS.md"
    if not rules.exists() or is_generated(rules):
        rules.write_text(export_rules(), encoding="utf-8", newline="\n")

    export_global_config()
    export_project_config()
    say(
        f"OpenCode sincronizado: {len(agents)} agentes, {len(commands)} comandos, "
        f"regras em {rules}",
        quiet,
    )


if __name__ == "__main__":
    main()
