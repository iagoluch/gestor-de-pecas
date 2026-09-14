"""Gera a entrega Web sem ambientes, credenciais, dependências locais ou caches."""

from __future__ import annotations

from pathlib import Path
import sys
import zipfile


EXCLUDED_DIRECTORIES = {
    "%SystemDrive%",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    ".vite",
    "__pycache__",
    "backups",
    "dados",
    "node_modules",
    "output",
    "outputs",
}
EXCLUDED_NAMES = {
    ".env",
    "cookies.json",
    "pnpm-lock.yaml",
}
EXCLUDED_SUFFIXES = {".key", ".log", ".pem", ".pyc", ".pyo", ".tsbuildinfo"}
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def should_include(relative: Path, output: Path) -> bool:
    if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
        return False
    if relative.name in EXCLUDED_NAMES or relative.suffix.casefold() in EXCLUDED_SUFFIXES:
        return False
    if relative.resolve() == output.resolve():
        return False
    return True


def validate_text(path: Path) -> None:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return
    path.read_text(encoding="utf-8")


def package(root: Path, output: Path) -> tuple[int, int]:
    root = root.resolve()
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError("O ZIP final deve ser criado fora da raiz empacotada.")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and should_include(path.relative_to(root), output)
    ]
    files.sort(key=lambda item: item.relative_to(root).as_posix().casefold())
    for path in files:
        validate_text(path)

    archive_root = "Gestor de Peças - Web"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            name = f"{archive_root}/{relative}"
            info = zipfile.ZipInfo.from_file(path, arcname=name)
            info.flag_bits |= 0x800
            info.compress_type = zipfile.ZIP_DEFLATED
            info._compresslevel = 9
            archive.writestr(info, path.read_bytes())

    with zipfile.ZipFile(output, "r") as archive:
        broken = archive.testzip()
        if broken:
            raise RuntimeError(f"Entrada corrompida no ZIP: {broken}")
        names = archive.namelist()
        forbidden = [
            name for name in names
            if any(part in EXCLUDED_DIRECTORIES for part in Path(name).parts)
            or Path(name).name in EXCLUDED_NAMES
            or Path(name).suffix.casefold() in EXCLUDED_SUFFIXES
        ]
        if forbidden:
            raise RuntimeError(f"Entradas proibidas no ZIP: {forbidden[:5]}")
        utf8_named = sum(1 for item in archive.infolist() if item.flag_bits & 0x800)
    return len(files), utf8_named


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else project_root.parent / "Gestor de Peças - Web Final.zip"
    file_count, utf8_count = package(project_root, target)
    print(f"ZIP={target}")
    print(f"FILES={file_count}")
    print(f"UTF8_FLAGGED_NAMES={utf8_count}")
    print(f"SIZE_BYTES={target.stat().st_size}")
