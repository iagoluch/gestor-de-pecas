#!/usr/bin/env python3
"""Servidor local do Escritório Nemo (scripts/nemo-hub.html).

Uso: python scripts/nemo-hub.py [--open]   (porta 8765; NEMO_HUB_PORT muda)

Mostra as runs do scripts/nemo.sh ao vivo, despacha tarefas novas para os funcionários
(ultra | super | kimi), cancela, mostra o patch (git apply --check) e guarda o veredito.
Só escuta 127.0.0.1. Cada chamada da API exige o token que o servidor injeta na página,
Host e Origin conferidos (DNS rebinding / outra aba). Nada é executado por shell: os
argumentos vão em lista. Estado e logs ficam fora do repo (../nemo-*).
"""
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parents[1]
OUT = REPO.parent
RUNS, LOGS, PROMPTS, STATE = OUT / "nemo-runs.js", OUT / "nemo-logs", OUT / "nemo-prompts", OUT / "nemo-hub-state.json"
HTML = Path(__file__).with_name("nemo-hub.html")
HOST, PORT = "127.0.0.1", int(os.environ.get("NEMO_HUB_PORT", "8765"))
TOKEN = secrets.token_urlsafe(24)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
WORKERS = {"ultra": "ultra", "super": "super", "kimi": "kimi"}  # alias do nemo.sh; o id completo vem no evento
MAX_RUNNING, RUN_MAX, STAGGER = 3, 1260, 4  # simultâneas; segundos até uma run sem fim ser dada como perdida (timeout 900 + patch); pausa entre inícios
SLUG = re.compile(r"^[a-z0-9-]{1,48}$")
RUN_ID = re.compile(r"^[a-z0-9-]{1,64}$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
UPSTREAM = re.compile(r"\[(429|50[0-9])\]|overloaded|Upstream error|rate.?limit", re.I)
PUSH = re.compile(r"^NEMO_LIVE\.push\((\{.*\})\);\s*$")
HARD = re.compile(r"(^|/)\.env|(^|/)\.git/|(^|/)\.claude/|(^|/)\.opencode/|(^|/)opencode\.json$|secret|\.(pem|key|pfx|p12)$", re.I)
SOFT = re.compile(r"migration|alembic|schema|(^|/)auth|security|session|totvs|protheus|sigmanest|(^|/)oee|(^|/)ot[_/]|(^|/)\.ai/|(^|/)(CLAUDE|AGENTS)\.md$", re.I)

lock = threading.RLock()
procs: dict[str, subprocess.Popen] = {}
queued: set[str] = set()  # despachadas e ainda não iniciadas (largada escalonada)
_ev_cache = {"sig": None, "val": {}}
_ls_cache = {"t": 0.0, "val": set()}
_df_cache = {"t": 0.0, "val": set()}


def bash_exe() -> str:
    if os.environ.get("NEMO_BASH"):
        return os.environ["NEMO_BASH"]
    git = shutil.which("git")  # nunca o bash.exe do System32 (esse é o do WSL)
    if not git:
        sys.exit("git não encontrado no PATH")
    for root in Path(git).resolve().parents[:3]:
        p = root / "usr" / "bin" / "bash.exe"
        if p.exists():
            return str(p)
    sys.exit("Git Bash não encontrado; defina NEMO_BASH com o caminho do bash.exe do Git for Windows")


BASH = bash_exe()


def now() -> float:
    return time.time()


def read_events() -> dict:
    """Eventos do nemo.sh (uma linha JSON por evento) fundidos por id."""
    try:
        st = RUNS.stat()
    except OSError:
        return {}
    sig = (st.st_mtime_ns, st.st_size)
    if _ev_cache["sig"] == sig:
        return _ev_cache["val"]
    out: dict = {}
    for line in RUNS.read_text(encoding="utf-8", errors="replace").splitlines():
        m = PUSH.match(line)
        if not m:
            continue
        try:
            e = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(e.get("id"), str) and RUN_ID.match(e["id"]):
            out.setdefault(e["id"], {}).update(e)
    _ev_cache.update(sig=sig, val=out)
    return out


def load_state() -> dict:
    with lock:  # no Windows, replace() falha se alguém estiver lendo o arquivo: leitura e gravação nunca juntas
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
    d.setdefault("meta", {})
    d.setdefault("verdicts", {})
    return d


def save_state(d: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    with lock:
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        for _ in range(5):  # antivírus/indexador também seguram o arquivo por instantes
            try:
                return tmp.replace(STATE)
            except PermissionError:
                time.sleep(0.05)
        tmp.replace(STATE)


def worker_of(model: str):
    return next((k for k in WORKERS if k in (model or "")), None)


def log_tail(rid: str, n: int = 6000) -> str:
    p = LOGS / f"{rid}.log"
    try:
        with p.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - n))
            return ANSI.sub("", f.read().decode("utf-8", errors="replace")).replace("\r", "")
    except OSError:
        return ""


def last_lines(rid: str, k: int = 3) -> list:
    lines = [l.strip()[:160] for l in log_tail(rid, 3000).splitlines() if l.strip()]
    return lines[-k:]


def patch_path(slug):
    """Caminho do patch só se existir e não for vazio (patch vazio não é revisão pendente)."""
    p = OUT / f"nemo-{slug}.patch"
    return p if SLUG.match(str(slug)) and p.is_file() and p.stat().st_size > 0 else None


def runs_view() -> list:
    t, ev, st, out = now(), read_events(), None, []
    with lock:
        st = load_state()
        meta, verd = st["meta"], st["verdicts"]
        seen = set()
        for rid, e in ev.items():
            seen.add(rid)
            state = e.get("state", "running")
            if state == "running" and t - e.get("t0", t) > RUN_MAX and not (rid in procs and procs[rid].poll() is None):
                state = "erro"
            out.append({**e, "state": state, "secs": e.get("secs"), "worker": worker_of(e.get("model", "")),
                        "meta": meta.get(rid, {}), "verdict": verd.get(rid), "patch": patch_path(e.get("slug")) is not None})
        for rid, m in meta.items():  # despachada, nemo.sh ainda não escreveu o primeiro evento
            if rid in seen:
                continue
            p = procs.get(rid)
            dead = (p is not None and p.poll() is not None) or (p is None and rid not in queued and t - m["created"] > 60)
            out.append({"id": rid, "slug": rid, "model": m.get("alias", ""), "worker": m.get("alias"), "state": "erro" if dead else "iniciando",
                        "t0": m["created"], "secs": None, "meta": m, "verdict": verd.get(rid), "patch": False,
                        "note": err_tail(rid) if dead else ""})
    for r in out:
        if r["state"] in ("running", "iniciando"):
            r["last"] = last_lines(r["id"])
        elif r["state"] in ("erro", "vazio") and not r.get("note"):
            tail = " ".join(last_lines(r["id"], 6))
            if UPSTREAM.search(tail):
                r["note"] = "O provedor do modelo recusou a chamada (sobrecarga/503). Reenvie em alguns minutos ou troque de funcionário."
    out.sort(key=lambda r: r.get("t0", 0), reverse=True)
    return [r for r in out if r["worker"]][:80]


def err_tail(rid: str) -> str:
    try:
        return ANSI.sub("", (LOGS / f"{rid}.err").read_text(encoding="utf-8", errors="replace"))[-300:].strip()
    except OSError:
        return "o runner terminou antes de registrar a run"


def tracked_files() -> set:
    if now() - _ls_cache["t"] > 30:
        r = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, timeout=20)
        _ls_cache.update(t=now(), val=set(r.stdout.decode("utf-8", errors="replace").split("\0")) - {""})
    return _ls_cache["val"]


def differs() -> set:
    """Arquivos que diferem de origin/master: o funcionário só enxerga o que já foi enviado."""
    if now() - _df_cache["t"] > 10:
        r = subprocess.run(["git", "diff", "--name-only", "-z", "origin/master"], cwd=REPO, capture_output=True, timeout=20)
        _df_cache.update(t=now(), val=set(r.stdout.decode("utf-8", errors="replace").split("\0")) - {""})
    return _df_cache["val"]


def file_search(q: str) -> list:
    q = q.strip().lower()
    if len(q) < 2:
        return []
    hits = [f for f in tracked_files() if q in f.lower()]
    hits.sort(key=lambda f: (f.lower() != q, q not in f.rsplit("/", 1)[-1].lower(), len(f), f))
    ahead = differs()
    return [{"path": f, "flag": "hard" if HARD.search(f) else "soft" if SOFT.search(f) else "", "diff": f in ahead} for f in hits[:12]]


def slugify(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:20]


class Bad(Exception):
    def __init__(self, msg, code=400, **extra):
        super().__init__(msg)
        self.code, self.extra = code, extra


def dispatch(b: dict) -> dict:
    src = b.get("from")  # reenvio: mesmo prompt e arquivos de uma run anterior, outro funcionário
    if src is not None:
        meta = load_state()["meta"].get(src) if isinstance(src, str) and RUN_ID.match(src) else None
        pf = PROMPTS / f"{src}.md" if meta else None
        if not meta or not pf.exists():
            raise Bad("prompt da run de origem não encontrado", 404)
        b = {**b, "prompt": pf.read_text(encoding="utf-8"), "files": meta.get("files", []), "name": meta.get("title"), "preset": meta.get("preset")}
    workers = b.get("workers")
    if not isinstance(workers, list) or not workers or len(workers) > MAX_RUNNING or any(w not in WORKERS for w in workers) or len(set(workers)) != len(workers):
        raise Bad("escolha de 1 a 3 funcionários entre ultra, super e kimi")
    prompt, files = b.get("prompt"), b.get("files", [])
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise Bad("prompt vazio ou maior que 12000 caracteres")
    if not isinstance(files, list) or len(files) > 20 or any(not isinstance(f, str) for f in files):
        raise Bad("lista de arquivos inválida (máx. 20)")
    known = tracked_files()
    for f in files:
        if f.startswith("/") or ".." in f.split("/") or "\\" in f or f not in known:
            raise Bad(f"arquivo fora do repositório versionado: {f}")
        if HARD.search(f):
            raise Bad(f"arquivo que nenhum funcionário toca: {f}", 422)
    risky = [f for f in files if SOFT.search(f)]
    if risky and b.get("ack_risk") is not True:
        raise Bad("caminhos de área crítica (R2/R3): confirme que assume o risco", 422, need_ack=True, flagged=risky)
    base = slugify(str(b.get("name") or "")) or "tarefa"
    stamp = time.strftime("%m%d%H%M")
    with lock:
        busy = sum(1 for p in procs.values() if p.poll() is None) + len(queued)
        if busy + len(workers) > MAX_RUNNING:
            raise Bad(f"limite de {MAX_RUNNING} runs simultâneas (há {busy} rodando)", 409)
        PROMPTS.mkdir(exist_ok=True)
        LOGS.mkdir(exist_ok=True)
        st, made = load_state(), []
        for w in workers:
            slug = f"{base}-{w}-{stamp}"
            if slug in st["meta"] or (OUT / f"nemo-{slug}.patch").exists():
                slug = f"{slug}-{secrets.token_hex(2)}"
            pf = PROMPTS / f"{slug}.md"
            pf.write_text(prompt, encoding="utf-8")
            st["meta"][slug] = {"alias": w, "title": str(b.get("name") or base)[:60], "preset": str(b.get("preset") or "")[:24],
                                "files": files, "objective": prompt.strip().splitlines()[0][:200], "created": now()}
            made.append((slug, pf, w))
        save_state(st)
        queued.update(s for s, _, _ in made)  # só depois de gravar: se save_state falhar, nada fica preso na fila
    threading.Thread(target=start_all, args=(made,), daemon=True).start()
    return {"runs": [s for s, _, _ in made]}


_last_start = 0.0


def start_all(made) -> None:
    global _last_start
    for slug, pf, w in made:
        with lock:  # git fetch/worktree add no mesmo clone do WSL não gostam de ir juntos: STAGGER entre inícios, mesmo de lotes diferentes
            slot = _last_start = max(now(), _last_start + STAGGER)
        time.sleep(max(0.0, slot - now()))
        try:
            with (LOGS / f"{slug}.err").open("wb") as err:
                p = subprocess.Popen(  # -l: PATH do Git Bash (sed, tee); CHERE_INVOKING: não pular para ~
                    [BASH, "-lc", 'scripts/nemo.sh "$@"', "nemo", slug, pf.as_posix(), WORKERS[w]], cwd=REPO, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env={**os.environ, "NEMO_RUN_ID": slug, "MSYS_NO_PATHCONV": "1", "CHERE_INVOKING": "1"})
        except OSError as e:
            (LOGS / f"{slug}.err").write_text(f"não consegui iniciar o bash: {e}", encoding="utf-8")
            p = None
        with lock:
            queued.discard(slug)
            if p:
                procs[slug] = p


CANCEL_SH = r'''wt="$HOME/nemo-$1"; n=0
touch "$wt.cancel"  # run ainda preparando (fetch/worktree): o runner confere isto antes de chamar o opencode
for d in /proc/[0-9]*; do
  case "$(readlink "$d/cwd" 2>/dev/null)" in "$wt"|"$wt"/*) ;; *) continue ;; esac
  [ "$(cat "$d/comm" 2>/dev/null)" = bash ] && continue
  kill -TERM "${d#/proc/}" 2>/dev/null && n=$((n+1))
done
echo $n'''


def cancel(rid: str) -> dict:
    e = read_events().get(rid) or {}
    slug = e.get("slug") or rid
    if not SLUG.match(str(slug)) or not (rid in read_events() or rid in load_state()["meta"]):
        raise Bad("run desconhecida", 404)
    (LOGS / f"{rid}.cancel").touch()  # nemo.sh lê isto para marcar "cancelado" (o opencode sai com 1 ao receber TERM)
    r = subprocess.run(["wsl.exe", "-d", "Ubuntu-24.04", "-u", "nemo", "--", "bash", "-s", slug], input=CANCEL_SH.encode(), capture_output=True, timeout=30)  # bytes: text=True viraria \n em \r\n no Windows e o bash não executaria o script
    m = re.search(r"(\d+)\s*$", r.stdout.decode("utf-8", errors="replace"))
    return {"killed": int(m.group(1)) if m else 0}


def patch_info(rid: str) -> dict:
    e = read_events().get(rid) or {}
    slug = e.get("slug") or rid
    p = patch_path(slug)
    if p is None:
        raise Bad("sem patch para esta run", 404)

    def git(*a):
        r = subprocess.run(["git", "apply", *a, str(p)], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return r.returncode, (r.stdout + r.stderr).strip()

    diff = p.read_bytes()
    rc, chk = git("--check")
    return {"bytes": len(diff), "stat": git("--stat")[1], "check_ok": rc == 0, "check": chk or "aplica limpo na árvore atual",
            "diff": diff[:150000].decode("utf-8", errors="replace"), "truncated": len(diff) > 150000, "cmd": f"git apply ../nemo-{slug}.patch"}


class H(BaseHTTPRequestHandler):
    server_version = "NemoHub"

    def log_message(self, *a):
        pass

    def reply(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def guard(self, post: bool) -> bool:
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            self.reply(403, {"erro": "host"})
            return False
        if self.path.startswith("/api/"):
            origin = self.headers.get("Origin")
            if not hmac.compare_digest(self.headers.get("X-Nemo-Token", ""), TOKEN) or (origin and origin.removeprefix("http://") not in ALLOWED_HOSTS):
                self.reply(403, {"erro": "token ou origem inválidos; recarregue a página"})
                return False
            if post and not self.headers.get("Content-Type", "").startswith("application/json"):
                self.reply(415, {"erro": "use application/json"})
                return False
        return True

    def do_GET(self):
        if not self.guard(False):
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.reply(200, HTML.read_text(encoding="utf-8").replace("__NEMO_TOKEN__", TOKEN), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self.reply(200, {"now": now(), "max": MAX_RUNNING, "runs": runs_view(), "verdicts": load_state()["verdicts"]})
            if u.path == "/api/files":
                return self.reply(200, file_search(q.get("q", "")))
            rid = q.get("id", "")
            if not RUN_ID.match(rid):
                raise Bad("id inválido")
            if u.path == "/api/log":
                return self.reply(200, log_tail(rid, 14000), "text/plain; charset=utf-8")
            if u.path == "/api/patch":
                return self.reply(200, patch_info(rid))
            raise Bad("não existe", 404)
        except Bad as e:
            self.reply(e.code, {"erro": str(e), **e.extra})
        except Exception as e:  # noqa: BLE001 — a API não pode derrubar o servidor
            self.reply(500, {"erro": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self.guard(True):
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= 65536:
                raise Bad("corpo grande demais", 413)
            b = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(b, dict):
                raise Bad("JSON deve ser um objeto")
            path = urlparse(self.path).path
            if path == "/api/dispatch":
                return self.reply(200, dispatch(b))
            rid = b.get("id", "")
            if not isinstance(rid, str) or not RUN_ID.match(rid):
                raise Bad("id inválido")
            if path == "/api/cancel":
                return self.reply(200, cancel(rid))
            if path == "/api/verdict":
                v = b.get("verdict")
                if v not in ("ok", "parcial", "rej", None):
                    raise Bad("veredito inválido")
                with lock:
                    st = load_state()
                    if v is None:
                        st["verdicts"].pop(rid, None)
                    else:
                        st["verdicts"][rid] = v
                    save_state(st)
                return self.reply(200, {"ok": True})
            raise Bad("não existe", 404)
        except Bad as e:
            self.reply(e.code, {"erro": str(e), **e.extra})
        except ValueError:
            self.reply(400, {"erro": "JSON inválido"})
        except Exception as e:  # noqa: BLE001
            self.reply(500, {"erro": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), H)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"[nemo-hub] {url}   (Ctrl+C para sair; as runs em andamento continuam)")
    if "--open" in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
