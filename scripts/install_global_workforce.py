"""Publica a IA Workforce deste repositório em ~/.claude para todos os projetos.

A fonte de verdade continua sendo `.claude/agents/` e `.ai/` deste repositório
(é o que o validator e o CI conferem). A cópia global só troca os caminhos
relativos por absolutos e liga as skills usadas pelos agentes via junction.
Idempotente: só grava o que mudou. Roda no SessionStart do projeto.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKER = "<!-- gerado por scripts/install_global_workforce.py do Gestor de Peças; edite a fonte no repo -->"


def render(source: str) -> str:
    ai_dir = (REPO / ".ai").as_posix()
    body = source.replace("`.ai/", f"`{ai_dir}/")
    body = body.replace("`AGENTS.md`", "o `AGENTS.md`/`CLAUDE.md` do projeto atual")
    frontmatter_end = body.index("\n---", 3) + len("\n---")
    return f"{body[:frontmatter_end]}\n{MARKER}{body[frontmatter_end:]}"


def agent_skills(text: str) -> set[str]:
    skills, inside = set(), False
    for line in text.splitlines():
        if line.strip() == "---" and inside:
            break
        if line.startswith("skills:"):
            inside = True
            continue
        if inside:
            if not line.startswith("  - "):
                break
            skills.add(line[4:].strip())
    return skills


def link_dir(target: Path, link: Path) -> None:
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def install(home: Path, quiet: bool) -> list[str]:
    agents_dst = home / "agents"
    skills_dst = home / "skills"
    agents_dst.mkdir(parents=True, exist_ok=True)
    changes: list[str] = []
    wanted_skills = {"impeccable"}
    published: set[str] = set()

    for src in sorted((REPO / ".claude" / "agents").glob("*.md")):
        text = src.read_text(encoding="utf-8")
        wanted_skills |= agent_skills(text)
        rendered = render(text)
        dst = agents_dst / src.name
        published.add(src.name)
        if not dst.exists() or dst.read_text(encoding="utf-8") != rendered:
            dst.write_text(rendered, encoding="utf-8", newline="")
            changes.append(f"agente {src.stem}")

    for stale in agents_dst.glob("*.md"):
        if stale.name not in published and MARKER in stale.read_text(encoding="utf-8"):
            stale.unlink()
            changes.append(f"removido {stale.stem}")

    for skill in sorted(wanted_skills):
        target = REPO / ".claude" / "skills" / skill
        link = skills_dst / skill
        if target.is_dir() and not link.exists():
            link_dir(target, link)
            changes.append(f"skill {skill}")

    if not quiet:
        print("\n".join(changes) if changes else "workforce global já sincronizada")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    install(args.home, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
