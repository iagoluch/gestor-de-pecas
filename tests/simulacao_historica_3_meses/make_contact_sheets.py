"""Monta as folhas de contato da simulação a partir das capturas reais."""

from __future__ import annotations

from datetime import datetime
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "screenshots" / "simulacao-3-meses"
FONT_REGULAR = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")


ANALYSES = (
    "ANALISE_OEE.png",
    "ANALISE_HORAS_UTILIZACAO.png",
    "ANALISE_PARADAS.png",
    "ANALISE_SETUP.png",
    "ANALISE_QUALIDADE.png",
    "ANALISE_TEMPO_PADRAO_REAL.png",
    "ANALISE_CRONOANALISE.png",
    "ANALISE_CAPACIDADE_GARGALOS.png",
)

OPERATORS = (
    "OPERADOR_DESTAQUE.png",
    "OPERADOR_DOBRA_SELECAO.png",
    "OPERADOR_DOBRA_POSTO.png",
    "OPERADOR_USINAGEM_SELECAO.png",
    "OPERADOR_SERRA_SELECAO.png",
    "OPERADOR_CORTE_SELECAO.png",
    "OPERADOR_CORTE_FILA.png",
    "OPERADOR_PINTURA.png",
    "OPERADOR_SOLDA_ESTACOES.png",
)

MANAGEMENT = tuple(
    path.name
    for path in sorted(OUTPUT.glob("*.png"))
    if not path.name.startswith(("OPERADOR_", "RESPONSIVO_OPERADOR_", "CALENDARIO_BASE"))
)


RESPONSIVE_VIEWPORTS = {
    "RESPONSIVO_GESTAO_1600x900.png": (1600, 900),
    "RESPONSIVO_GESTAO_1366x768.png": (1366, 768),
    "RESPONSIVO_OPERADOR_1600x900.png": (1600, 900),
    "RESPONSIVO_OPERADOR_1366x768.png": (1366, 768),
}


def validate_capture_geometry(paths: list[Path]) -> None:
    """Recusa capturas cortadas antes de montar as folhas de contato."""

    errors: list[str] = []
    for path in paths:
        expected_width, minimum_height = RESPONSIVE_VIEWPORTS.get(path.name, (1920, 1080))
        # O screenshot full-page do Chromium exclui a barra de rolagem vertical
        # (15 px no Windows), embora a viewport continue na largura solicitada.
        minimum_width = expected_width - 20
        with Image.open(path) as image:
            if not minimum_width <= image.width <= expected_width or image.height < minimum_height:
                errors.append(
                    f"{path.name}: {image.width}x{image.height}; "
                    f"esperado largura entre {minimum_width} e {expected_width} "
                    f"e altura mínima de {minimum_height}"
                )
    if errors:
        raise RuntimeError("Capturas incompletas:\n- " + "\n- ".join(errors))


def _font(path: Path, size: int):
    return ImageFont.truetype(str(path), size=size)


def _label(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("x", "×")


def make_sheet(filename: str, title: str, images: tuple[str, ...], columns: int) -> Path:
    paths = [OUTPUT / name for name in images]
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        raise RuntimeError(f"Capturas ausentes: {', '.join(missing)}")

    width = 1920
    outer = 28
    gap = 18
    header = 82
    label_height = 34
    cell_width = (width - outer * 2 - gap * (columns - 1)) // columns
    image_height = round(cell_width * 9 / 16)
    cell_height = image_height + label_height
    rows = math.ceil(len(paths) / columns)
    height = header + outer + rows * cell_height + (rows - 1) * gap + outer
    canvas = Image.new("RGB", (width, height), "#F5F7FA")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width, header), fill="#001E3F")
    draw.text((outer, 22), title, fill="#FFFFFF", font=_font(FONT_BOLD, 30))

    for index, path in enumerate(paths):
        row, column = divmod(index, columns)
        x = outer + column * (cell_width + gap)
        y = header + outer + row * (cell_height + gap)
        with Image.open(path) as source:
            rendered = ImageOps.contain(source.convert("RGB"), (cell_width, image_height), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_width, image_height), "#FFFFFF")
        frame.paste(rendered, ((cell_width - rendered.width) // 2, (image_height - rendered.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y, x + cell_width - 1, y + image_height - 1), outline="#C7D3E2", width=1)
        draw.text((x + 8, y + image_height + 7), _label(path.name), fill="#081630", font=_font(FONT_REGULAR, 17))

    destination = OUTPUT / filename
    canvas.save(destination, "JPEG", quality=91, optimize=True, subsampling=0)
    return destination


def main() -> None:
    captures = sorted(OUTPUT.glob("*.png"))
    validate_capture_geometry(captures)

    outputs = [
        make_sheet("MANAGEMENT_JUNHO.jpg", "Management View — Junho de 2026", ("MANAGEMENT_JUNHO.png",), 1),
        make_sheet("MANAGEMENT_JULHO.jpg", "Management View — Julho de 2026", ("MANAGEMENT_JULHO.png",), 1),
        make_sheet("MANAGEMENT_AGOSTO.jpg", "Management View — Agosto até 24/08/2026", ("MANAGEMENT_AGOSTO.png",), 1),
        make_sheet("ANALISES_3_MESES.jpg", "Análises — Simulação histórica de três meses", ANALYSES, 3),
        make_sheet("OPERADOR_ESTADO_ATUAL.jpg", "Operadores — Estado atual em 24/08/2026 08:32", OPERATORS, 3),
        make_sheet("contact_sheet_gestao.jpg", "Gestão Web — Catálogo completo da simulação", MANAGEMENT, 3),
        make_sheet("contact_sheet_operacao.jpg", "Operação Web — Catálogo da simulação", OPERATORS, 3),
    ]

    manifest = [
        "# Capturas da simulação histórica de três meses",
        f"Gerado em: {datetime.now().isoformat(timespec='seconds')}",
        "Viewport principal: 1920 × 1080",
        "",
    ]
    for path in [*captures, *outputs]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            manifest.append(f"{path.name}|{image.width}x{image.height}|sha256:{digest}")
    (OUTPUT / "capture_manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"{len(captures)} capturas e {len(outputs)} folhas de contato verificadas em {OUTPUT}")


if __name__ == "__main__":
    main()
