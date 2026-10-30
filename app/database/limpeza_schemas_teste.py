"""Limpeza dos schemas temporários deixados pelos testes no banco de teste local.

Cada teste de integração cria um schema próprio e o apaga no ``tearDown``;
quando o ``setUp`` falha ou a execução é interrompida, o schema fica para trás.
Regra do notebook: o banco de teste guarda só o schema ``public``. Esta limpeza
roda no início e no fim de cada execução de testes (unittest ou pytest).

Duas execuções ao mesmo tempo não se atrapalham: cada uma segura um lock
consultivo compartilhado enquanto roda, e só limpa quem consegue o lock
exclusivo, isto é, quando não há outra execução em andamento.
"""

import atexit
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


_CHAVE_LOCK = 7_301_030
_HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1"}
_SOBRAS_SQL = r"""
    SELECT nspname FROM pg_namespace
    WHERE nspname NOT IN ('public', 'information_schema')
      AND nspname NOT LIKE 'pg\_%'
"""
_conexao = None


def _rodando_testes() -> bool:
    principal = getattr(sys.modules.get("__main__"), "__spec__", None)
    nome = getattr(principal, "name", "") or ""
    return nome.startswith(("unittest", "pytest")) or "pytest" in sys.modules


def _limpar_se_sozinho(conexao) -> None:
    if not conexao.execute("SELECT pg_try_advisory_lock(%s)", (_CHAVE_LOCK,)).fetchone()[0]:
        return
    try:
        for (nome,) in conexao.execute(_SOBRAS_SQL).fetchall():
            conexao.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(nome)))
    finally:
        conexao.execute("SELECT pg_advisory_unlock(%s)", (_CHAVE_LOCK,))


def _encerrar() -> None:
    try:
        _limpar_se_sozinho(_conexao)
    except psycopg.Error as exc:
        print(f"[limpeza de schemas] fim ignorado: {exc}", file=sys.stderr)
    finally:
        _conexao.close()


def iniciar(dsn: str) -> None:
    """Limpa as sobras e agenda nova limpeza no fim; uma vez por processo de teste."""

    global _conexao
    if _conexao is not None or not _rodando_testes():
        return
    if conninfo_to_dict(dsn).get("host") not in _HOSTS_LOCAIS:
        return
    try:
        _conexao = psycopg.connect(dsn, autocommit=True)
        _limpar_se_sozinho(_conexao)
        _conexao.execute("SELECT pg_advisory_lock_shared(%s)", (_CHAVE_LOCK,))
    except psycopg.Error as exc:
        print(f"[limpeza de schemas] início ignorado: {exc}", file=sys.stderr)
        if _conexao is not None:
            _conexao.close()
        _conexao = False  # não tenta de novo neste processo
        return
    atexit.register(_encerrar)
