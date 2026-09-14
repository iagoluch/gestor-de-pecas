"""Idempotência da geração manual de relatórios (D2).

Dois pedidos semanticamente iguais e simultâneos devem convergir para um único
artifact, um único arquivo físico e o mesmo ``artifact.id``.
"""

import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from mes.contracts import ReportError, ReportRequest, build_report_idempotency_key
from mes.services.industrial_reports import IndustrialReportService
from tests.fakes import FakeDatabase
from tests.test_intelligence_reports import CanonicalReportFacade


NOW = datetime(2026, 8, 26, 10, 30)


class ChaveDeterministicaTests(unittest.TestCase):
    def pedido(self, **kwargs):
        base = {
            "report_type": "completo",
            "inicio": datetime(2026, 8, 1),
            "fim": datetime(2026, 8, 24, 8, 32),
        }
        base.update(kwargs)
        return ReportRequest(**base)

    def chave(self, request, *, created_by=7, source="manual"):
        return build_report_idempotency_key(request, created_by=created_by, source=source)

    def test_solicitacoes_equivalentes_produzem_a_mesma_chave(self):
        # Caixa do tipo, filtro vazio e filtro ausente colapsam no mesmo valor.
        a = self.pedido()
        b = self.pedido(report_type="COMPLETO", setor="", recurso=None)
        self.assertEqual(self.chave(a), self.chave(b))
        self.assertEqual(self.chave(self.pedido(setor="Usinagem")), self.chave(self.pedido(setor="  usinagem  ")))

    def test_qualquer_dado_relevante_muda_a_chave(self):
        base = self.chave(self.pedido())
        variacoes = {
            "tipo": self.chave(self.pedido(report_type="paradas")),
            "inicio": self.chave(self.pedido(inicio=datetime(2026, 7, 1))),
            "fim": self.chave(self.pedido(fim=datetime(2026, 8, 25))),
            "setor": self.chave(self.pedido(setor="Corte")),
            "recurso": self.chave(self.pedido(recurso="Laser Ensis 3015")),
            "op": self.chave(self.pedido(op="SIM3M001729")),
            "indicador": self.chave(self.pedido(indicador="oee")),
            "analise": self.chave(self.pedido(include_executive_analysis=True)),
            "usuario": self.chave(self.pedido(), created_by=8),
            "origem": self.chave(self.pedido(), source="chat"),
        }
        for nome, valor in variacoes.items():
            with self.subTest(campo=nome):
                self.assertNotEqual(base, valor)

    def test_chave_nao_carrega_nome_de_arquivo_nem_aleatoriedade(self):
        chave = self.chave(self.pedido())
        self.assertTrue(chave.startswith("report:v1:"))
        self.assertNotIn(".xlsx", chave)
        self.assertNotIn("gestor_", chave)
        # Estável entre execuções: recalcular devolve exatamente o mesmo valor.
        self.assertEqual(chave, self.chave(self.pedido()))


class GeracaoConcorrenteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = FakeDatabase()
        self.lento = threading.Event()
        self.entrou = threading.Barrier(2, timeout=20)
        self.chamadas = []

    def tearDown(self):
        self.temp.cleanup()

    def servico(self, workbook_builder=None, **kwargs):
        return IndustrialReportService(
            CanonicalReportFacade(),
            self.database,
            artifact_dir=self.temp.name,
            workbook_builder=workbook_builder or (lambda *_: b"PK-conteudo-de-teste"),
            now_func=lambda: NOW,
            **kwargs,
        )

    def pedido(self, **kwargs):
        base = {
            "report_type": "completo",
            "inicio": datetime(2026, 8, 1),
            "fim": datetime(2026, 8, 24, 8, 32),
        }
        base.update(kwargs)
        return ReportRequest(**base)

    def arquivos(self):
        return sorted(p.name for p in Path(self.temp.name).rglob("*.xlsx"))

    def test_dois_pedidos_simultaneos_produzem_um_unico_artifact(self):
        def builder(*_args):
            self.chamadas.append(1)
            # Segura a geração até o segundo pedido tentar reservar a mesma chave.
            self.entrou.wait()
            self.lento.wait(timeout=20)
            return b"PK-conteudo-de-teste"

        servico = self.servico(workbook_builder=builder)
        request = self.pedido()
        chave = build_report_idempotency_key(request, created_by=7, source="manual")
        resultados = {}

        def gerar(nome, antes=None):
            def alvo():
                try:
                    if antes:
                        antes()
                    resultados[nome] = servico.generate(
                        request, created_by=7, source="manual", idempotency_key=chave
                    )
                except Exception as exc:  # pragma: no cover - falha explícita no assert
                    resultados[nome] = exc
            return threading.Thread(target=alvo)

        primeiro = gerar("a")
        primeiro.start()
        self.entrou.wait()          # o primeiro já está dentro do builder
        segundo = gerar("b")
        segundo.start()
        # Dá tempo do segundo perder a reserva e entrar em espera.
        threading.Event().wait(0.3)
        self.lento.set()
        primeiro.join(timeout=30)
        segundo.join(timeout=30)

        for nome in ("a", "b"):
            self.assertNotIsInstance(resultados.get(nome), Exception, resultados.get(nome))
        self.assertEqual(resultados["a"]["id"], resultados["b"]["id"])
        self.assertEqual(len(self.database.generated_reports), 1)
        self.assertEqual(len(self.arquivos()), 1)
        # O workbook foi construído uma única vez.
        self.assertEqual(len(self.chamadas), 1)
        self.assertEqual(self.database.generated_reports[0]["status"], "pronto")

    def test_pedido_equivalente_posterior_reutiliza_o_artifact_valido(self):
        servico = self.servico()
        request = self.pedido()
        chave = build_report_idempotency_key(request, created_by=7, source="manual")
        primeiro = servico.generate(request, created_by=7, source="manual", idempotency_key=chave)
        segundo = servico.generate(request, created_by=7, source="manual", idempotency_key=chave)
        self.assertEqual(primeiro["id"], segundo["id"])
        self.assertEqual(len(self.database.generated_reports), 1)
        self.assertEqual(len(self.arquivos()), 1)

    def test_pedido_diferente_gera_artifact_proprio(self):
        servico = self.servico()
        for setor in ("Usinagem", "Corte"):
            request = self.pedido(setor=setor)
            servico.generate(
                request,
                created_by=7,
                source="manual",
                idempotency_key=build_report_idempotency_key(request, created_by=7, source="manual"),
            )
        self.assertEqual(len(self.database.generated_reports), 2)
        self.assertEqual(len(self.arquivos()), 2)

    def test_falha_libera_a_chave_e_a_nova_tentativa_gera(self):
        estado = {"falhar": True}

        def builder(*_args):
            if estado["falhar"]:
                raise RuntimeError("falha simulada na construção do workbook")
            return b"PK-conteudo-de-teste"

        servico = self.servico(workbook_builder=builder)
        request = self.pedido()
        chave = build_report_idempotency_key(request, created_by=7, source="manual")

        with self.assertRaises(RuntimeError):
            servico.generate(request, created_by=7, source="manual", idempotency_key=chave)
        self.assertEqual(self.database.generated_reports[0]["status"], "falhou")
        self.assertEqual(self.arquivos(), [])

        estado["falhar"] = False
        retomado = servico.generate(request, created_by=7, source="manual", idempotency_key=chave)
        self.assertEqual(retomado["status"], "pronto")
        self.assertEqual(len(self.database.generated_reports), 1)
        self.assertEqual(len(self.arquivos()), 1)

    def test_artifact_expirado_e_regerado_em_vez_de_reaproveitado(self):
        servico = self.servico(expiration_hours=1)
        request = self.pedido()
        chave = build_report_idempotency_key(request, created_by=7, source="manual")
        primeiro = servico.generate(request, created_by=7, source="manual", idempotency_key=chave)

        # Relógio avança além da validade do artifact.
        depois = NOW + timedelta(hours=2)
        servico._now = lambda: depois
        segundo = servico.generate(request, created_by=7, source="manual", idempotency_key=chave)

        self.assertNotEqual(primeiro["id"], segundo["id"])
        self.assertEqual(segundo["status"], "pronto")
        # A reserva anterior foi retomada: continua existindo um único registro.
        self.assertEqual(len(self.database.generated_reports), 1)

    def test_espera_esgotada_devolve_erro_controlado_sem_gerar_segundo_arquivo(self):
        servico = self.servico(wait_seconds=0.05, wait_interval_seconds=0.01)
        request = self.pedido()
        chave = build_report_idempotency_key(request, created_by=7, source="manual")
        # Simula outra sessão que reservou a chave e ainda está gerando.
        self.database.reservar_relatorio_gerado(
            report_id="11111111-1111-1111-1111-111111111111",
            created_by=7,
            report_type=request.report_type,
            period_start=request.inicio,
            period_end=request.fim,
            filters=request.filters_dict(),
            filename="gestor_completo_2026-08-01_11111111.xlsx",
            storage_path=str(Path(self.temp.name) / "gestor_completo_2026-08-01_11111111.xlsx"),
            source="manual",
            created_at=NOW,
            expires_at=NOW + timedelta(hours=168),
            idempotency_key=chave,
            generation_metadata={},
        )
        with self.assertRaises(ReportError) as erro:
            servico.generate(request, created_by=7, source="manual", idempotency_key=chave)
        self.assertEqual(erro.exception.code, "report_generation_in_progress")
        self.assertEqual(erro.exception.status_code, 409)
        self.assertEqual(len(self.database.generated_reports), 1)
        self.assertEqual(self.arquivos(), [])


if __name__ == "__main__":
    unittest.main()
