import unittest

from app.core.operator_sectors import operator_route_resource_label
from mes.services.operator_flow import OperatorFlowService, OperatorState, validate_transition
from tests.fakes import FakeDatabase
from tests.helpers import liberar_primeira_peca


class OperatorFlowTests(unittest.TestCase):
    def _service(self, *, primeira_peca_liberada=True):
        """Posto de Dobra pronto para apontar.

        Wave 6B: em Dobra, Usinagem e Serra o Iniciar passa pelo portão
        Setup/Qualidade. Estes testes são da máquina de estados, não do portão
        — por isso o fixture já entrega a primeira peça aprovada, como o posto
        real está depois do popup. O portão em si é testado em
        ``tests/test_first_piece_gate.py`` e ``tests/test_wave6b_gate.py``.
        """

        db = FakeDatabase()
        task_id = db.inserir_tarefa("T-OPERADOR")
        db.inserir_op_na_tarefa(task_id, "OP-OPERADOR", "PECA", "Dobra", 2)
        operation = {
            "id": 10,
            "codigo_op": "OP-OPERADOR",
            "numero_operacao": "20",
            "codigo_recurso": "DOBRA3",
            "descricao_operacao": "DOBRA",
            "tipo_setor": "Dobra",
            "produto_codigo": "PECA",
            "produto_descricao": "PECA TESTE",
            "quantidade": 2,
        }
        db.catalog_operations.append(operation)
        if primeira_peca_liberada:
            liberar_primeira_peca(
                db,
                "OPERADOR TESTE",
                op="OP-OPERADOR",
                setor="Dobra",
                recurso="1303",
                operacao=operation,
            )
        return db, OperatorFlowService(db, "OPERADOR TESTE"), operation

    def _liberar_primeira_peca(self, db, operation, op="OP-OPERADOR", recurso="1303"):
        """Wave 5: sem primeira peça aprovada o backend recusa a finalização."""

        resultado = liberar_primeira_peca(
            db,
            "OPERADOR TESTE",
            op=op,
            setor="Dobra",
            recurso=recurso,
            operacao=operation,
        )
        self.assertTrue(resultado.ok, resultado.message)
        return resultado

    def test_inicio_exige_op_operacao_e_recurso(self):
        invalid = validate_transition(
            OperatorState.QUEUED,
            OperatorState.PRODUCTION,
            {"op": "OP-1", "recurso": "1303"},
        )
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.missing_fields, ("operacao",))

        valid = validate_transition(
            OperatorState.QUEUED,
            OperatorState.PRODUCTION,
            {"op": "OP-1", "operacao": "20", "recurso": "1303"},
        )
        self.assertTrue(valid.ok)

    def test_inicio_recusa_operacao_sem_quantidade_planejada(self):
        _db, service, operation = self._service()

        result = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao={**operation, "quantidade": None},
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "quantidade_planejada_indisponivel")

    def test_recurso_exclusivo_bloqueia_corrida_na_transacao(self):
        db, service, first_operation = self._service()
        second_task = db.inserir_tarefa("T-OPERADOR-2")
        db.inserir_op_na_tarefa(second_task, "OP-OPERADOR-2", "PECA-2", "Dobra", 1)
        second_operation = {
            **first_operation,
            "id": 11,
            "codigo_op": "OP-OPERADOR-2",
            "produto_codigo": "PECA-2",
            "quantidade": 1,
        }
        db.catalog_operations.append(second_operation)

        first = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=first_operation,
            recurso_exclusivo=True,
        )
        second = service.executar(
            "Início",
            op="OP-OPERADOR-2",
            setor="Dobra",
            recurso="1303",
            operacao=second_operation,
            recurso_exclusivo=True,
        )

        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(second.code, "operator_resource_occupied")

    def test_recurso_exclusivo_nao_permite_contornar_por_parada_e_retomada(self):
        db, service, first_operation = self._service()
        second_task = db.inserir_tarefa("T-OPERADOR-PARADA")
        db.inserir_op_na_tarefa(second_task, "OP-OPERADOR-PARADA", "PECA-2", "Dobra", 1)
        second_operation = {
            **first_operation,
            "id": 12,
            "codigo_op": "OP-OPERADOR-PARADA",
            "produto_codigo": "PECA-2",
            "quantidade": 1,
        }
        db.catalog_operations.append(second_operation)

        first = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303",
            operacao=first_operation, recurso_exclusivo=True,
        )
        queued = db.enfileirar_apontamento_operacional(
            "OP-OPERADOR-PARADA", "PECA-2", second_task, "Dobra", "1303", "OPERADOR",
            quantidade=1, operacao=second_operation,
        )
        stopped = service.executar(
            "Parada", op="OP-OPERADOR-PARADA", setor="Dobra", recurso="1303",
            operacao=second_operation, motivo="Ajuste", motivo_codigo="0029",
            recurso_exclusivo=True,
        )

        self.assertTrue(first.ok)
        self.assertEqual(queued["status"], "Aguardando")
        self.assertFalse(stopped.ok)
        self.assertEqual(stopped.code, "operator_resource_occupied")
        self.assertEqual(db.buscar_apontamento_operacional(queued["id"])["status"], "Aguardando")

    def test_parada_exige_motivo_e_finalizacao_exige_quantidades_e_operador(self):
        self.assertEqual(
            validate_transition(OperatorState.PRODUCTION, OperatorState.STOPPED).missing_fields,
            ("motivo_parada",),
        )
        final = validate_transition(
            OperatorState.PRODUCTION,
            OperatorState.FINISHED,
            {"pecas_boas": 0, "refugo": 0, "operador_id": "CRACHA"},
        )
        self.assertTrue(final.ok)

    def test_finalizado_e_terminal(self):
        result = validate_transition(OperatorState.FINISHED, OperatorState.PRODUCTION)
        self.assertFalse(result.ok)

    def test_botoes_setup_retrabalho_e_retorno_a_producao_persistem_catalogo(self):
        db, service, operation = self._service()
        started = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self.assertTrue(started.ok)

        setup = service.executar(
            "Setup", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self.assertTrue(setup.ok)
        self.assertEqual(setup.data["codigo_status_recurso"], "1005")

        resumed = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self.assertTrue(resumed.ok)
        rework = service.executar(
            "Retrabalho", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self.assertTrue(rework.ok)
        self.assertEqual(rework.data["codigo_status_recurso"], "0040")
        self.assertEqual(db.operator_events[-1]["codigo_status_recurso"], "0040")

    def test_setup_exige_inicio_da_op(self):
        _db, service, operation = self._service()

        result = service.executar(
            "Setup",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "setup_exige_inicio")
        self.assertEqual(result.data["estado_atual"], "fila")

    def test_fila_pode_ir_diretamente_para_retrabalho(self):
        _db, service, operation = self._service()

        result = service.executar(
            "Retrabalho",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )

        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.data["status"], "Retrabalho")

    def test_setup_nao_esta_disponivel_para_pintura_ou_solda(self):
        for sector in ("Pintura", "Solda Aço", "Protótipo"):
            with self.subTest(sector=sector):
                _db, service, operation = self._service()
                result = service.executar(
                    "Setup",
                    op="OP-OPERADOR",
                    setor=sector,
                    recurso=sector,
                    operacao=operation,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.code, "setup_indisponivel_setor")

    def test_parada_fisica_independe_de_op_ativa(self):
        db, service, _operation = self._service()
        result = service.registrar_parada_recurso(
            setor="Dobra",
            recurso="1303",
            motivo_codigo="0029",
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.code, "parada_recurso_sem_op")
        self.assertEqual(db.buscar_estado_recurso_atual("1303")["categoria"], "parada")
        self.assertIsNone(db.buscar_estado_recurso_atual("1303").get("op"))

    def test_parada_fisica_recusa_motivo_de_retorno_automatico(self):
        _db, service, _operation = self._service()
        result = service.registrar_parada_recurso(
            setor="Dobra",
            recurso="1303",
            motivo_codigo="0002",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "motivo_parada_invalido")

    def test_retomada_fisica_encerra_parada_sem_op(self):
        db, service, _operation = self._service()
        self.assertTrue(
            service.registrar_parada_recurso(
                setor="Dobra", recurso="1303", motivo_codigo="0029"
            ).ok
        )
        retomada = service.retomar_recurso_sem_op(setor="Dobra", recurso="1303")
        self.assertTrue(retomada.ok, retomada.message)
        self.assertEqual(retomada.code, "retomada_recurso_sem_op")
        self.assertEqual(db.buscar_estado_recurso_atual("1303")["categoria"], "fila")

    def test_retomada_sem_op_recusa_recurso_que_nao_esta_parado(self):
        _db, service, _operation = self._service()
        recusa = service.retomar_recurso_sem_op(setor="Dobra", recurso="1303")
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "recurso_nao_parado")

    def test_atividade_sem_op_abre_e_fecha_o_estado_do_recurso(self):
        db, service, _operation = self._service()
        inicio = service.iniciar_atividade_sem_op(setor="Dobra", recurso="1303")
        self.assertTrue(inicio.ok, inicio.message)
        self.assertEqual(inicio.code, "inicio_atividade_sem_op")
        estado = db.buscar_estado_recurso_atual("1303")
        self.assertEqual(estado["categoria"], "atividade_sem_op")
        self.assertIsNone(estado.get("op"))
        fim = service.finalizar_atividade_sem_op(setor="Dobra", recurso="1303")
        self.assertTrue(fim.ok, fim.message)
        self.assertEqual(fim.code, "fim_atividade_sem_op")
        self.assertEqual(db.buscar_estado_recurso_atual("1303")["categoria"], "fila")

    def test_atividade_sem_op_grava_tipo_diaria_apenas_no_corte_e_no_destaque(self):
        for setor, esperado in (("Corte", "diaria"), ("Destaque", "diaria"), ("Dobra", None)):
            with self.subTest(setor=setor):
                db, service, _operation = self._service()
                inicio = service.iniciar_atividade_sem_op(setor=setor, recurso="1303")
                self.assertTrue(inicio.ok, inicio.message)
                estado = db.buscar_estado_recurso_atual("1303")
                self.assertEqual(estado.get("tipo_atividade"), esperado)
                self.assertEqual(
                    estado.get("motivo"),
                    "Atividade diária" if esperado else "Atividade s/OP",
                )

    def test_atividade_sem_op_nao_duplica_nem_fecha_o_que_nao_abriu(self):
        _db, service, _operation = self._service()
        self.assertFalse(
            service.finalizar_atividade_sem_op(setor="Dobra", recurso="1303").ok
        )
        self.assertEqual(
            service.finalizar_atividade_sem_op(setor="Dobra", recurso="1303").code,
            "atividade_sem_op_inexistente",
        )
        self.assertTrue(service.iniciar_atividade_sem_op(setor="Dobra", recurso="1303").ok)
        repetida = service.iniciar_atividade_sem_op(setor="Dobra", recurso="1303")
        self.assertFalse(repetida.ok)
        self.assertEqual(repetida.code, "atividade_sem_op_em_andamento")

    def test_atividade_sem_op_recusa_recurso_parado(self):
        _db, service, _operation = self._service()
        self.assertTrue(
            service.registrar_parada_recurso(
                setor="Dobra", recurso="1303", motivo_codigo="0029"
            ).ok
        )
        recusa = service.iniciar_atividade_sem_op(setor="Dobra", recurso="1303")
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "recurso_parado")

    def test_parada_valida_codigo_e_comentario_obrigatorio(self):
        _db, service, operation = self._service()
        reason_codes = {item["codigo"] for item in service.listar_motivos_parada()}
        self.assertNotIn("1005", reason_codes)
        self.assertNotIn("0040", reason_codes)
        self.assertNotIn("0002", reason_codes)
        self.assertTrue(
            service.executar(
                "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
            ).ok
        )
        invalid_rework_reason = service.executar(
            "Parada",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            motivo_codigo="0040",
        )
        self.assertEqual(invalid_rework_reason.code, "motivo_parada_invalido")
        missing_comment = service.executar(
            "Parada",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            motivo_codigo="0015",
        )
        self.assertEqual(missing_comment.code, "comentario_obrigatorio")
        stopped = service.executar(
            "Parada",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            motivo_codigo="0015",
            comentario="Peça separada para análise.",
        )
        self.assertTrue(stopped.ok)
        self.assertEqual(stopped.data["codigo_status_recurso"], "0015")

    def test_roteiro_completo_nao_redireciona_acao_para_outra_operacao(self):
        db, service, dobra = self._service()
        db.catalog_operations[:] = [
            {
                **dobra,
                "id": 9,
                "numero_operacao": "10",
                "codigo_recurso": "LASER",
                "descricao_operacao": "CORTE",
                "tipo_setor": "Corte",
            },
            dobra,
            {
                **dobra,
                "id": 11,
                "numero_operacao": "40",
                "codigo_recurso": "PINT.L",
                "descricao_operacao": "PINTURA",
                "tipo_setor": "Pintura",
            },
        ]

        route = service.listar_operacoes("OP-OPERADOR", "Dobra")
        self.assertEqual([row["numero_operacao"] for row in route], ["10", "20", "40"])
        self.assertEqual(
            [row["visual_status"] for row in route],
            ["current", "pending", "pending"],
        )
        self.assertFalse(route[0]["actionable"])
        self.assertFalse(route[1]["actionable"])

        # A tela do operador sempre consulta o roteiro com o posto aberto.
        posto = service.listar_operacoes("OP-OPERADOR", "Dobra", "1303")
        # Wave 2: a etapa de Dobra é do próprio posto, então continua
        # selecionável — apenas exige a confirmação canônica de exceção.
        self.assertTrue(posto[1]["selectable"])
        self.assertTrue(posto[1]["requires_confirmation"])
        self.assertFalse(posto[1]["actionable"])
        # A seleção mantém o roteiro completo disponível; a confirmação e a
        # autorização protegem o apontamento fora do recurso do posto.
        self.assertTrue(posto[0]["selectable"])
        self.assertTrue(posto[2]["selectable"])

        pendente = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=route[1],
        )
        self.assertFalse(pendente.ok)
        self.assertEqual(pendente.code, "confirmacao_etapa_anterior_obrigatoria")
        self.assertEqual(pendente.data["op"], "OP-OPERADOR")
        self.assertEqual(pendente.data["etapa_atual"], "10 - CORTE")
        self.assertEqual(pendente.data["operacao_selecionada"], "20 - DOBRA")
        # Sem crachá autorizado nada é registrado.
        self.assertEqual(
            db.listar_apontamentos_operacionais("Dobra", maquina="1303"), []
        )
        # A confirmação explícita libera a etapa do próprio posto.
        confirmado = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303",
            operacao=route[1], confirmar_etapa_anterior_pendente=True,
            operadores_cracha=["1"],
        )
        self.assertTrue(confirmado.ok, confirmado.message)

        # Uma etapa posterior do roteiro também é selecionável; ela continua
        # exigindo a confirmação existente antes do apontamento.
        posterior = service.executar(
            "Parada",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=route[2],
            motivo_codigo="0029",
        )
        self.assertFalse(posterior.ok)
        self.assertIn(
            posterior.code,
            {"operator_resource_occupied"},
        )
        self.assertFalse(
            service.executar(
                "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303",
                operacao=route[0], confirmar_etapa_anterior_pendente=True,
                operadores_cracha=["1"],
            ).ok
        )

    def test_etapa_em_outro_recurso_exige_confirmacao_e_autorizacao(self):
        db, service, dobra = self._service()
        db.catalog_operations.insert(
            0,
            {
                **dobra,
                "id": 9,
                "numero_operacao": "10",
                "codigo_recurso": "LASER",
                "descricao_operacao": "CORTE",
                "tipo_setor": "Corte",
            },
        )
        db.catalog_operations.append(
            {
                **dobra,
                "id": 11,
                "numero_operacao": "40",
                "codigo_recurso": "PINT.L",
                "descricao_operacao": "PINTURA",
                "tipo_setor": "Pintura",
            }
        )

        roteiro = service.listar_operacoes("OP-OPERADOR", "Dobra", "1303")
        corte, dobra_atual, pintura = roteiro
        self.assertTrue(corte["visual_current"])
        self.assertTrue(dobra_atual["selectable"])
        self.assertTrue(pintura["selectable"])
        self.assertTrue(pintura["requires_confirmation"])

        pendente = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=pintura,
        )
        self.assertFalse(pendente.ok)
        self.assertEqual(pendente.code, "confirmacao_etapa_anterior_obrigatoria")
        self.assertTrue(pendente.data["confirmar_recurso_divergente"])
        self.assertEqual(db.appointments, [])

        self._liberar_primeira_peca(db, pintura)
        autorizado = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=pintura,
            confirmar_etapa_anterior_pendente=True,
            confirmar_recurso_divergente=True,
            operadores_cracha=["1"],
        )
        self.assertTrue(autorizado.ok, autorizado.message)
        self.assertEqual(autorizado.data["catalogo_operacao_id"], pintura["id"])

    def test_excecao_de_roteiro_recusa_cracha_ativo_sem_autorizacao(self):
        db, service, operation = self._service()
        db.cadastrar_operador_apontamento("2", "Operador sem alçada")
        pending = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303",
            operacao={**operation, "codigo_recurso": "DOBRA1"},
            confirmar_recurso_divergente=True,
            operadores_cracha=["2"],
        )

        self.assertFalse(pending.ok)
        self.assertEqual(pending.code, "cracha_autorizacao_nao_autorizado")
        self.assertEqual(db.appointments, [])

    def test_fluxos_especializados_mantem_a_eligibilidade_do_posto(self):
        db, service, dobra = self._service()
        db.catalog_operations.insert(
            0,
            {
                **dobra,
                "id": 9,
                "numero_operacao": "10",
                "codigo_recurso": "LASER",
                "descricao_operacao": "CORTE",
                "tipo_setor": "Corte",
            },
        )
        corte = service.listar_operacoes("OP-OPERADOR", "Corte", "Laser Ensis 3015")
        self.assertTrue(corte[0]["selectable"])
        self.assertFalse(corte[1]["selectable"])
        destaque = service.listar_operacoes("OP-OPERADOR", "Destaque", "Destaque")
        self.assertFalse(destaque[0]["selectable"])
        self.assertFalse(destaque[1]["selectable"])

    def _roteiro_com_inspecao_e_marco_terminal(self):
        db, service, dobra = self._service()
        db.catalog_operations.extend([
            {
                **dobra,
                "id": 40,
                "numero_operacao": "40",
                "codigo_recurso": "INSPEC",
                "descricao_operacao": "INSPECAO",
                "tipo_setor": None,
                "ativo": False,
                "inspecao_qualidade": True,
            },
            {
                **dobra,
                "id": 99,
                "numero_operacao": "99",
                "codigo_recurso": "ALMOX4",
                "descricao_operacao": "FINALIZADA",
                "tipo_setor": None,
                "ativo": False,
                "marco_terminal": True,
            },
        ])
        return db, service

    def test_inspecao_da_caldeiraria_e_concluida_sozinha_sem_apontamento(self):
        """Decisão do usuário, 16/09/2026: o recurso físico de inspeção da
        Caldeiraria não existe mais na fábrica. A etapa INSPECAO do roteiro
        (numérico, não a aba Qualidade) deixa de ser selecionável pelo posto
        — o Gestor a trata como sempre concluída, sem apontamento nenhum e
        sem produção fictícia — e a OP alcança o marco terminal só com a
        operação real."""

        db, service = self._roteiro_com_inspecao_e_marco_terminal()
        route = service.listar_operacoes("OP-OPERADOR", "Dobra", "1303")
        inspecao = next(row for row in route if row["numero_operacao"] == "40")
        self.assertEqual(inspecao["visual_status"], "done")
        self.assertFalse(inspecao["selectable"])

        real = next(row for row in route if row["numero_operacao"] == "20")
        inicio = service.executar("Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=real)
        self.assertEqual(inicio.message, "Produção iniciada.")
        concluido = service.executar(
            "Finalizado", op="OP-OPERADOR", setor="Dobra", recurso="1303",
            operacao=real, pecas_boas=2, operadores_cracha=["1"],
        )
        self.assertTrue(concluido.ok, concluido.message)
        # OP-05: a resposta confirma o que foi finalizado, com as quantidades.
        self.assertEqual(concluido.message, "OP OP-OPERADOR finalizada: 2 peça(s) boa(s), 0 refugo(s).")

        rota_final = service.listar_operacoes("OP-OPERADOR", "Dobra", "1303")
        terminal = next(row for row in rota_final if row["numero_operacao"] == "99")
        self.assertEqual(terminal["visual_status"], "done")
        self.assertEqual(
            [item["numero_operacao"] for item in db.appointments if item.get("op") == "OP-OPERADOR"],
            ["20"],
        )

    def test_marco_terminal_nunca_e_apontavel_nem_vira_etapa_atual(self):
        """99 - FINALIZADA é leitura do roteiro, não um posto de trabalho.

        Ele nasce com ``ativo = FALSE``, fica fora de toda consulta canônica e
        o TOTVS o deriva da última operação produtiva. Oferecê-lo no seletor
        criava um beco sem saída: era a única linha com ``pode_finalizar``
        enquanto o portão da primeira peça segurava a etapa real, e finalizar
        por ele não fecha apontamento nenhum.
        """

        db, service = self._roteiro_com_inspecao_e_marco_terminal()
        route = service.listar_operacoes("OP-OPERADOR", "Dobra", "1303")
        terminal = next(row for row in route if row["numero_operacao"] == "99")
        self.assertFalse(terminal["selectable"])
        self.assertFalse(terminal["pode_finalizar"])
        self.assertFalse(terminal["visual_current"])

        recusa = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303",
            operacao=terminal, confirmar_etapa_anterior_pendente=True,
            confirmar_recurso_divergente=True, operadores_cracha=["1"],
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "operacao_nao_apontavel")
        self.assertEqual(db.appointments, [])

    def test_ultima_etapa_real_concluida_encerra_o_roteiro_sem_selecionar_o_marco(self):
        """A última etapa real finalizada já leva a OP ao marco terminal."""

        db, service, dobra = self._service()
        db.catalog_operations.append(
            {
                **dobra,
                "id": 99,
                "numero_operacao": "99",
                "codigo_recurso": "ALMOX4",
                "descricao_operacao": "FINALIZADA",
                "tipo_setor": None,
                "ativo": False,
                "marco_terminal": True,
            }
        )
        self.assertTrue(
            service.executar(
                "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=dobra
            ).ok
        )
        self._liberar_primeira_peca(db, dobra)
        final = service.executar(
            "Finalizado", op="OP-OPERADOR", setor="Dobra", recurso="1303",
            operacao=dobra, pecas_boas=2, operadores_cracha=["1"],
        )
        self.assertTrue(final.ok, final.message)

        route = service.listar_operacoes("OP-OPERADOR", "Dobra", "1303")
        self.assertEqual([row["visual_status"] for row in route], ["done", "done"])
        self.assertEqual([row["visual_current"] for row in route], [False, False])
        self.assertFalse(any(row["selectable"] for row in route))

    def test_operacao_finalizada_nao_pode_ser_reaberta(self):
        db, service, operation = self._service()
        self.assertTrue(
            service.executar(
                "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
            ).ok
        )
        self._liberar_primeira_peca(db, operation)
        self.assertTrue(
            service.executar(
                "Finalizado",
                op="OP-OPERADOR",
                setor="Dobra",
                recurso="1303",
                operacao=operation,
                pecas_boas=2,
                operadores_cracha=["1"],
            ).ok
        )
        retry = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self.assertFalse(retry.ok)
        self.assertEqual(retry.code, "operacao_finalizada")

    def test_finalizacao_parcial_mantem_op_aberta_e_acumula_ate_o_total(self):
        db, service, operation = self._service()
        started = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self._liberar_primeira_peca(db, operation)

        partial = service.executar(
            "Finalizado",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=1,
            refugo=0,
            operadores_cracha=["1"],
        )
        self.assertTrue(partial.ok)
        self.assertEqual(partial.code, "finalizacao_parcial")
        self.assertEqual(partial.data["status"], "Aguardando")
        self.assertEqual(partial.data["saldo_restante"], 1)
        cards = service.listar_cartoes("Dobra", "1303")
        self.assertEqual(cards["queue"][0]["good"], 1)

        resumed = service.executar(
            "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
        )
        self.assertTrue(resumed.ok, resumed.message)

        completed = service.executar(
            "Finalizado",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=1,
            refugo=0,
            operadores_cracha=["1"],
        )
        self.assertTrue(completed.ok)
        self.assertEqual(completed.data["status"], "Finalizado")
        self.assertEqual(completed.data["quantidade_boa"], 2)
        self.assertEqual(
            [event["estado"] for event in db.operator_events],
            ["fila", "producao", "parcial", "producao", "finalizado"],
        )
        self.assertEqual(started.data["id"], completed.data["id"])

    def test_finalizacao_exige_cracha_cadastrado_e_aceita_varios_operadores(self):
        db, service, operation = self._service()
        db.cadastrar_operador_apontamento("2", "Maria", fonte="teste")
        self.assertTrue(
            service.executar(
                "Início", op="OP-OPERADOR", setor="Dobra", recurso="1303", operacao=operation
            ).ok
        )
        missing = service.executar(
            "Finalizado",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=2,
            refugo=0,
            operadores_cracha=[],
        )
        self.assertFalse(missing.ok)
        self.assertEqual(missing.code, "cracha_obrigatorio")
        invalid = service.executar(
            "Finalizado",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=2,
            refugo=0,
            operadores_cracha=["999"],
        )
        self.assertEqual(invalid.code, "cracha_invalido")
        finished = service.executar(
            "Finalizado",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=2,
            refugo=0,
            operadores_cracha=["1", "2"],
        )
        self.assertTrue(finished.ok)
        self.assertEqual(
            [item["cracha"] for item in db.operator_events[-1]["operadores"]],
            ["1", "2"],
        )

    def test_recurso_do_roteiro_usa_mapeamento_exato_e_fallback_no_codigo(self):
        self.assertEqual(operator_route_resource_label("Dobra", "DOBRA1"), "Gasparini")
        self.assertEqual(
            operator_route_resource_label(
                "Dobra",
                "SEM-MAPA",
                setor_atual="Dobra",
                recurso_atual="1303",
            ),
            "SEM-MAPA",
        )
        self.assertEqual(
            operator_route_resource_label("Usinagem", "NOVO", "Máquina Nova"),
            "Máquina Nova",
        )

    def test_inicio_fora_do_recurso_exige_confirmacao_e_cracha_auditado(self):
        db, service, operation = self._service()
        operation = {**operation, "codigo_recurso": "DOBRA1", "recurso_nome": "GASPARINI"}
        pending = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )
        self.assertFalse(pending.ok)
        self.assertEqual(pending.code, "confirmacao_recurso_obrigatoria")
        self.assertEqual(db.appointments, [])

        invalid = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            confirmar_recurso_divergente=True,
            operadores_cracha=["999"],
        )
        self.assertEqual(invalid.code, "cracha_invalido")
        self.assertEqual(db.appointments, [])

        accepted = service.executar(
            "Início",
            op="OP-OPERADOR",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            confirmar_recurso_divergente=True,
            operadores_cracha=["1"],
        )
        self.assertTrue(accepted.ok)
        event = db.operator_events[-1]
        self.assertTrue(event["recurso_divergente"])
        self.assertEqual(event["recurso_roteiro_codigo"], "DOBRA1")
        self.assertEqual(event["recurso_apontado"], "1303")
        self.assertEqual([item["cracha"] for item in event["operadores"]], ["1"])

    def test_fila_automatica_avanca_pelo_roteiro_apos_finalizacao(self):
        db = FakeDatabase()
        task_id = db.inserir_tarefa("T-FILA")
        db.inserir_op_na_tarefa(task_id, "OP-FILA", "PECA", "Dobra", 1)
        dobra = {
            "id": 101,
            "codigo_op": "OP-FILA",
            "numero_operacao": "10",
            "codigo_recurso": "DOBRA3",
            "descricao_operacao": "DOBRA",
            "tipo_setor": "Dobra",
            "produto_codigo": "PECA",
            "produto_descricao": "PECA FILA",
            "quantidade": 1,
            "ordem": 1,
        }
        usinagem = {
            **dobra,
            "id": 102,
            "numero_operacao": "20",
            "codigo_recurso": "CNC-01",
            "descricao_operacao": "USINAGEM",
            "tipo_setor": "Usinagem",
            "ordem": 2,
        }
        db.catalog_operations.extend((dobra, usinagem))
        service = OperatorFlowService(db, "OPERADOR TESTE")

        queue = service.listar_cartoes("Dobra", "1303")["queue"]
        self.assertEqual([row["op"] for row in queue], ["OP-FILA"])
        self.assertTrue(queue[0]["virtual_queue"])
        liberar_primeira_peca(
            db, "OPERADOR TESTE", op="OP-FILA", setor="Dobra", recurso="1303", operacao=dobra
        )
        self.assertTrue(
            service.executar(
                "Início", op="OP-FILA", setor="Dobra", recurso="1303", operacao=dobra
            ).ok
        )
        self.assertTrue(
            service.executar(
                "Finalizado",
                op="OP-FILA",
                setor="Dobra",
                recurso="1303",
                operacao=dobra,
                pecas_boas=1,
                operadores_cracha=["1"],
            ).ok
        )
        self.assertEqual(service.listar_cartoes("Dobra", "1303")["queue"], [])
        next_queue = service.listar_cartoes("Usinagem", "Romi D 1000")["queue"]
        self.assertEqual([row["op"] for row in next_queue], ["OP-FILA"])
        self.assertEqual(next_queue[0]["codigo_recurso"], "CNC-01")


if __name__ == "__main__":
    unittest.main()
