"""Remove os artefatos de cache descartáveis do workspace.

Só apaga o que é regenerável e já está declarado no `.gitignore`. Nada de
código, dado, documento, evidência, `.env` ou backup é tocado.

Uso:

    python limpar_caches.py --dry-run   # apenas lista o que seria removido
    python limpar_caches.py             # remove os caches
    python limpar_caches.py --build     # também remove artefatos de build

`web/dist` fica fora do padrão de propósito: quando o backend roda com
`GESTOR_WEB_SERVE_STATIC=1` é essa pasta que serve a interface, e apagá-la
derruba a UI até um novo `npm run build`. Por isso só sai com `--build`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parent

# Diretórios em que a varredura nunca entra: ambientes, dependências,
# histórico do git e todo o conteúdo real do projeto.
PODAR = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "assets",
    "backups",
    "dados",
    "data",
    "docs",
    "integracao_totvs_referencia",
    "outputs",
}

# Diretórios de cache removidos por inteiro.
DIRETORIOS_CACHE = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pyright",
    ".tox",
    ".nox",
    "htmlcov",
}

# Arquivos soltos de cache.
SUFIXOS_CACHE = (".pyc", ".pyo", ".pyd", ".tsbuildinfo")
NOMES_CACHE = ("coverage.xml",)

# Alvos fixos, fora da varredura recursiva.
ALVOS_DIRETOS = (
    Path("web") / "node_modules" / ".vite",
    Path(".vscode") / ".cache",
    Path("playwright-report"),
    Path("test-results"),
)

# Somente com --build: artefatos regeneráveis que o sistema em execução usa.
ALVOS_BUILD = (Path("web") / "dist",)


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove caches regeneráveis do workspace do Gestor de Peças."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista o que seria removido, sem apagar nada.",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Também remove web/dist. Exige novo build para servir a interface.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Mostra apenas o resumo final.",
    )
    return parser.parse_args()


def _dentro_da_raiz(caminho: Path) -> bool:
    """Impede que um link simbólico leve a remoção para fora do projeto."""

    try:
        return PROJECT_ROOT in caminho.resolve().parents or caminho.resolve() == PROJECT_ROOT
    except OSError:
        return False


def _tamanho(caminho: Path) -> int:
    if caminho.is_file():
        try:
            return caminho.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in caminho.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _coletar() -> tuple[list[Path], list[Path]]:
    """Percorre o projeto uma vez, registrando caches sem descer neles."""

    diretorios: list[Path] = []
    arquivos: list[Path] = []

    for atual, subdirs, nomes in PROJECT_ROOT.walk():
        manter: list[str] = []
        for nome in sorted(subdirs):
            if nome in DIRETORIOS_CACHE:
                # Registra o diretório inteiro e não desce nele.
                diretorios.append(atual / nome)
            elif nome not in PODAR:
                manter.append(nome)
        subdirs[:] = manter

        for nome in sorted(nomes):
            if nome.endswith(SUFIXOS_CACHE) or nome in NOMES_CACHE:
                arquivos.append(atual / nome)
            elif nome == ".coverage" or nome.startswith(".coverage."):
                arquivos.append(atual / nome)

    for relativo in ALVOS_DIRETOS:
        alvo = PROJECT_ROOT / relativo
        if alvo.is_dir():
            diretorios.append(alvo)

    diretorios = [item for item in diretorios if _dentro_da_raiz(item)]
    arquivos = [item for item in arquivos if _dentro_da_raiz(item)]
    return diretorios, arquivos


def main() -> int:
    # O console do Windows costuma abrir em cp1252 e corromper os acentos.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = _argumentos()
    diretorios, arquivos = _coletar()

    if args.build:
        for relativo in ALVOS_BUILD:
            alvo = PROJECT_ROOT / relativo
            if alvo.is_dir() and _dentro_da_raiz(alvo):
                diretorios.append(alvo)

    alvos = [(item, True) for item in diretorios] + [(item, False) for item in arquivos]
    if not alvos:
        print("Nenhum cache encontrado. Workspace já está limpo.")
        return 0

    liberado = 0
    removidos = 0
    falhas: list[tuple[Path, str]] = []

    for alvo, e_diretorio in alvos:
        if not alvo.exists():
            continue
        tamanho = _tamanho(alvo)
        relativo = alvo.relative_to(PROJECT_ROOT)
        if args.dry_run:
            if not args.quiet:
                print(f"[dry-run] {relativo}")
            liberado += tamanho
            removidos += 1
            continue
        try:
            if e_diretorio:
                shutil.rmtree(alvo)
            else:
                alvo.unlink()
        except OSError as exc:
            # No Windows um .pyc em uso pelo processo do Gestor fica travado.
            falhas.append((relativo, str(exc)))
            continue
        if not args.quiet:
            print(f"removido {relativo}")
        liberado += tamanho
        removidos += 1

    acao = "seriam removidos" if args.dry_run else "removidos"
    print(f"\n{removidos} itens {acao} — {liberado / 1024 / 1024:.1f} MB")
    if not args.build:
        print("web/dist preservado (use --build para removê-lo também).")
    if falhas:
        print(f"\n{len(falhas)} itens não puderam ser removidos:")
        for relativo, erro in falhas:
            print(f"  {relativo}: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
