"""Caminhada aleatória (monkey test) com semente contra o preview isolado.

Não é coletado pelo pytest. Sobe um servidor novo por execução (estado em
memória) e, a cada passo, escolhe ao acaso um controle visível e habilitado
(botão, link interno, campo, select, aba, checkbox), preenche campos com
entradas hostis (vazio, negativo, enorme, HTML, emoji) ou abre/cancela diálogos.
Os invariantes valem para QUALQUER caminho:
  - nenhum erro de página/console; nenhuma resposta 5xx ou 401 inesperado
    (503 em /sync é esperado: pull TOTVS desligado no preview);
  - corpo da página nunca vazio e sem texto cru ("undefined", "NaN", "Traceback"...);
  - a navegação não sai da origem do app.
A mesma semente reproduz exatamente a mesma sequência.

    python tests/e2e_random_walk.py --profiles operador,destaque,1 --seeds 1,2,3 --steps 150
Saída em docs/auditoria_2026-10-01/e2e/random/: random_report.json, trilha de
ações por execução e um PNG por violação.
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PwError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "auditoria_2026-10-01" / "e2e" / "random"
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"
RAW = re.compile(r"undefined|\[object |\bNaN\b|\bnull\b|Traceback|Internal Server Error", re.I)
AVOID = re.compile(r"\b(sair|logout|encerrar sess)", re.I)
HOSTILE = ["", "0", "-1", "1", "2", "999999999", "OP-VISUAL-101", "OP-VISUAL-102", "OP-INEXISTENTE",
           "abc", "<script>alert(1)</script>", "x" * 300, "ação çãõ ü 🚀", "   ", "1.5", "1,5", "' OR 1=1 --"]
START = {"operador": "/operador", "destaque": "/operador", "1": "/"}
CONTROLS = ("button:visible, a[href]:visible, input:visible, select:visible, textarea:visible, "
            "[role=button]:visible, [role=tab]:visible, [role=checkbox]:visible, [role=menuitem]:visible")


def start_server(profile):
    env = {**os.environ, "GESTOR_VISUAL_AUTOLOGIN": profile}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.web_preview_api:app", "--port", str(PORT),
                             "--log-level", "warning"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/v1/system/health", timeout=1)
            return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("preview não subiu")


def describe(el):
    label = (el.get_attribute("aria-label") or el.inner_text() or el.get_attribute("placeholder")
             or el.get_attribute("name") or el.get_attribute("type") or "").strip().replace("\n", " ")
    return el.evaluate("e => e.tagName.toLowerCase()"), label[:60]


def act(page, rng, el, tag, label):
    kind = (el.get_attribute("type") or "").lower()
    if tag == "select":
        opts = el.evaluate("e => [...e.options].map(o => o.value)")
        value = rng.choice(opts) if opts else None
        if value is not None:
            el.select_option(value)
        return f"select {label} -> {value}"
    if tag == "textarea" or (tag == "input" and kind not in ("checkbox", "radio", "file", "button", "submit")):
        value = rng.choice(HOSTILE)
        el.fill(value[:300] if kind in ("number", "date", "time") and not value.lstrip("-").isdigit() else value)
        if rng.random() < 0.4:
            el.press("Enter")
        return f"fill {label} <- {value[:20]!r}"
    el.click(timeout=1500)
    return f"click {label}"


def walk(profile, seed, steps):
    rng = random.Random(f"{profile}:{seed}")
    trail, violations, seen = [], [], set()
    server = start_server(profile)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.set_default_timeout(1500)
            events = []
            page.on("pageerror", lambda e: events.append(("pageerror", str(e)[:200])))
            page.on("console", lambda m: events.append(("console", m.text[:200]))
                    if m.type == "error" and "Failed to load resource" not in m.text else None)
            page.on("response", lambda r: events.append(("http", f"{r.status} {r.request.method} {r.url}"[:200]))
                    if (r.status >= 500 or r.status == 401)
                    and not (r.status == 503 and r.url.split("?")[0].endswith("/sync")) else None)
            page.goto(BASE + START[profile], wait_until="networkidle")
            try:
                for step in range(1, steps + 1):
                    roll = rng.random()
                    try:
                        if roll < 0.06:
                            page.keyboard.press("Escape")
                            what = "Escape"
                        elif roll < 0.09:
                            page.go_back()
                            what = "voltar"
                        else:
                            cands = page.locator(CONTROLS)
                            total = cands.count()
                            if total == 0:
                                page.goto(BASE + START[profile], wait_until="networkidle")
                                what = "recarregar (sem controles)"
                            else:
                                el = cands.nth(rng.randrange(total))
                                tag, label = describe(el)
                                href = el.get_attribute("href") if tag == "a" else None
                                if (not el.is_enabled() or AVOID.search(label)
                                        or (href and not (href.startswith("/") or href.startswith(BASE)))):
                                    what = f"ignorado {tag} {label}"
                                else:
                                    what = act(page, rng, el, tag, label)
                                    seen.add((page.url.replace(BASE, "").split("?")[0], tag, label))
                    except PwError as exc:  # elemento sumiu/overlay: não é falha do produto
                        what = f"pulado ({str(exc).splitlines()[0][:60]})"
                    page.wait_for_timeout(120)
                    trail.append(f"{step:03d} {what}")
                    problems = list(events)
                    events.clear()
                    if page.url == "about:blank":  # voltou além do início: artefato do teste
                        page.goto(BASE + START[profile], wait_until="networkidle")
                    elif not page.url.startswith(BASE):
                        problems.append(("origin", page.url))
                        page.goto(BASE + START[profile], wait_until="networkidle")
                    body = page.inner_text("body")
                    if len(body.strip()) < 15:
                        problems.append(("blank", body[:40]))
                    if (m := RAW.search(body)):
                        problems.append(("raw", m.group(0)))
                    if problems:
                        shot = f"{profile}_seed{seed}_step{step:03d}.png"
                        page.screenshot(path=str(OUT / shot))
                        violations.append({"step": step, "after": what, "problems": problems, "shot": shot,
                                           "trail": trail[-8:]})
                        if len(violations) >= 15:
                            break
            except PwError as exc:  # crash do renderer/alvo fechado = violação real
                violations.append({"step": len(trail), "after": trail[-1] if trail else "",
                                   "problems": [("crash", str(exc).splitlines()[0][:120])], "shot": None,
                                   "trail": trail[-8:]})
            browser.close()
    finally:
        server.kill()
    return {"profile": profile, "seed": seed, "steps": len(trail), "distinct_controls": len(seen),
            "violations": violations, "trail": trail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="operador,destaque,1")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--steps", type=int, default=150)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    runs = [walk(p, int(s), args.steps) for p in args.profiles.split(",") for s in args.seeds.split(",")]
    (OUT / "random_report.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = 0
    for r in runs:
        bad += len(r["violations"])
        print(f"{r['profile']:9} seed={r['seed']} passos={r['steps']} controles distintos={r['distinct_controls']} "
              f"violações={len(r['violations'])}")
        for v in r["violations"][:5]:
            print("   passo", v["step"], v["after"], v["problems"], v["shot"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
