"""Varredura E2E visual de todas as rotas da gestão contra o preview isolado.

Não é coletado pelo pytest (sem prefixo test_). Uso:
    uvicorn tests.web_preview_api:app --port 8010 &
    python tests/e2e_sweep.py
Gera, em docs/auditoria_2026-10-01/e2e/: vídeo, trace.zip, um PNG por rota,
results.json e galeria index.html. Falha (exit 1) se alguma rota tiver erro de
console, requisição >= 400 ou texto interno cru ("undefined", "[object", "NaN").
"""
import html
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
OUT = Path(__file__).resolve().parents[1] / "docs" / "auditoria_2026-10-01" / "e2e"
APP = Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx"
SKIP = {"inicio/andon", "inicio/solda"}  # só redirecionam
RAW = re.compile(r"undefined|\[object |\bNaN\b|\bnull\b")


def routes():
    paths = re.findall(r'<Route\s+path="([a-z][^"*]*)"', APP.read_text(encoding="utf-8"))
    return ["/" + p for p in paths if p not in SKIP] + ["/andon", "/welding-management", "/operador"]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(OUT / "video"),
            record_video_size={"width": 1280, "height": 800},
        )
        ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        for route in routes():
            errors, bad = [], []
            on_console = lambda m: errors.append(m.text) if m.type == "error" else None
            on_response = lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None
            page.on("console", on_console)
            page.on("response", on_response)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE + route, wait_until="networkidle")
            page.wait_for_timeout(600)
            shot = route.strip("/").replace("/", "__") + ".png"
            page.screenshot(path=str(OUT / shot), full_page=True)
            text = page.inner_text("body")
            raw = sorted(set(RAW.findall(text)))
            results.append({"route": route, "shot": shot, "console": errors[:5], "http": bad[:5],
                            "raw": raw, "ok": not (errors or bad or raw)})
            page.remove_listener("console", on_console)
            page.remove_listener("response", on_response)
        ctx.tracing.stop(path=str(OUT / "trace.zip"))
        ctx.close()
        browser.close()
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    cards = "".join(
        f'<figure class="{"ok" if r["ok"] else "bad"}"><a href="{r["shot"]}"><img src="{r["shot"]}" loading="lazy"></a>'
        f'<figcaption><b>{html.escape(r["route"])}</b> {"OK" if r["ok"] else html.escape(json.dumps({k: r[k] for k in ("console", "http", "raw")}, ensure_ascii=False))}</figcaption></figure>'
        for r in results
    )
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Galeria E2E</title>"
        "<style>body{font:14px system-ui;margin:16px}figure{display:inline-block;width:340px;margin:8px;vertical-align:top}"
        "img{width:100%;border:3px solid #2a2}.bad img{border-color:#c22}figcaption{word-break:break-all}</style>"
        f"<h1>Varredura E2E — {sum(r['ok'] for r in results)}/{len(results)} rotas OK</h1>{cards}",
        encoding="utf-8",
    )
    bad = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(bad)}/{len(results)} OK")
    for r in bad:
        print("FALHA", r["route"], r["console"], r["http"], r["raw"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
