"""Monta o pacote da primeira instalação na VM.

Uso: python deploy/montar_pacote.py
Saída: dev_reports/deploy_vm/gestor-pecas-deploy.zip — contém o dump do REAL e
os segredos do .env: nunca versionar nem enviar por canal aberto.

Conteúdo: app/ (git archive do HEAD + web/dist recém-construído),
gestor_pecas.dump (REAL, lido via pg_dump), gestor.env.base (o .env deste
notebook sem as chaves que o instalar_vm.ps1 gera por máquina) e certs/
(autoassinado, reaproveitado entre montagens).
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "dev_reports" / "deploy_vm"
PACOTE = SAIDA / "gestor-pecas-deploy.zip"
PREFIXO = "gestor-pecas-deploy/"
CONTAINER = "gestor-de-pecas-postgres-1"

# Geradas por máquina no instalar_vm.ps1, ou só fazem sentido no notebook.
CHAVES_FORA_DO_SERVIDOR = {
    "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
    "DATABASE_URL", "TEST_DATABASE_URL", "GESTOR_EXPECTED_DATABASE", "GESTOR_TEST_ALLOWED_HOSTS",
    "GESTOR_WEB_ENV", "GESTOR_WEB_SESSION_SECRET", "GESTOR_DEVOBS_SESSION_SECRET",
    "GESTOR_WEB_COOKIE_SECURE", "GESTOR_WEB_SERVE_STATIC", "GESTOR_WEB_PUBLIC_HOST",
    "GESTOR_WEB_ALLOWED_HOSTS", "GESTOR_WEB_ALLOWED_ORIGINS",
    "GESTOR_DEV_OBSERVATORY_ENABLED", "GESTOR_DEVOBS_REAL_DATABASE_URL",
    "GESTOR_DEVOBS_LOGIN_USERNAME", "GESTOR_DEVOBS_LOGIN_PASSWORD",
    "GESTOR_OPERATOR_DRAWING_ROOTS",
    # Mesmo bot do notebook: ligar só depois de parar o notebook (LEIA-ME §2).
    "TELEGRAM_ENABLED", "GESTOR_TELEGRAM_BOT_POLLING_ENABLED", "GESTOR_TELEGRAM_DIGEST_ENABLED",
}


def rodar(*cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def env_base(texto: str) -> str:
    linhas = []
    for linha in texto.splitlines():
        ativa = "=" in linha and not linha.lstrip().startswith("#")
        chave = linha.split("=", 1)[0].strip()
        if ativa and (chave in CHAVES_FORA_DO_SERVIDOR or chave.startswith("GESTOR_SIMULATION_")):
            continue
        linhas.append(linha)
    return "\n".join(linhas) + "\n"


def certificado() -> Path:
    pasta = SAIDA / "certs"
    if not (pasta / "gestor-pecas.crt").exists():
        pasta.mkdir(parents=True, exist_ok=True)
        openssl = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"
        rodar(openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825",
              "-subj", "/CN=gestor-peca",
              "-addext", "subjectAltName=DNS:gestor-peca,DNS:gestor-pecas,DNS:localhost,IP:127.0.0.1",
              "-keyout", str(pasta / "gestor-pecas.key"), "-out", str(pasta / "gestor-pecas.crt"))
    return pasta


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=RAIZ,
                      capture_output=True, text=True, check=True).stdout.strip():
        sys.exit("Há alterações não commitadas: o pacote usa o HEAD. Commite antes de montar.")

    dump = SAIDA / "gestor_pecas.dump"
    with dump.open("wb") as destino:
        rodar("docker", "exec", CONTAINER, "pg_dump", "-Fc", "--no-owner", "--no-acl",
              "-U", "gestor_app", "gestor_pecas", stdout=destino)
    rodar(shutil.which("npm"), "run", "build", cwd=RAIZ / "web")
    certs = certificado()

    PACOTE.unlink(missing_ok=True)
    rodar("git", "archive", "--format=zip", f"--prefix={PREFIXO}app/", "-o", str(PACOTE), "HEAD", cwd=RAIZ)
    with zipfile.ZipFile(PACOTE, "a", zipfile.ZIP_DEFLATED) as zf:
        dist = RAIZ / "web" / "dist"
        for arquivo in sorted(p for p in dist.rglob("*") if p.is_file()):
            zf.write(arquivo, f"{PREFIXO}app/web/dist/{arquivo.relative_to(dist).as_posix()}")
        zf.write(dump, f"{PREFIXO}gestor_pecas.dump")
        zf.writestr(f"{PREFIXO}gestor.env.base", env_base((RAIZ / ".env").read_text(encoding="utf-8")))
        for arquivo in certs.iterdir():
            zf.write(arquivo, f"{PREFIXO}certs/{arquivo.name}")
    dump.unlink()  # cópia solta do REAL no notebook: o zip é a única que fica

    print(f"Pacote: {PACOTE} ({PACOTE.stat().st_size / 1e6:.1f} MB)")
    print("ATENÇÃO: contém o dump do REAL e segredos do .env. Não versionar.")


if __name__ == "__main__":
    main()
