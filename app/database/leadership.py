"""Liderança entre processos para laços com efeito externo duplicável (BK-07).

Com mais de um processo web, cada um sobe os mesmos laços de background. Envio
de relatório e bot do Telegram falam com o mundo externo: dois líderes mandam a
mesma mensagem duas vezes. O líder é quem segura um advisory lock de sessão
numa conexão própria, fora do pool — o pool do operador não perde vaga para um
laço que só espera. Se o processo líder morrer, o PostgreSQL solta o lock junto
com a conexão e outro processo assume no ciclo seguinte.
"""

import logging

import psycopg

LOGGER = logging.getLogger(__name__)

REPORT_SCHEDULER_LEADER_LOCK_ID = 874_210_308
TELEGRAM_BOT_LEADER_LOCK_ID = 874_210_309
TELEGRAM_DIGEST_LEADER_LOCK_ID = 874_210_310
INTERNAL_ALERT_DISPATCH_LEADER_LOCK_ID = 874_210_311


class LeaderLease:
    def __init__(self, lock_id):
        self.lock_id = int(lock_id)
        self._connection = None
        self._held = False

    def hold(self, database):
        """Confirma ou tenta assumir a liderança; chamar a cada ciclo."""

        config = getattr(getattr(database, "_pool", None), "config", None)
        if config is None:
            # Sem PostgreSQL (fakes e prévia local) só existe um processo.
            return True
        try:
            if self._connection is None or self._connection.closed:
                self._connection = psycopg.connect(config.dsn, autocommit=True, connect_timeout=5)
                self._held = False
            if self._held:
                # Prova que a sessão, e o lock com ela, segue viva.
                self._connection.execute("SELECT 1")
            else:
                self._held = bool(
                    self._connection.execute(
                        "SELECT pg_try_advisory_lock(%s)", (self.lock_id,)
                    ).fetchone()[0]
                )
            return self._held
        except psycopg.Error:
            LOGGER.warning("Liderança %s indisponível; ciclo pulado.", self.lock_id, exc_info=True)
            self.release()
            return False

    def release(self):
        connection, self._connection, self._held = self._connection, None, False
        if connection is not None:
            try:
                connection.close()
            except psycopg.Error:
                pass
