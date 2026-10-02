"""Galeria única da auditoria E2E: varredura de rotas, fluxos roteirizados e caminhada aleatória.

    python tests/e2e_gallery.py
Lê docs/auditoria_2026-10-01/e2e/ (results.json, random/random_report.json, PNGs) e
escreve e2e/galeria.html, com caminhos relativos para abrir direto do repositório.
"""
import html
import json
from pathlib import Path

E2E = Path(__file__).resolve().parents[1] / "docs" / "auditoria_2026-10-01" / "e2e"
FLUXOS = {"operador": "Operador Dobra (1303)", "destaque": "Destaque", "qualidade": "Portão Setup/Qualidade"}


def figure(path: Path, caption: str, ok: bool = True) -> str:
    rel = path.relative_to(E2E).as_posix()
    mark = "" if ok else " ❌"
    return (f'<figure class="{"" if ok else "bad"}"><a href="{rel}"><img loading="lazy" src="{rel}"></a>'
            f"<figcaption>{html.escape(caption)}{mark}</figcaption></figure>")


def sweep_section() -> str:
    results = json.loads((E2E / "results.json").read_text(encoding="utf-8"))
    ok = sum(r["ok"] for r in results)
    figs = "".join(figure(E2E / r["shot"], r["route"], r["ok"]) for r in results)
    return f"<h2>Varredura de rotas — {ok}/{len(results)} sem erro</h2><div class=grid>{figs}</div>"


def flow_sections() -> str:
    parts = []
    for folder, title in FLUXOS.items():
        shots = sorted((E2E / folder).glob("*.png"))
        if shots:
            figs = "".join(figure(p, p.stem.replace("_", " ")) for p in shots)
            parts.append(f"<h2>Fluxo: {title} — {len(shots)} passos</h2><div class=grid>{figs}</div>")
    return "".join(parts)


def random_section() -> str:
    report = E2E / "random" / "random_report.json"
    if not report.exists():
        return ""
    runs = json.loads(report.read_text(encoding="utf-8"))
    rows = "".join(
        f"<tr><td>{html.escape(str(r['profile']))}</td><td>{r['seed']}</td><td>{r['steps']}</td>"
        f"<td>{r['distinct_controls']}</td><td>{len(r['violations'])}</td></tr>" for r in runs)
    return ("<h2>Caminhada aleatória (relatório da última execução)</h2><table><tr><th>perfil</th><th>semente</th>"
            f"<th>passos</th><th>controles distintos</th><th>violações</th></tr>{rows}</table>")


def main() -> None:
    page = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Galeria E2E — Gestor de Peças</title>
<style>body{{font-family:system-ui;margin:24px;background:#fafafa;color:#111}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
figure{{margin:0;border:1px solid #ccc;background:#fff}}figure.bad{{border-color:#c00}}
img{{width:100%;display:block}}figcaption{{font-size:12px;padding:4px 6px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 10px}}</style>
<h1>Galeria E2E — auditoria 01-02/10/2026</h1>{sweep_section()}{flow_sections()}{random_section()}"""
    (E2E / "galeria.html").write_text(page, encoding="utf-8")
    print("galeria.html escrita")


if __name__ == "__main__":
    main()
