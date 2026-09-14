"""Projeção incremental e idempotente do planejamento SigmaNEST.

Diferença essencial para ``publicar_catalogo_sigmanest``: aquele método publica
um **snapshot completo** e inativa tudo que ficou de fora. Uma sincronização
incremental lê apenas uma janela recente e, por isso, **nunca** pode inativar o
que está fora da janela. Este repositório faz somente ``UPSERT``.

Nada aqui cria OP: ``catalogo_sigmanest_ops.codigo_op`` é a OP observada na
linha de peça do SigmaNEST e permanece um dado de planejamento. A identidade
canônica da OP continua sendo exclusividade do ``catalogo_pcp_ops``, alimentado
pelo TOTVS.
"""

from __future__ import annotations

from datetime import datetime
import hashlib

from app.core.normalization import normalizar_data_db


def _texto(valor):
    return str(valor if valor is not None else "").strip() or None


def _plano_hash(codigo_tarefa: str, programa: str, nome_chapa: str, repeat_id) -> str:
    """Identidade estável do nesting, independente do pacote de arquivo.

    O mesmo nesting reaparece no `ProgArchive` a cada evento. A identidade
    funcional é (tarefa, programa, chapa, repetição); usá-la mantém a
    sincronização idempotente e preserva o vínculo com `apontamentos_corte`.
    """

    bruto = "|".join(
        (
            str(codigo_tarefa or "").strip().upper(),
            str(programa or "").strip().upper(),
            str(nome_chapa or "").strip().upper(),
            str(int(repeat_id) if repeat_id is not None else 1),
        )
    )
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


class SigmaNestRepositoryMixin:
    """Escrita incremental nas tabelas canônicas de planejamento de Corte."""

    def ultima_sincronizacao_sigmanest(self):
        """Marca d'água da última projeção, usada para a leitura incremental."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    MAX(data_programa) AS ultima_data_programa,
                    MAX(sigmanest_synced_at) AS ultima_sincronizacao,
                    COUNT(*) FILTER (WHERE sigmanest_synced_at IS NOT NULL) AS planos
                FROM catalogo_sigmanest_planos_corte
                """
            )
            linha = cursor.fetchone()
            return dict(linha) if linha else {}

    def sincronizar_catalogo_sigmanest(
        self,
        *,
        tarefas,
        programas,
        ops,
        planos_corte,
        sincronizado_em=None,
    ) -> dict:
        """Aplica a janela lida do SigmaNEST em uma única transação.

        Só faz ``INSERT ... ON CONFLICT DO UPDATE``. Registros fora da janela
        permanecem intactos, o que torna a operação segura para execução
        repetida e incremental.
        """

        instante = normalizar_data_db(sincronizado_em) or datetime.now().replace(
            microsecond=0
        )

        tarefas_linhas = []
        vistas = set()
        for item in tarefas or ():
            codigo = str(item.get("codigo_tarefa") or "").strip().upper()
            if not codigo or codigo in vistas:
                continue
            vistas.add(codigo)
            espessura = item.get("espessura")
            tarefas_linhas.append(
                (
                    codigo,
                    _texto(item.get("material")),
                    float(espessura) if espessura not in (None, "") else None,
                    instante,
                )
            )

        programas_linhas = []
        chaves = set()
        for item in programas or ():
            chave = (
                str(item.get("codigo_tarefa") or "").strip().upper(),
                str(item.get("programa") or "").strip(),
            )
            if not chave[0] or not chave[1] or chave in chaves or chave[0] not in vistas:
                continue
            chaves.add(chave)
            programas_linhas.append((*chave, instante))

        ops_linhas = []
        linhas_vistas = set()
        for item in ops or ():
            tarefa = str(item.get("codigo_tarefa") or "").strip().upper()
            codigo_op = str(item.get("codigo_op") or "").strip().upper()
            linha_hash = str(item.get("linha_hash") or "").strip()
            if not tarefa or not codigo_op or not linha_hash or tarefa not in vistas:
                continue
            if linha_hash in linhas_vistas:
                continue
            linhas_vistas.add(linha_hash)
            ops_linhas.append(
                (
                    linha_hash,
                    tarefa,
                    # Programa em que esta peça foi aninhada. Anulável: linhas
                    # projetadas antes da Wave 6C ainda não o possuem.
                    _texto(item.get("programa")) or None,
                    codigo_op,
                    _texto(item.get("id_peca")),
                    str(item.get("setor_destino") or "Almoxarifado").strip(),
                    max(0, int(item.get("quantidade") or 0)),
                    _texto(item.get("dobra")),
                    _texto(item.get("usinagem")),
                    _texto(item.get("solda")),
                    _texto(item.get("chanfro")),
                    instante,
                )
            )

        planos_linhas = []
        planos_vistos = set()
        for item in planos_corte or ():
            tarefa = str(item.get("codigo_tarefa") or "").strip().upper()
            programa = str(item.get("programa") or "").strip()
            data_programa = normalizar_data_db(item.get("data_programa"))
            maquina = str(item.get("maquina_sigmanest") or "").strip()
            if not tarefa or not programa or not maquina or data_programa is None:
                continue
            if tarefa not in vistas:
                continue
            plano_hash = str(item.get("plano_hash") or "").strip() or _plano_hash(
                tarefa, programa, item.get("nome_chapa"), item.get("sigmanest_repeat_id")
            )
            if plano_hash in planos_vistos:
                continue
            planos_vistos.add(plano_hash)
            planos_linhas.append(
                (
                    plano_hash,
                    tarefa,
                    programa,
                    _texto(item.get("nome_chapa")),
                    max(1, int(item.get("sequencia_nesting") or 1)),
                    float(item.get("area_usada") or 0),
                    float(item.get("fracao_sucata") or 0),
                    max(1, int(item.get("quantidade_processo") or 1)),
                    maquina,
                    float(item.get("tempo_previsto_segundos") or 0),
                    _texto(item.get("tempo_previsto_formatado")),
                    data_programa.date(),
                    _texto(item.get("status_programa")),
                    instante,
                    item.get("sigmanest_repeat_id"),
                    item.get("sigmanest_archive_packet_id"),
                    normalizar_data_db(item.get("sigmanest_comp_date")),
                    _texto(item.get("sigmanest_trans_type")),
                    instante,
                )
            )

        with self.connection() as connection, connection.cursor() as cursor:
            if tarefas_linhas:
                cursor.executemany(
                    """
                    INSERT INTO catalogo_sigmanest_tarefas
                        (codigo_tarefa, material, espessura, ativo,
                         sincronizado_em, sigmanest_synced_at)
                    VALUES (%s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT (codigo_tarefa) DO UPDATE SET
                        material = COALESCE(EXCLUDED.material, catalogo_sigmanest_tarefas.material),
                        espessura = COALESCE(EXCLUDED.espessura, catalogo_sigmanest_tarefas.espessura),
                        ativo = TRUE,
                        sincronizado_em = EXCLUDED.sincronizado_em,
                        sigmanest_synced_at = EXCLUDED.sigmanest_synced_at
                    """,
                    [(*linha, linha[-1]) for linha in tarefas_linhas],
                )
            if programas_linhas:
                cursor.executemany(
                    """
                    INSERT INTO catalogo_sigmanest_programas
                        (codigo_tarefa, programa, ativo, sincronizado_em)
                    VALUES (%s, %s, TRUE, %s)
                    ON CONFLICT (codigo_tarefa, programa) DO UPDATE SET
                        ativo = TRUE,
                        sincronizado_em = EXCLUDED.sincronizado_em
                    """,
                    programas_linhas,
                )
            if ops_linhas:
                cursor.executemany(
                    """
                    INSERT INTO catalogo_sigmanest_ops
                        (linha_hash, codigo_tarefa, programa, codigo_op, id_peca,
                         setor_destino, quantidade, dobra, usinagem, solda, chanfro,
                         ativo, sincronizado_em, sigmanest_synced_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT (linha_hash) DO UPDATE SET
                        codigo_tarefa = EXCLUDED.codigo_tarefa,
                        programa = EXCLUDED.programa,
                        codigo_op = EXCLUDED.codigo_op,
                        id_peca = EXCLUDED.id_peca,
                        setor_destino = EXCLUDED.setor_destino,
                        quantidade = EXCLUDED.quantidade,
                        dobra = EXCLUDED.dobra,
                        usinagem = EXCLUDED.usinagem,
                        solda = EXCLUDED.solda,
                        chanfro = EXCLUDED.chanfro,
                        ativo = TRUE,
                        sincronizado_em = EXCLUDED.sincronizado_em,
                        sigmanest_synced_at = EXCLUDED.sigmanest_synced_at
                    """,
                    [(*linha, linha[-1]) for linha in ops_linhas],
                )
            if planos_linhas:
                cursor.executemany(
                    """
                    INSERT INTO catalogo_sigmanest_planos_corte (
                        plano_hash, codigo_tarefa, programa, nome_chapa,
                        sequencia_nesting, area_usada, fracao_sucata,
                        quantidade_processo, maquina_sigmanest, tempo_previsto_segundos,
                        tempo_previsto_formatado, data_programa, status_programa,
                        ativo, sincronizado_em,
                        sigmanest_repeat_id, sigmanest_archive_packet_id,
                        sigmanest_comp_date, sigmanest_trans_type, sigmanest_synced_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        TRUE, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (plano_hash) DO UPDATE SET
                        codigo_tarefa = EXCLUDED.codigo_tarefa,
                        programa = EXCLUDED.programa,
                        nome_chapa = EXCLUDED.nome_chapa,
                        sequencia_nesting = EXCLUDED.sequencia_nesting,
                        area_usada = EXCLUDED.area_usada,
                        fracao_sucata = EXCLUDED.fracao_sucata,
                        quantidade_processo = EXCLUDED.quantidade_processo,
                        maquina_sigmanest = EXCLUDED.maquina_sigmanest,
                        tempo_previsto_segundos = EXCLUDED.tempo_previsto_segundos,
                        tempo_previsto_formatado = EXCLUDED.tempo_previsto_formatado,
                        data_programa = EXCLUDED.data_programa,
                        status_programa = EXCLUDED.status_programa,
                        ativo = TRUE,
                        sincronizado_em = EXCLUDED.sincronizado_em,
                        sigmanest_repeat_id = EXCLUDED.sigmanest_repeat_id,
                        sigmanest_archive_packet_id = EXCLUDED.sigmanest_archive_packet_id,
                        sigmanest_comp_date = EXCLUDED.sigmanest_comp_date,
                        sigmanest_trans_type = EXCLUDED.sigmanest_trans_type,
                        sigmanest_synced_at = EXCLUDED.sigmanest_synced_at
                    """,
                    planos_linhas,
                )

        return {
            "tarefas": len(tarefas_linhas),
            "programas": len(programas_linhas),
            "ops": len(ops_linhas),
            "planos_corte": len(planos_linhas),
            "sincronizado_em": instante,
        }
