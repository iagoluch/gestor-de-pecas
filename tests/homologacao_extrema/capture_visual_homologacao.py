"""Captura telas críticas do Web e gera contact sheets sem expor credenciais."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import secrets
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.config import PostgresConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from tests.homologacao_extrema.seed_homologacao_extrema import (  # noqa: E402
    TARGET_DATABASE,
    _load_dsns,
    _safe_target,
)


OUTPUT = ROOT / "docs" / "screenshots" / "homologacao-extrema"
CAPTURE_SCRIPT = ROOT / "scripts" / "capture_web_preview.mjs"
BASE_URL = "http://127.0.0.1:8000"


MANAGER_ROUTES = (
    ("inicio", "/inicio/visao-geral"),
    ("recursos", "/consulta-operacional/recursos"),
    ("ops", "/producao/ordens"),
    ("qualidade", "/analises/qualidade"),
    ("paradas", "/analises/paradas"),
    ("auditoria", "/auditoria/inconsistencias"),
    ("relatorio", "/relatorios/dados-analiticos"),
    ("rastreabilidade", "/rastreabilidade/linha-do-tempo?op=HOMEXT00001"),
)

OPERATOR_PROFILES = (
    ("operador_destaque", "destaque", ""),
    ("operador_dobra", "dobra_selecao", ""),
    ("operador_dobra", "dobra_posto", "1303"),
    ("operador_usinagem", "usinagem_selecao", ""),
    ("operador_serra", "serra_selecao", ""),
    ("operador_corte", "corte_selecao", ""),
    ("operador_corte", "corte_fila", "Laser Ensis 3015"),
    ("operador_pintura", "pintura", ""),
    ("operador_solda", "solda_estacoes", ""),
)


def _db(target_dsn: str) -> Database:
    return Database(
        config=PostgresConfig(
            dsn=target_dsn,
            min_pool_size=1,
            max_pool_size=4,
            pool_timeout=8,
        )
    )


def _wait_server() -> None:
    import urllib.request

    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/v1/system/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        import time

        time.sleep(1)
    raise RuntimeError("O servidor de homologação não respondeu em 30 segundos.")


def _capture(username, password, name, route, width, height, click="") -> Path:
    output = OUTPUT / f"{name}_{width}x{height}.png"
    environment = os.environ.copy()
    environment["CAPTURE_USERNAME"] = username
    environment["CAPTURE_PASSWORD"] = password
    command = [
        "node",
        str(CAPTURE_SCRIPT),
        "--output",
        str(output),
        "--width",
        str(width),
        "--height",
        str(height),
        "--route",
        route,
        "--base-url",
        BASE_URL,
    ]
    if click:
        command.extend(("--click", click))
    completed = None
    for _attempt in range(3):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0:
            break
    if completed is None or completed.returncode:
        detail = "capturador não iniciado" if completed is None else (completed.stderr.strip() or completed.stdout.strip())
        raise RuntimeError(f"Falha ao capturar {name}: {detail}")
    if not output.is_file():
        raise RuntimeError(f"Captura não foi criada: {output}")
    return output


def _contact_sheet(paths: list[Path], output: Path, *, columns=3, thumb=(640, 360)) -> None:
    label_height = 42
    rows = (len(paths) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * thumb[0], rows * (thumb[1] + label_height)), "#F5F7FA")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for index, path in enumerate(paths):
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail(thumb, Image.Resampling.LANCZOS)
            left = (index % columns) * thumb[0] + (thumb[0] - image.width) // 2
            top = (index // columns) * (thumb[1] + label_height)
            canvas.paste(image, (left, top))
        draw.text(
            ((index % columns) * thumb[0] + 12, top + thumb[1] + 10),
            path.stem,
            fill="#081630",
            font=font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", optimize=True)


def main() -> None:
    _operational, _common_test, target_dsn, _maintenance = _load_dsns()
    target = _safe_target(target_dsn)
    if target["dbname"].casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Captura recusada: banco de homologação inesperado.")
    _wait_server()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(32)
    only = {
        value.strip()
        for value in os.getenv("HOMOLOG_CAPTURE_ONLY", "").split(",")
        if value.strip()
    }
    suffix = secrets.token_hex(5)
    db = _db(target_dsn)
    users = []
    captures: list[Path] = []
    try:
        manager = f"Homologação Visual Gestor {suffix}"
        users.append(db.criar_usuario(manager, password, "gestor"))
        operators = {}
        for level, _name, _click in OPERATOR_PROFILES:
            if level in operators:
                continue
            username = f"Homologação Visual {level} {suffix}"
            operators[level] = username
            users.append(db.criar_usuario(username, password, level))

        for name, route in MANAGER_ROUTES:
            if only and name not in only:
                continue
            for width, height in ((1920, 1080), (1600, 900), (1366, 768)):
                captures.append(_capture(manager, password, name, route, width, height))
        for level, name, click in OPERATOR_PROFILES:
            if only and name not in only:
                continue
            captures.append(
                _capture(operators[level], password, name, "/operador", 1920, 1080, click)
            )
        for level, name, click in (
            ("operador_dobra", "dobra_posto", "1303"),
            ("operador_corte", "corte_fila", "Laser Ensis 3015"),
            ("operador_solda", "solda_estacoes", ""),
        ):
            if only and name not in only:
                continue
            for width, height in ((1600, 900), (1366, 768)):
                captures.append(
                    _capture(operators[level], password, name, "/operador", width, height, click)
                )

        all_captures = sorted(
            path for path in OUTPUT.glob("*.png")
            if not path.name.startswith("contact_sheet_")
        )
        manager_names = {name for name, _ in MANAGER_ROUTES}
        manager_paths = [path for path in all_captures if path.stem.split("_")[0] in manager_names]
        operator_paths = [path for path in all_captures if path not in manager_paths]
        _contact_sheet(manager_paths, OUTPUT / "contact_sheet_gestao.png")
        _contact_sheet(operator_paths, OUTPUT / "contact_sheet_operador.png")
        (OUTPUT / "capture_manifest.txt").write_text(
            "\n".join(path.name for path in all_captures)
            + f"\ncontact_sheet_gestao.png\ncontact_sheet_operador.png\nGerado em {datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )
        print(f"{len(captures)} capturas atualizadas; {len(all_captures)} no catálogo e 2 contact sheets em {OUTPUT}")
    finally:
        valid_users = [user_id for user_id in users if user_id]
        if valid_users:
            with db.connection() as connection, connection.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios WHERE id = ANY(%s)", (valid_users,))
        db.close()


if __name__ == "__main__":
    main()
