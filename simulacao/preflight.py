"""Pre-flight da simulação (seção 1).

Se qualquer verificação **crítica** falhar, a simulação não começa. O critério
não é "provavelmente está certo": cada item é comprovado contra o ambiente real
naquele instante.

O pre-flight é dividido em dois momentos porque as evidências são diferentes:
antes da API sobe-se a prova de que o alvo é o TESTE e que o REAL está fora de
alcance; depois da API, a prova de que a aplicação que está no ar é aquela.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from psycopg.conninfo import conninfo_to_dict

from simulacao.config import EXPECTED_DATABASE, FORBIDDEN_DATABASE, PROJECT_ROOT, SimulationConfig


@dataclass
class Checagem:
    nome: str
    ok: bool
    detalhe: str
    critico: bool = True
    dados: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "nome": self.nome,
            "ok": self.ok,
            "critico": self.critico,
            "detalhe": self.detalhe,
            "dados": self.dados,
        }


@dataclass
class ResultadoPreflight:
    checagens: list[Checagem] = field(default_factory=list)

    def adicionar(self, checagem: Checagem) -> Checagem:
        self.checagens.append(checagem)
        return checagem

    @property
    def aprovado(self) -> bool:
        return all(item.ok for item in self.checagens if item.critico)

    @property
    def falhas_criticas(self) -> list[Checagem]:
        return [item for item in self.checagens if item.critico and not item.ok]

    def as_dict(self) -> dict:
        return {
            "aprovado": self.aprovado,
            "verificado_em": datetime.now().isoformat(),
            "checagens": [item.as_dict() for item in self.checagens],
        }


def preflight_local(
    config: SimulationConfig, env_file: dict[str, str], ambiente_api: dict[str, str]
) -> ResultadoPreflight:
    resultado = ResultadoPreflight()

    dsn_teste = (env_file.get("TEST_DATABASE_URL") or "").strip()
    alvo = conninfo_to_dict(dsn_teste) if dsn_teste else {}
    nome_banco = str(alvo.get("dbname") or "")
    resultado.adicionar(
        Checagem(
            "banco_alvo_e_o_teste",
            nome_banco.casefold() == EXPECTED_DATABASE,
            f"TEST_DATABASE_URL aponta para '{nome_banco or '<vazio>'}' "
            f"em {alvo.get('host')}:{alvo.get('port')}; esperado '{EXPECTED_DATABASE}'.",
            dados={"host": alvo.get("host"), "port": alvo.get("port"), "dbname": nome_banco},
        )
    )
    resultado.adicionar(
        Checagem(
            "banco_real_fora_do_alvo",
            nome_banco.casefold() != FORBIDDEN_DATABASE,
            f"O banco REAL '{FORBIDDEN_DATABASE}' não é o alvo da execução.",
        )
    )
    resultado.adicionar(
        Checagem(
            "dsn_produtivo_removido_da_api",
            (ambiente_api.get("DATABASE_URL") or "") == "",
            "DATABASE_URL entra vazia no processo da API: o DSN produtivo não existe dentro dela.",
        )
    )
    resultado.adicionar(
        Checagem(
            "banco_esperado_fixado",
            (ambiente_api.get("GESTOR_EXPECTED_DATABASE") or "").casefold() == EXPECTED_DATABASE,
            f"GESTOR_EXPECTED_DATABASE = {ambiente_api.get('GESTOR_EXPECTED_DATABASE')}.",
        )
    )
    resultado.adicionar(
        Checagem(
            "worker_outbound_desligado",
            str(ambiente_api.get("GESTOR_TOTVS_OUTBOX_WORKER_ENABLED", "0")).strip()
            in {"0", "false", "no", ""},
            "O worker da outbox TOTVS entra desligado: nenhuma produção é publicada no WSPCP.",
        )
    )
    resultado.adicionar(
        Checagem(
            "relogio_virtual_configurado",
            bool(ambiente_api.get("GESTOR_SIMULATION_MODE") == "1")
            and float(ambiente_api.get("GESTOR_SIMULATION_TIME_SCALE") or 0) > 0,
            f"Modo simulação ligado com escala {ambiente_api.get('GESTOR_SIMULATION_TIME_SCALE')}× "
            f"a partir de {ambiente_api.get('GESTOR_SIMULATION_NOW')}.",
            dados={
                "escala": ambiente_api.get("GESTOR_SIMULATION_TIME_SCALE"),
                "inicio_virtual": ambiente_api.get("GESTOR_SIMULATION_NOW"),
                "duracao_real_s": config.duration_seconds,
                "duracao_virtual_s": config.factory_seconds,
            },
        )
    )
    indice = PROJECT_ROOT / "web" / "dist" / "index.html"
    resultado.adicionar(
        Checagem(
            "frontend_teste_disponivel",
            indice.is_file(),
            f"Build do frontend presente em {indice}." if indice.is_file()
            else "web/dist/index.html não existe: o frontend TESTE não seria servido.",
        )
    )
    return resultado


def preflight_banco(observer, resultado: ResultadoPreflight) -> ResultadoPreflight:
    try:
        identidade = observer.consultar(
            "SELECT current_database() AS banco, current_user AS usuario, version() AS versao"
        )[0]
    except Exception as exc:
        resultado.adicionar(
            Checagem("conexao_observabilidade", False, f"Falha ao conectar: {type(exc).__name__}: {exc}")
        )
        return resultado
    resultado.adicionar(
        Checagem(
            "conexao_observabilidade",
            str(identidade["banco"]).casefold() == EXPECTED_DATABASE,
            f"Observador conectado em {identidade['banco']} "
            f"({str(identidade['versao']).split(',')[0]}).",
            dados={"banco": identidade["banco"], "usuario": identidade["usuario"]},
        )
    )
    try:
        schema = observer.escalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    except Exception as exc:
        schema = None
    from app.database.schema import SCHEMA_VERSION

    resultado.adicionar(
        Checagem(
            "schema_compativel",
            schema is not None and int(schema) == int(SCHEMA_VERSION),
            f"Schema efetivo {schema}; aplicação espera {SCHEMA_VERSION}.",
            dados={"efetivo": schema, "aplicacao": SCHEMA_VERSION},
        )
    )
    try:
        pg_stat = observer.consultar(
            "SELECT COUNT(*) AS n FROM pg_stat_activity WHERE datname = current_database()"
        )
        recursos = observer.escalar(
            "SELECT COUNT(*) FROM catalogo_recursos_pcfactory WHERE habilitado IS TRUE"
        )
        motivos = observer.escalar(
            "SELECT COUNT(*) FROM catalogo_status_recursos WHERE habilitado IS TRUE"
        )
        turnos = observer.escalar(
            "SELECT COUNT(*) FROM turnos_produtivos WHERE ativo IS TRUE"
        )
    except Exception as exc:
        resultado.adicionar(
            Checagem("observabilidade_postgres", False, f"pg_stat indisponível: {exc}")
        )
        return resultado
    resultado.adicionar(
        Checagem(
            "observabilidade_postgres",
            bool(pg_stat),
            f"pg_stat_activity acessível ({pg_stat[0]['n']} sessões no banco).",
        )
    )
    resultado.adicionar(
        Checagem(
            "cadastro_minimo",
            int(recursos or 0) > 0 and int(motivos or 0) > 0 and int(turnos or 0) > 0,
            f"{recursos} recursos habilitados, {motivos} status de recurso, {turnos} turnos ativos.",
            dados={"recursos": recursos, "motivos": motivos, "turnos": turnos},
        )
    )
    return resultado


async def preflight_api(sessao, config: SimulationConfig, resultado: ResultadoPreflight):
    saude = await sessao.call("GET", "/system/health", action="preflight_health", registrar=False)
    resultado.adicionar(
        Checagem(
            "api_disponivel",
            saude.ok and isinstance(saude.data, dict) and saude.data.get("status") == "ok",
            f"/system/health respondeu {saude.status} em {saude.latency_ms:.0f} ms "
            f"({(saude.data or {}).get('status') if isinstance(saude.data, dict) else '-'}).",
            dados=saude.data if isinstance(saude.data, dict) else {},
        )
    )
    capacidades = await sessao.call(
        "GET", "/system/capabilities", action="preflight_capabilities", registrar=False
    )
    dados = capacidades.data if isinstance(capacidades.data, dict) else {}
    simulacao = dados.get("simulation") or {}
    corporativo = dados.get("corporate_integration") or {}
    resultado.adicionar(
        Checagem(
            "fonte_de_dados_teste",
            str(dados.get("active_data_source") or "") == "postgresql_test_only",
            f"A API declara fonte ativa '{dados.get('active_data_source')}'.",
        )
    )
    escala_api = float(simulacao.get("time_scale") or 0)
    resultado.adicionar(
        Checagem(
            "relogio_virtual_em_operacao",
            bool(simulacao.get("enabled"))
            and bool(simulacao.get("running"))
            and abs(escala_api - config.time_scale) < 0.01,
            f"Relógio virtual ativo em {simulacao.get('reference_time')} "
            f"a {escala_api}× (esperado {config.time_scale:.4f}×).",
            dados=simulacao,
        )
    )
    resultado.adicionar(
        Checagem(
            "outbound_produtivo_bloqueado",
            not bool(corporativo.get("execution_write_enabled")),
            "Escrita de execução no ERP desabilitada: "
            f"execution_write_enabled={corporativo.get('execution_write_enabled')}; "
            f"motivo: {corporativo.get('reason')}.",
            dados=corporativo,
        )
    )
    frontend = await sessao.call(
        "GET", "/", action="preflight_frontend", registrar=False, raw=True
    )
    resultado.adicionar(
        Checagem(
            "frontend_servido_pela_api",
            frontend.status == 200 and isinstance(frontend.data, str)
            and "<div id=\"root\"" in frontend.data,
            f"A raiz devolveu {frontend.status} com o HTML do SPA TESTE.",
            critico=False,
        )
    )
    return resultado


#: Colunas de tempo de fábrica que o Gestor grava. A janela virtual de uma nova
#: execução precisa começar depois de **todas** elas: o TESTE é reaproveitado
#: entre execuções e o relógio virtual, se recomeçasse antes, escreveria eventos
#: com data anterior à do evento já gravado no mesmo apontamento — uma inversão
#: que não vem do Gestor, vem do calendário da simulação.
_COLUNAS_DE_TEMPO_DA_FABRICA: tuple[tuple[str, str], ...] = (
    ("eventos_apontamento_operador", "data_hora"),
    ("apontamentos_operacionais", "data_entrada"),
    ("apontamentos_operacionais", "data_inicio"),
    ("apontamentos_operacionais", "data_fim"),
    ("participacoes_operador", "data_inicio"),
    ("participacoes_operador", "data_fim"),
    ("eventos_estado_recurso", "data_inicio"),
    ("eventos_estado_recurso", "data_fim"),
    ("eventos_quantidade_producao", "data_hora"),
    ("eventos_destaque_tarefa", "data_hora"),
    ("historico", "data_hora"),
)

#: Folga entre o histórico existente e o novo início virtual.
_DESLOCAMENTO_SEMANAS = 7


def ultimo_instante_de_fabrica(observer) -> tuple[datetime | None, str | None]:
    """Maior instante de fábrica já persistido no TESTE, e de onde ele veio."""

    maior: datetime | None = None
    origem: str | None = None
    for tabela, coluna in _COLUNAS_DE_TEMPO_DA_FABRICA:
        try:
            valor = observer.escalar(f"SELECT MAX({coluna}) FROM {tabela}")
        except Exception:
            continue
        if isinstance(valor, datetime) and (maior is None or valor > maior):
            maior, origem = valor, f"{tabela}.{coluna}"
    return maior, origem


def resolver_janela_virtual(
    observer, config: SimulationConfig
) -> tuple[SimulationConfig, Checagem]:
    """Garante que o relógio virtual nunca comece atrás do histórico do TESTE.

    O banco de TESTE é reaproveitado entre execuções e guarda o WIP da anterior.
    Se a nova execução recomeçasse o relógio em um instante já ultrapassado, o
    primeiro apontamento retomado gravaria um evento **anterior** ao último
    evento do mesmo apontamento — uma inversão real no banco, mas provocada pelo
    simulador, não pelo Gestor.

    O deslocamento é feito em semanas inteiras de propósito: ``turnos_produtivos``
    é indexado por ``dia_semana``, então mover a janela 7 dias preserva
    integralmente o calendário (turno oficial, HE e fora de turno) que a seção 16
    manda exercitar.
    """

    maior, origem = ultimo_instante_de_fabrica(observer)
    inicio = config.virtual_start
    if maior is None or inicio > maior:
        return config, Checagem(
            "janela_virtual_a_frente_do_historico",
            True,
            (
                f"Janela virtual começa em {inicio:%d/%m/%Y %H:%M}; "
                + (
                    f"o histórico do TESTE termina em {maior:%d/%m/%Y %H:%M} ({origem})."
                    if maior is not None
                    else "o TESTE não tem histórico de fábrica."
                )
            ),
            dados={
                "inicio_virtual": inicio.isoformat(),
                "ultimo_instante_no_teste": maior.isoformat() if maior else None,
                "origem": origem,
                "semanas_deslocadas": 0,
            },
        )

    semanas = 0
    novo_inicio = inicio
    while novo_inicio <= maior:
        novo_inicio += timedelta(days=_DESLOCAMENTO_SEMANAS)
        semanas += 1
    ajustada = config.com_inicio_virtual(novo_inicio)
    return ajustada, Checagem(
        "janela_virtual_a_frente_do_historico",
        True,
        (
            f"O TESTE já tem fábrica registrada até {maior:%d/%m/%Y %H:%M} ({origem}), "
            f"à frente do início pedido ({inicio:%d/%m/%Y %H:%M}). A janela foi deslocada "
            f"{semanas} semana(s) — mesmo dia da semana, mesmo calendário de turnos — "
            f"para {novo_inicio:%d/%m/%Y %H:%M} → {ajustada.virtual_end:%d/%m/%Y %H:%M}."
        ),
        dados={
            "inicio_pedido": inicio.isoformat(),
            "inicio_virtual": novo_inicio.isoformat(),
            "fim_virtual": ajustada.virtual_end.isoformat(),
            "ultimo_instante_no_teste": maior.isoformat(),
            "origem": origem,
            "semanas_deslocadas": semanas,
            "dia_da_semana_preservado": novo_inicio.weekday() == inicio.weekday(),
        },
    )


def preflight_turno(observer, config: SimulationConfig, resultado: ResultadoPreflight):
    """A janela virtual precisa existir no calendário produtivo (seção 16)."""

    dia = config.virtual_start.weekday()
    turnos = observer.consultar(
        """
        SELECT nome, hora_inicio, hora_fim, minutos_intervalo
        FROM turnos_produtivos
        WHERE ativo IS TRUE AND dia_semana = %s
        ORDER BY hora_inicio
        """,
        (dia,),
    )
    resultado.adicionar(
        Checagem(
            "calendario_da_janela_virtual",
            bool(turnos),
            (
                "Turnos do dia virtual: "
                + "; ".join(f"{t['nome']} {t['hora_inicio']}–{t['hora_fim']}" for t in turnos)
            )
            if turnos
            else f"Nenhum turno ativo para dia_semana={dia}; a janela virtual ficaria fora de turno inteira.",
            dados={"dia_semana": dia, "turnos": [dict(t) for t in turnos]},
        )
    )
    return resultado


def registrar_baseline(observer) -> dict[str, Any]:
    """Fotografia do TESTE antes do primeiro evento (WIP herdado etc.)."""

    def consulta(sql: str) -> list[dict]:
        try:
            return observer.consultar(sql)
        except Exception:
            return []

    return {
        "coletado_em": datetime.now().isoformat(),
        "apontamentos_abertos": consulta(
            """
            SELECT id, op, tipo_setor, maquina, status, numero_operacao,
                   data_entrada, data_inicio, quantidade, quantidade_boa, quantidade_refugo
            FROM apontamentos_operacionais WHERE status <> 'Finalizado' ORDER BY id
            """
        ),
        "participacoes_abertas": consulta(
            "SELECT id, cracha, op, recurso, data_inicio FROM participacoes_operador "
            "WHERE data_fim IS NULL ORDER BY id"
        ),
        "contagens": (
            consulta(
                """
                SELECT
                  (SELECT COUNT(*) FROM apontamentos_operacionais) AS apontamentos,
                  (SELECT COUNT(*) FROM apontamentos_corte) AS apontamentos_corte,
                  (SELECT COUNT(*) FROM eventos_apontamento_operador) AS eventos,
                  (SELECT COUNT(*) FROM eventos_quantidade_producao) AS eventos_quantidade,
                  (SELECT COUNT(*) FROM participacoes_operador) AS participacoes,
                  (SELECT COUNT(*) FROM qualidade_primeira_peca) AS primeiras_pecas,
                  (SELECT COUNT(*) FROM alertas_internos) AS alertas,
                  (SELECT COUNT(*) FROM catalogo_pcp_ops) AS ops,
                  (SELECT COUNT(*) FROM catalogo_operacoes_op WHERE ativo) AS operacoes_ativas,
                  (SELECT COUNT(*) FROM totvs_outbox) AS outbox
                """
            )
            or [{}]
        )[0],
    }
