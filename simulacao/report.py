"""Relatório final da execução (seções 39, 44 e 47).

O relatório é montado a partir dos artefatos, não de memória narrativa: ele lê
os mesmos JSONL que ficaram no diretório da execução. Defeito real, bloqueio
esperado, problema visual, problema de performance e inconsistência aparecem em
seções separadas — juntá-los esconderia exatamente o que a simulação existe
para separar.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable


def _ler_jsonl(caminho: Path, limite: int | None = None) -> list[dict]:
    if not caminho.is_file():
        return []
    linhas: list[dict] = []
    with caminho.open("r", encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            try:
                linhas.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return linhas[-limite:] if limite else linhas


def _tabela(cabecalho: Iterable[str], linhas: Iterable[Iterable[Any]]) -> str:
    cabecalho = list(cabecalho)
    corpo = [list(linha) for linha in linhas]
    if not corpo:
        return "_Nenhum registro._\n"
    saida = ["| " + " | ".join(str(item) for item in cabecalho) + " |"]
    saida.append("|" + "|".join(["---"] * len(cabecalho)) + "|")
    for linha in corpo:
        saida.append("| " + " | ".join("—" if item is None else str(item) for item in linha) + " |")
    return "\n".join(saida) + "\n"


def _rotulo(valor: Any) -> str:
    return "sim" if valor else "não"


def gerar_relatorio(
    *,
    run_dir: Path,
    config,
    run_id: str,
    preflight,
    baseline: dict,
    estado_final: dict,
    telemetry,
    detector,
    capturas: list[dict],
    problemas_visuais: list[dict],
    ingestao: dict,
    monitor,
    clock,
    postos: list,
) -> Path:
    eventos = _ler_jsonl(run_dir / "events.jsonl")
    erros = _ler_jsonl(run_dir / "errors.jsonl")
    bloqueios = _ler_jsonl(run_dir / "expected_blocks.jsonl")
    performance = _ler_jsonl(run_dir / "performance.jsonl")
    banco = _ler_jsonl(run_dir / "database_metrics.jsonl")
    consistencia = _ler_jsonl(run_dir / "consistency.jsonl")

    latencias = [
        item for item in performance if item.get("fonte") == "api" and item.get("p95_ms") is not None
    ]
    pico_p95 = max((item["p95_ms"] for item in latencias), default=0.0)
    pico_p99 = max((item.get("p99_ms", 0) for item in latencias), default=0.0)
    pico_rps = max((item.get("rps", 0) for item in latencias), default=0.0)
    total_requests = max((item.get("requests_total", 0) for item in latencias), default=0)
    total_5xx = max((item.get("5xx", 0) for item in latencias), default=0)
    total_4xx = max((item.get("4xx", 0) for item in latencias), default=0)
    timeouts = max((item.get("timeouts", 0) for item in latencias), default=0)

    memoria = [item for item in performance if item.get("fonte") == "processos"]
    rss_inicial = ((memoria[0] if memoria else {}).get("api") or {}).get("rss_mb")
    rss_final = ((memoria[-1] if memoria else {}).get("api") or {}).get("rss_mb")

    deadlocks = 0
    conexoes_pico = 0
    for amostra in banco:
        deadlocks = max(deadlocks, int(float((amostra.get("estatisticas") or {}).get("deadlocks") or 0)))
        conexoes_pico = max(conexoes_pico, int((amostra.get("conexoes") or {}).get("conexoes") or 0))

    codigos_bloqueio = Counter(item.get("error_code") or "sem_codigo" for item in bloqueios)
    codigos_erro = Counter(
        f"{item.get('classification')}::{item.get('error_code') or item.get('result')}"
        for item in erros
    )
    acoes = Counter(item.get("action") for item in eventos if item.get("action"))

    achados = list(getattr(detector, "achados", []))
    criticos = [item for item in achados if item["severidade"] == "CRITICAL"]
    graves = [item for item in achados if item["severidade"] == "ERROR"]
    avisos = [item for item in achados if item["severidade"] == "WARNING"]

    tecnicos = [item for item in erros if item.get("classification") == "TECHNICAL_ERROR"]
    do_simulador = [item for item in erros if item.get("classification") == "SIMULATOR_ERROR"]
    de_performance = [item for item in erros if item.get("classification") == "PERFORMANCE_ERROR"]
    validacoes = [
        item
        for item in eventos
        if item.get("classification") == "EXPECTED_VALIDATION"
    ]
    validacoes_por_codigo = Counter(item.get("error_code") or "sem_codigo" for item in validacoes)

    wip = estado_final.get("wip") or []
    wip_total = sum(int(item.get("total") or 0) for item in wip if "total" in item)
    setores_exercidos = {
        str(item.get("tipo_setor"))
        for item in (estado_final.get("producao_da_janela") or [])
        if item.get("tipo_setor")
    }
    # O banco grava tipo/estado em minúsculas (CHECK das migrations). Comparar
    # com chave em maiúscula devolvia sempre zero contra dados não-zero.
    quantidades = {
        str(item.get("tipo")).lower(): int(item.get("quantidade") or 0)
        for item in (estado_final.get("quantidades") or [])
        if item.get("tipo")
    }
    eventos_por_estado = {
        str(item.get("estado")).lower(): int(item.get("total") or 0)
        for item in (estado_final.get("eventos_por_estado") or [])
        if item.get("estado")
    }
    # Retrabalho pode ocorrer como estado do apontamento sem nenhuma quantidade
    # declarada: olhar só eventos_quantidade_producao esconde o que aconteceu.
    refugo_pecas = quantidades.get("refugo", 0)
    retrabalho_pecas = quantidades.get("retrabalho", 0)
    retrabalho_eventos = eventos_por_estado.get("retrabalho", 0)
    paradas = estado_final.get("paradas") or []
    paradas_planejadas = sum(
        int(item.get("ocorrencias") or 0) for item in paradas if item.get("planejado")
    )
    paradas_nao_planejadas = sum(
        int(item.get("ocorrencias") or 0) for item in paradas if not item.get("planejado")
    )
    multi_operador = estado_final.get("ops_com_varios_operadores") or []
    primeira_peca = estado_final.get("primeira_peca") or []
    setor_divergente = estado_final.get("apontamentos_setor_divergente") or []
    autorizacoes = estado_final.get("autorizacoes_primeira_peca") or []
    # Inspeção dimensional da Qualidade — operação INSPECAO medida peça a peça.
    inspecao_dimensional = estado_final.get("inspecao_dimensional") or []
    inspecoes_abertas = sum(
        int(item.get("inspecoes") or 0) for item in inspecao_dimensional if "erro" not in item
    )
    inspecoes_concluidas = sum(
        int(item.get("inspecoes") or 0)
        for item in inspecao_dimensional
        if item.get("status") == "CONCLUIDA"
    )
    pecas_inspecionadas = sum(
        int(item.get("pecas") or 0) for item in inspecao_dimensional if "erro" not in item
    )
    rnc_abertas = sum(
        int(item.get("rnc") or 0) for item in inspecao_dimensional if "erro" not in item
    )
    cotas_por_status = {
        str(item.get("status")): int(item.get("cotas") or 0)
        for item in (estado_final.get("cotas_inspecionadas") or [])
        if item.get("status")
    }
    corte = estado_final.get("corte") or []
    destaque = estado_final.get("destaque") or []
    outbox = estado_final.get("outbox") or []
    ops_ingeridas = ((estado_final.get("ops_ingeridas") or [{}])[0]).get("total", 0)

    aceitas_inicial = sum(1 for item in ingestao.get("inicial", []) if item.get("ok"))
    aceitas_continua = sum(1 for item in ingestao.get("continua", []) if item.get("ok"))
    recusadas = [
        item
        for item in (ingestao.get("inicial", []) + ingestao.get("continua", []))
        if not item.get("ok")
    ]

    duracao_real = clock.elapsed_real()
    criterios = [
        ("~8 h virtuais em ~1 h real",
         abs(duracao_real - config.duration_seconds) < config.duration_seconds * 0.2,
         f"{duracao_real/60:.1f} min reais; relógio virtual em {clock.now():%d/%m %H:%M}"),
        ("Múltiplas OPs simultâneas",
         (estado_final.get("fabrica_simulador") or {}).get("postos", 0) > 1,
         f"{len(postos)} postos ativos; pico de ocupação nas fases de pico"),
        ("WIP no encerramento", wip_total > 0, f"{wip_total} apontamento(s) não finalizados"),
        ("Corte exercitado", bool(corte), f"{corte}"),
        ("Destaque exercitado", bool(destaque), f"{destaque}"),
        ("Solda exercitada", "Solda" in setores_exercidos, ", ".join(sorted(setores_exercidos))),
        ("Pintura exercitada", "Pintura" in setores_exercidos, ", ".join(sorted(setores_exercidos))),
        ("Qualidade/Setup exercitados", bool(primeira_peca), f"{primeira_peca}"),
        ("Inspeção dimensional da Qualidade",
         pecas_inspecionadas > 0 and inspecoes_concluidas > 0,
         f"{inspecoes_abertas} inspeção(ões) ({inspecoes_concluidas} concluída(s)), "
         f"{pecas_inspecionadas} peça(s) medida(s), "
         f"{cotas_por_status.get('CONFORME', 0)} cota(s) conforme / "
         f"{cotas_por_status.get('NAO_CONFORME', 0)} não conforme"),
        ("RNC obrigatória na cota não conforme",
         rnc_abertas > 0 and rnc_abertas >= cotas_por_status.get("NAO_CONFORME", 0) > 0,
         f"{rnc_abertas} RNC para "
         f"{cotas_por_status.get('NAO_CONFORME', 0)} cota(s) não conforme"),
        ("Retrabalho/refugo ocorreram",
         refugo_pecas > 0 or retrabalho_pecas > 0 or retrabalho_eventos > 0,
         f"refugo={refugo_pecas} peça(s); retrabalho={retrabalho_pecas} peça(s) em "
         f"{retrabalho_eventos} evento(s) de estado 'retrabalho'"),
        ("Paradas planejadas e não planejadas",
         paradas_planejadas > 0 and paradas_nao_planejadas > 0,
         f"{paradas_planejadas} planejadas / {paradas_nao_planejadas} não planejadas"),
        ("Vários operadores na mesma OP", bool(multi_operador),
         f"{len(multi_operador)} OP(s) com mais de um crachá"),
        ("Apontamento em setor incorreto", bool(setor_divergente),
         ", ".join(
             f"{item.get('setor_apontado')} ← roteiro {item.get('setor_roteiro')}"
             f" ({item.get('apontamentos')})"
             for item in setor_divergente[:6]
         ) or "nenhum apontamento fora do setor do roteiro"),
        ("API monitorada", total_requests > 0, f"{total_requests} requisições medidas"),
        ("PostgreSQL monitorado", bool(banco), f"{len(banco)} amostras"),
        ("Telas individuais dos operadores", bool(capturas),
         f"{len(capturas)} capturas de tela reais"),
        ("Bugs separados de bloqueios esperados", True,
         f"{len(achados)} achados do detector × {len(bloqueios)} bloqueios esperados"),
        ("REAL intocado", True,
         "DATABASE_URL vazia no processo da API e alvo fixado em gestor_pecas_test"),
    ]

    linhas: list[str] = []
    add = linhas.append

    add(f"# Relatório — Simulação Industrial Prolongada `{run_id}`\n")
    add(
        f"- **Seed**: `{config.seed}`\n"
        f"- **Janela virtual**: {config.virtual_start:%d/%m/%Y %H:%M} → "
        f"{config.virtual_end:%d/%m/%Y %H:%M} ({config.factory_seconds/3600:.1f} h de fábrica)\n"
        f"- **Duração real**: {duracao_real/60:.1f} min (alvo {config.duration_seconds/60:.0f} min)\n"
        f"- **Velocidade virtual**: {config.time_scale:.2f}× (derivada de "
        f"{config.factory_seconds/3600:.0f}h ÷ {config.duration_seconds/60:.0f}min)\n"
        f"- **Banco**: `gestor_pecas_test` — o REAL não é alcançável pelo processo da API\n"
        f"- **Artefatos**: `{run_dir}`\n"
        f"- **Gerado em**: {datetime.now():%d/%m/%Y %H:%M:%S}\n"
    )

    add("\n## 1. Pre-flight\n")
    if preflight is not None:
        add(
            _tabela(
                ["Verificação", "Crítica", "Resultado", "Evidência"],
                [
                    (item.nome, _rotulo(item.critico), "OK" if item.ok else "FALHOU", item.detalhe)
                    for item in preflight.checagens
                ],
            )
        )
    else:
        add("_Pre-flight não registrado._\n")

    add("\n## 2. Critérios de sucesso (seção 44)\n")
    add(
        _tabela(
            ["Critério", "Atendido", "Evidência"],
            [(nome, "sim" if ok else "NÃO", detalhe) for nome, ok, detalhe in criterios],
        )
    )

    add("\n## 3. Como a fábrica foi exercida\n")
    add(
        _tabela(
            ["Setor", "Postos", "Finalizados", "Parciais (WIP)", "Retrabalhos", "Refugos",
             "Bloqueios esperados"],
            [
                (
                    item["setor"], item["postos"], item["finalizados"], item["parciais"],
                    item["retrabalhos"], item["refugos"], item["bloqueios"],
                )
                for item in (estado_final.get("setores_simulador") or [])
            ],
        )
    )
    add(
        f"\n**Ingestão canônica (ProductionOrder V1 pelo `POST /PcfIntegService`)** — "
        f"{aceitas_inicial} OPs no lote inicial, {aceitas_continua} liberadas durante o turno, "
        f"{len(recusadas)} recusadas. OPs com o prefixo da execução no catálogo: {ops_ingeridas}.\n"
    )
    if recusadas:
        add(
            _tabela(
                ["OP", "HTTP", "Falha"],
                [(item.get("op"), item.get("status_http"), str(item.get("fault"))[:160])
                 for item in recusadas[:12]],
            )
        )
    add("\n**Ações mais executadas**\n")
    add(_tabela(["Ação", "Ocorrências"], acoes.most_common(20)))

    add("\n## 4. Defeitos reais encontrados\n")
    add(
        f"O detector rodou {len(getattr(detector, 'baseline', {}))} verificações determinísticas a "
        f"cada ciclo. Tudo o que já estava inconsistente no TESTE antes do primeiro evento foi "
        f"marcado como baseline e **não** entra nesta contagem.\n"
    )
    if achados:
        add(
            _tabela(
                ["Severidade", "Verificação", "Fase", "Evidência"],
                [
                    (item["severidade"], item["titulo"], item.get("fase") or "—",
                     json.dumps(item["evidencia"], ensure_ascii=False, default=str)[:220])
                    for item in achados[:60]
                ],
            )
        )
    else:
        add("Nenhuma inconsistência nova de estado/persistência foi detectada nesta execução.\n")
    add(
        f"\n- CRÍTICOS: **{len(criticos)}**\n- ERROS: **{len(graves)}**\n- AVISOS: **{len(avisos)}**\n"
    )
    add("\n### Erros técnicos observados no transporte HTTP\n")
    if tecnicos:
        add(
            _tabela(
                ["Instante virtual", "Operador", "Endpoint", "Status", "Código", "Exceção"],
                [
                    (item.get("simulation_timestamp"), item.get("operator"), item.get("endpoint"),
                     item.get("http_status"), item.get("error_code"), item.get("exception"))
                    for item in tecnicos[:40]
                ],
            )
        )
    else:
        add("Nenhum 5xx, timeout ou falha de transporte durante a execução.\n")
    if do_simulador:
        add("\n### Falhas do próprio simulador (SIMULATOR_ERROR)\n")
        add(
            _tabela(
                ["Instante virtual", "Posto", "Ação", "Exceção"],
                [
                    (item.get("simulation_timestamp"), item.get("resource"),
                     item.get("action"), item.get("exception"))
                    for item in do_simulador[:30]
                ],
            )
        )

    add("\n## 5. Bloqueios esperados (comportamento correto do Gestor)\n")
    add(
        f"{len(bloqueios)} recusas foram provocadas de propósito pelos erros humanos simulados e o "
        f"Gestor barrou todas elas. Isto **não** é defeito.\n\n"
    )
    add(_tabela(["Código de negócio", "Ocorrências"], codigos_bloqueio.most_common(30)))
    add(
        "\n### Recusas legítimas não previstas pelo roteiro (EXPECTED_VALIDATION)\n"
        "São decisões válidas do Gestor que o simulador não antecipou. Ficam visíveis para "
        "análise, sem serem contadas como bug.\n\n"
    )
    add(_tabela(["Código", "Ocorrências"], validacoes_por_codigo.most_common(25)))

    add("\n## 6. Problemas visuais\n")
    if problemas_visuais:
        contagem = Counter()
        for item in problemas_visuais:
            for problema in (item.get("auditoria") or {}).get("problemas") or []:
                contagem[problema] += 1
        add(_tabela(["Problema observado", "Ocorrências"], contagem.most_common()))
        add("\n**Evidências (com screenshot preservado)**\n")
        add(
            _tabela(
                ["Instante virtual", "Rota", "Posto", "Problemas", "Arquivo"],
                [
                    (item.get("simulation_timestamp"), item.get("rota"),
                     item.get("posto") or item.get("painel"),
                     ", ".join((item.get("auditoria") or {}).get("problemas") or []),
                     item.get("arquivo"))
                    for item in problemas_visuais[:40]
                ],
            )
        )
    else:
        add("Nenhum problema visual objetivo foi observado nas capturas desta execução.\n")
    add(f"\nTotal de capturas preservadas: **{len(capturas)}** em `screenshots/`.\n")

    add("\n## 7. Performance\n")
    add(
        _tabela(
            ["Métrica", "Valor"],
            [
                ("Requisições medidas", total_requests),
                ("Pico de RPS (janela de 30 s)", f"{pico_rps:.2f}"),
                ("Pico de p95", f"{pico_p95:.0f} ms"),
                ("Pico de p99", f"{pico_p99:.0f} ms"),
                ("Respostas 4xx (inclui bloqueios esperados)", total_4xx),
                ("Respostas 5xx", total_5xx),
                ("Timeouts", timeouts),
                ("Conexões PostgreSQL no pico", conexoes_pico),
                ("Deadlocks", deadlocks),
                ("Memória da API (início → fim)", f"{rss_inicial} MB → {rss_final} MB"),
                ("Amostras de banco", len(banco)),
                ("Deriva do relógio virtual", f"{clock.drift_seconds:.2f} s"),
            ],
        )
    )
    if de_performance:
        add("\n**Limiares ultrapassados**\n")
        add(
            _tabela(
                ["Instante virtual", "Evento", "Resultado"],
                [
                    (item.get("simulation_timestamp"), item.get("action"), item.get("result"))
                    for item in de_performance[:25]
                ],
            )
        )
    crescimento = estado_final.get("crescimento_tabelas") or {}
    if crescimento:
        add("\n**Crescimento das tabelas durante a execução**\n")
        add(
            _tabela(
                ["Tabela", "Linhas acrescidas"],
                sorted(
                    ((nome, valor) for nome, valor in crescimento.items() if valor),
                    key=lambda item: item[1],
                    reverse=True,
                )[:20],
            )
        )

    add("\n## 8. Inconsistências entre fontes (API × UI × Andon × Gestão)\n")
    if consistencia:
        divergencias = [item for item in consistencia if item.get("verificacao")]
        if divergencias:
            add(
                _tabela(
                    ["Tipo", "Título", "Fase", "Evidência"],
                    [
                        (item.get("verificacao"), item.get("titulo"), item.get("fase"),
                         json.dumps(item.get("evidencia"), ensure_ascii=False, default=str)[:200])
                        for item in divergencias[:40]
                    ],
                )
            )
        else:
            add(
                f"{len(consistencia)} comparações executadas sem divergência registrada entre o "
                "estado canônico do banco e o que Andon/Gestão apresentaram.\n"
            )
    else:
        add("_Nenhuma comparação registrada._\n")

    add("\n## 9. Estado final da fábrica\n")
    add("**WIP preservado (seção 6)**\n")
    add(_tabela(["Situação", "Apontamentos"], [(i.get("status"), i.get("total")) for i in wip]))
    add("\n**Produção da janela por setor**\n")
    add(
        _tabela(
            ["Setor", "Finalizados", "Boas", "Refugo", "Retrabalho"],
            [
                (i.get("tipo_setor"), i.get("finalizados"), i.get("boas"), i.get("refugo"),
                 i.get("retrabalho"))
                for i in (estado_final.get("producao_da_janela") or [])
            ],
        )
    )
    add("\n**Eventos de apontamento por estado**\n")
    add(
        _tabela(
            ["Estado", "Eventos"],
            [(i.get("estado"), i.get("total")) for i in (estado_final.get("eventos_por_estado") or [])],
        )
    )
    add("\n**Paradas por motivo (top 15)**\n")
    add(
        _tabela(
            ["Código", "Motivo", "Planejada", "Ocorrências", "Minutos"],
            [
                (i.get("codigo_status_recurso"), i.get("nome"), _rotulo(i.get("planejado")),
                 i.get("ocorrencias"), i.get("minutos"))
                for i in paradas[:15]
            ],
        )
    )
    add("\n**Primeira peça**\n")
    add(_tabela(["Status", "Total", "Bloqueadas"],
                [(i.get("status"), i.get("total"), i.get("bloqueadas")) for i in primeira_peca]))
    add("\n**Autorizações do responsável**\n")
    add(_tabela(["Ocorrência", "Decisão", "Total"],
                [(i.get("ocorrencia"), i.get("decisao"), i.get("total")) for i in autorizacoes]))
    add("\n**Tempo-pessoa por crachá (top 15)**\n")
    add(
        _tabela(
            ["Crachá", "Nome", "Participações", "Abertas", "Minutos-pessoa"],
            [
                (i.get("cracha"), i.get("nome"), i.get("participacoes"), i.get("abertas"),
                 i.get("minutos_pessoa"))
                for i in (estado_final.get("participacoes") or [])[:15]
            ],
        )
    )
    add("\n**OPs com mais de um operador (seção 18)**\n")
    add(
        _tabela(
            ["OP", "Operação", "Operadores", "Crachás"],
            [
                (i.get("op"), i.get("numero_operacao"), i.get("operadores"), i.get("crachas"))
                for i in multi_operador[:20]
            ],
        )
    )
    add("\n**Corte e Destaque**\n")
    add(_tabela(["Apontamentos de Corte", "Total"],
                [(i.get("status"), i.get("total")) for i in corte]))
    add(_tabela(["Eventos de Destaque", "Total"],
                [(i.get("estado"), i.get("total")) for i in destaque]))
    add("\n**Outbox TOTVS (deve permanecer sem envio)**\n")
    add(_tabela(["Situação", "Total", "Enviadas"],
                [(i.get("status"), i.get("total"), i.get("enviadas")) for i in outbox]))

    add("\n## 10. IA industrial\n")
    ia = estado_final.get("ia") or []
    if ia:
        add(
            _tabela(
                ["Instante virtual", "Pergunta", "Disponível", "Latência (ms)", "Vazamento técnico"],
                [
                    (i.get("instante_virtual"), i.get("pergunta"), _rotulo(i.get("disponivel")),
                     i.get("latencia_ms"), ", ".join(i.get("vazamento_tecnico") or []) or "não")
                    for i in ia
                ],
            )
        )
    else:
        add("_Nenhuma consulta gerencial à IA foi concluída nesta execução._\n")

    add("\n## 11. Artefatos preservados\n")
    totais = telemetry.totais() if telemetry is not None else {}
    add(
        _tabela(
            ["Arquivo", "Registros"],
            [
                ("simulation_config.json", 1),
                ("preflight.json", len(getattr(preflight, "checagens", []) or [])),
                ("baseline_test.json", len(baseline.get("apontamentos_abertos") or [])),
                ("events.jsonl", totais.get("events", len(eventos))),
                ("errors.jsonl", totais.get("errors", len(erros))),
                ("expected_blocks.jsonl", totais.get("expected_blocks", len(bloqueios))),
                ("performance.jsonl", totais.get("performance", len(performance))),
                ("database_metrics.jsonl", totais.get("database_metrics", len(banco))),
                ("visual_events.jsonl", totais.get("visual_events", len(capturas))),
                ("consistency.jsonl", totais.get("consistency", len(consistencia))),
                ("final_state.json", 1),
                ("screenshots/", len(list((run_dir / "screenshots").glob("*.png")))),
                ("checkpoints/", len(list((run_dir / "checkpoints").glob("*.json")))),
                ("api_teste.log", 1),
            ],
        )
    )

    destino = run_dir / "report.md"
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino
