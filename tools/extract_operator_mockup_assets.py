"""Extract small, reusable operator assets from the approved PNG mockups.

Only pictograms are extracted. Screens, forms and controls remain native Web
widgets so the resulting interface stays interactive and responsive.
"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageChops


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_ROOT = PROJECT_ROOT.parents[1]
DESIGN_ROOT = Path(
    os.environ.get(
        "GESTOR_DESIGN_ROOT",
        DOCUMENTS_ROOT / "Desenvolvimento" / "Novos Designs Gestor de Peça",
    )
)
MOCKUPS = DESIGN_ROOT / "Telas" / "Operador"
OUTPUT = PROJECT_ROOT / "assets" / "operator_mockup"
PROVIDED_ICONS = Path(
    os.environ.get("GESTOR_OPERATOR_ICONS_ZIP", DESIGN_ROOT / "Icons.zip")
)


def extract(source: Path, box: tuple[int, int, int, int], name: str) -> None:
    image = Image.open(source).convert("RGBA")
    output = OUTPUT / name
    output.parent.mkdir(parents=True, exist_ok=True)
    image.crop(box).save(output)
    print(f"{output.name}: {box}")


def transparent_copy(name: str, background=(8, 102, 245), tolerance=34) -> None:
    source = Image.open(OUTPUT / name).convert("RGBA")
    pixels = source.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, _alpha = pixels[x, y]
            distance = abs(red - background[0]) + abs(green - background[1]) + abs(blue - background[2])
            if distance <= tolerance:
                pixels[x, y] = (red, green, blue, 0)
    output = OUTPUT / name.replace(".png", "_transparent.png")
    source.save(output)
    print(f"{output.name}: chroma-key {background}")


def import_provided_icons() -> None:
    """Import the button artwork supplied with the revised operator mockups."""

    wanted = {
        "finalizado": "provided_action_finish.png",
        "inicio": "provided_action_start.png",
        "parada": "provided_action_stop.png",
        "retrabalho": "provided_action_rework.png",
        "setup": "provided_action_setup.png",
        "ver mais": "provided_more.png",
    }
    with ZipFile(PROVIDED_ICONS) as archive:
        candidates = []
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".png"):
                continue
            stem = Path(info.filename).stem.casefold()
            if stem.startswith("logo_"):
                continue
            candidates.append((stem, info))

        for key, output_name in wanted.items():
            if key == "inicio":
                match = next((item for stem, item in candidates if stem.startswith("in")), None)
            else:
                match = next((item for stem, item in candidates if stem == key), None)
            if match is None:
                raise FileNotFoundError(f"Icone fornecido nao encontrado no zip: {key}")

            image = Image.open(BytesIO(archive.read(match))).convert("RGBA")
            if key == "ver mais":
                rgb = image.convert("RGB")
                white = Image.new("RGB", image.size, (255, 255, 255))
                bounds = ImageChops.difference(rgb, white).getbbox()
                if bounds:
                    image = image.crop(bounds)
            output = OUTPUT / output_name
            output.parent.mkdir(parents=True, exist_ok=True)
            image.save(output)
            print(f"{output.name}: imported from {match.filename}, size={image.size}")


def main() -> None:
    import_provided_icons()
    dobra = MOCKUPS / "Apontamentos" / "Caldeiraria - OK" / "Dobra" / "Dobra_1303.png"
    action_crops = {
        "action_start.png": (674, 447, 731, 488),
        "action_stop.png": (954, 447, 1011, 488),
        "action_finish.png": (1232, 447, 1281, 488),
        "action_setup.png": (816, 502, 873, 543),
        "action_rework.png": (1094, 502, 1143, 543),
    }
    for name, box in action_crops.items():
        extract(dobra, box, name)
    transparent_copy("action_stop.png", background=(255, 49, 49), tolerance=34)
    transparent_copy("action_finish.png", background=(255, 222, 89), tolerance=34)
    extract(dobra, (23, 47, 270, 99), "logo_operator.png")
    extract(dobra, (27, 151, 84, 214), "profile_operator.png")
    transparent_copy("profile_operator.png", background=(3, 38, 75), tolerance=34)

    sector_sources = {
        "dobra": dobra,
        "usinagem": MOCKUPS / "Apontamentos" / "Caldeiraria - OK" / "Usinagem" / "Usinagem_Eurostec.png",
        "serra": MOCKUPS / "Apontamentos" / "Caldeiraria - OK" / "Serra" / "Serra_SFG-330.png",
        "corte": MOCKUPS / "Apontamentos" / "Corte - OK" / "Laser" / "Corte_Laser.png",
        "pintura": MOCKUPS / "Apontamentos" / "Pintura - OK" / "Pintura.png",
        "solda": MOCKUPS / "Apontamentos" / "Solda - OK" / "Solda.png",
        "destaque": MOCKUPS / "Apontamentos" / "Caldeiraria - OK" / "Destaque" / "Destaque.png",
    }
    for sector, source in sector_sources.items():
        name = f"nav_{sector}.png"
        extract(source, (27, 316, 77, 365), name)
        transparent_copy(name)


if __name__ == "__main__":
    main()
