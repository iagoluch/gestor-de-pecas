"""Etapa 4C — saneamento de recursos e postos.

Prova que a identidade do recurso é única e centralizada: o mesmo mapa vale
para a ingestão TOTVS, para a fila e para a Tela do Operador; o código real da
operação nunca é substituído; e recurso de um setor não vaza para o posto de
outro.
"""

from datetime import datetime
import os
from pathlib import Path
import unittest
from uuid import uuid4

from app.core.operator_sectors import OPERATOR_SECTORS
# Importado antes do skipUnless: é este módulo que carrega o .env com
# TEST_DATABASE_URL, decidido na avaliação do decorador.
from app.database import Database
from app.core.resource_mapping import (
    OFFICIAL_RESOURCE_ALIASES,
    RESOURCE_FRIENDLY_NAMES,
    SECTOR_OWNED_RESOURCE_SECTORS,
    STATION_RESOURCE_CODES,
    canonical_resource_code,
    normalize_resource_code,
    resource_display_name,
    station_matches_route,
    station_resource_code,
)
from mes.integrations.totvs.models import TotvsActivityOrder
from mes.integrations.totvs.resource_mapping import (
    OFFICIAL_RESOURCE_ALIASES as TOTVS_ALIASES,
    TotvsResourceResolver,
)


ROOT = Path(__file__).resolve().parents[1]

# Setor cadastral de cada recurso real usado nos cenários, exatamente como está
# em ``catalogo_recursos_pcfactory``.
CADASTRO = {
    "DOBRA1": "Dobra", "DOBRA2": "Dobra", "DOBRA3": "Dobra",
    "CNC-01": "Usinagem", "CNC-02": "Usinagem", "FRESA1": "Usinagem",
    "TCNC-1": "Usinagem", "TORNOC": "Usinagem", "PMCV": "Usinagem", "ROSQU": "Usinagem",
    "SERRA1": "Serra", "SERRA2": "Serra", "SERRA3": "Serra",
    "SERRA4": "Serra", "SERRA5": "Serra", "SERRA6": "Serra",
    "PLASMA": "Corte", "LASER1": "Corte", "LASER": "Corte",
    "PINT.L": "Pintura", "PREP": "Pintura", "INSPE2": "Pintura",
    "ESTUFA": "Pintura", "RETOQ": "Pintura", "TINTA": "Pintura",
    "SOLDA4": "Solda", "ROBO P": "Solda", "ROBO S": "Solda", "D02DUO": "Solda",
}


def _atividade(machine_code=None, work_center_code=None, activity_description=None):
    return TotvsActivityOrder(
        production_order_number="A9716901001",
        activity_id="1",
        activity_code="10",
        activity_description=activity_description,
        split=None,
        item_code=None,
        item_description=None,
        activity_type=None,
        work_center_code=work_center_code,
        work_center_description=None,
        unit_time_type=None,
        time_resource=None,
        time_machine=None,
        time_setup=None,
        script_code=None,
        resource_quantity=None,
        production_quantity=None,
        activity_quantity=None,
        unit_activity_code=None,
        machine_code=machine_code,
        start_plan_date_time=None,
        end_plan_date_time=None,
        is_activity_start=None,
        is_activity_end=None,
        time_mod=None,
        time_ind_mes=None,
    )


class MapaCentralizadoTests(unittest.TestCase):
    """Uma única fonte de identidade de recurso para todo o produto."""

    def test_alias_oficial_vive_no_nucleo_e_o_adaptador_totvs_apenas_consome(self):
        adaptador = (ROOT / "mes/integrations/totvs/resource_mapping.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('OFFICIAL_RESOURCE_ALIASES = {"laser"', adaptador)
        self.assertIn("_CORE_RESOURCE_ALIASES", adaptador)
        self.assertEqual(
            {chave.casefold(): valor for chave, valor in OFFICIAL_RESOURCE_ALIASES.items()},
            TOTVS_ALIASES,
        )

    def test_identidade_canonica_resolve_alias_e_preserva_o_resto(self):
        self.assertEqual(canonical_resource_code("LASER"), "LASER1")
        self.assertEqual(canonical_resource_code("laser"), "LASER1")
        self.assertEqual(canonical_resource_code("LASER1"), "LASER1")
        self.assertEqual(canonical_resource_code("PLASMA"), "PLASMA")
        self.assertEqual(canonical_resource_code("ROBO P"), "ROBO P")
        self.assertEqual(canonical_resource_code(""), "")

    def test_alias_nao_reescreve_o_codigo_exibido_da_operacao(self):
        """O alias existe para comparar recursos, nunca para trocar o roteiro."""

        self.assertEqual(resource_display_name("LASER"), "LASER")
        self.assertEqual(resource_display_name("LASER", "CORTE LASER"), "CORTE LASER")
        self.assertEqual(resource_display_name("LASER1"), "Laser Ensis 3015")

    def test_ingestao_totvs_e_tela_do_operador_concordam_sobre_o_mesmo_recurso(self):
        resolver = TotvsResourceResolver(known_resource_sectors=CADASTRO.items())
        atividade = _atividade(machine_code="LASER", activity_description="CORTE")

        self.assertEqual(resolver.resolve_resource(atividade, sector="Corte"), "LASER1")
        # O mesmo código, vindo pelo roteiro, precisa chegar ao posto de Corte.
        self.assertTrue(
            station_matches_route("Corte", "Laser Ensis 3015", "LASER", resource_sector="Corte")
        )


class SerraTests(unittest.TestCase):
    """Relação posto ↔ máquina física da Serra, apurada na Etapa 4C."""

    def test_postos_de_serra_apontam_para_as_tres_maquinas_do_cadastro(self):
        self.assertEqual(station_resource_code("Serra", "S4220"), "SERRA1")
        self.assertEqual(station_resource_code("Serra", "SFHA-10"), "SERRA2")
        self.assertEqual(station_resource_code("Serra", "SFG-330"), "SERRA3")

    def test_cada_serra_real_entra_apenas_no_proprio_posto(self):
        esperado = {"SERRA1": "S4220", "SERRA2": "SFHA-10", "SERRA3": "SFG-330"}
        for recurso, posto_certo in esperado.items():
            for posto in ("S4220", "SFHA-10", "SFG-330"):
                with self.subTest(recurso=recurso, posto=posto):
                    self.assertEqual(
                        station_matches_route("Serra", posto, recurso, resource_sector="Serra"),
                        posto == posto_certo,
                    )

    def test_serra_nao_e_setor_dono_do_recurso(self):
        """Serra é posto-máquina: exige igualdade exata, não pertencimento."""

        self.assertNotIn("serra", SECTOR_OWNED_RESOURCE_SECTORS)
        for codigo in ("SERRA4", "SERRA5", "SERRA6"):
            for posto in ("S4220", "SFHA-10", "SFG-330"):
                with self.subTest(codigo=codigo, posto=posto):
                    self.assertFalse(
                        station_matches_route("Serra", posto, codigo, resource_sector="Serra")
                    )


class MatrizElegibilidadeTests(unittest.TestCase):
    """RECURSO → SETOR → POSTO → ELEGÍVEL, para todos os setores operacionais."""

    def _postos(self, setor):
        return next(
            (
                sector.resources
                for sector in OPERATOR_SECTORS
                if sector.name.casefold() == setor.casefold()
            ),
            (),
        )

    def test_recurso_nao_vaza_para_posto_de_outro_setor(self):
        vazamentos = []
        for codigo, setor in CADASTRO.items():
            for sector in OPERATOR_SECTORS:
                if sector.name.casefold() == setor.casefold():
                    continue
                for posto in sector.resources:
                    if station_matches_route(
                        sector.name, posto, codigo, resource_sector=setor
                    ):
                        vazamentos.append((codigo, setor, sector.name, posto))
        self.assertEqual(vazamentos, [])

    def test_setores_de_maquina_exigem_o_posto_exato(self):
        esperado = {
            ("Dobra", "Gasparini"): "DOBRA1",
            ("Dobra", "2204"): "DOBRA2",
            ("Dobra", "1303"): "DOBRA3",
            ("Usinagem", "Romi D 1000"): "CNC-01",
            ("Usinagem", "Eurostec"): "CNC-02",
            ("Usinagem", "Fresadora FTV31"): "FRESA1",
            ("Usinagem", "Romi GL 350M"): "TCNC-1",
            ("Usinagem", "Torno Mecânico"): "TORNOC",
            ("Corte", "Plasma TerraBlade 4"): "PLASMA",
            ("Corte", "Laser Ensis 3015"): "LASER1",
        }
        for (setor, posto), recurso in esperado.items():
            with self.subTest(setor=setor, posto=posto):
                self.assertTrue(
                    station_matches_route(setor, posto, recurso, resource_sector=setor)
                )
                outros = [
                    codigo for codigo, dono in CADASTRO.items()
                    if dono == setor and canonical_resource_code(codigo) != recurso
                ]
                for outro in outros:
                    self.assertFalse(
                        station_matches_route(setor, posto, outro, resource_sector=setor),
                        f"{outro} não pode apontar em {setor}/{posto}",
                    )

    def test_pintura_e_solda_seguem_pertencimento_e_preservam_o_codigo(self):
        pintura = ("PINT.L", "PREP", "INSPE2", "ESTUFA", "RETOQ", "TINTA")
        for codigo in pintura:
            with self.subTest(codigo=codigo):
                self.assertTrue(
                    station_matches_route("Pintura", "Pintura", codigo, resource_sector="Pintura")
                )
                # O recurso continua sendo ele mesmo, não vira PINT.L.
                self.assertEqual(canonical_resource_code(codigo), normalize_resource_code(codigo))
        for codigo in ("SOLDA4", "ROBO P", "ROBO S", "D02DUO"):
            with self.subTest(codigo=codigo):
                self.assertTrue(
                    station_matches_route("Solda", "Estação 7", codigo, resource_sector="Solda")
                )
                self.assertEqual(canonical_resource_code(codigo), normalize_resource_code(codigo))

    def test_montagem_continua_sem_recurso_cadastrado_e_sem_projecao_por_nome(self):
        montagem = next(
            sector for sector in OPERATOR_SECTORS if sector.name == "Montagem"
        )
        self.assertEqual(montagem.resources, ())
        self.assertIn("montagem", SECTOR_OWNED_RESOURCE_SECTORS)
        # Nome parecido não cria elegibilidade: sem cadastro, não aponta.
        self.assertFalse(
            station_matches_route("Montagem", "Montagem", "MPRT1", resource_sector=None)
        )

    def test_todo_posto_configurado_resolve_um_recurso_conhecido(self):
        orfaos = []
        for sector in OPERATOR_SECTORS:
            if sector.name.casefold() in SECTOR_OWNED_RESOURCE_SECTORS:
                continue
            for posto in sector.resources:
                if not station_resource_code(sector.name, posto):
                    orfaos.append((sector.name, posto))
        self.assertEqual(orfaos, [], "posto sem recurso canônico correspondente")

    def test_todo_recurso_de_apresentacao_tem_posto_declarado(self):
        postos = {codigo for codigo in STATION_RESOURCE_CODES.values()}
        # SOLDA4 é o recurso do setor dono, exibido sem posto-máquina próprio.
        esperado = set(RESOURCE_FRIENDLY_NAMES) - {"SOLDA4"}
        self.assertEqual(esperado - postos, set())


class AndonCatalogoFake:
    def __init__(self, recursos):
        self._recursos = recursos

    def listar_recursos_pcfactory(self):
        return self._recursos


class IdentidadeVenceRotuloTests(unittest.TestCase):
    """O código de um recurso pode ser o nome de outro; o código manda."""

    CATALOGO = [
        {"codigo": "ALMOX4", "nome": "ALMOX F IV", "tipo_setor": "Solda"},
        {"codigo": "ALMOXF4", "nome": "ALMOX4", "tipo_setor": "Solda"},
        {"codigo": "RETR", "nome": "RETRABALHO", "tipo_setor": "Solda"},
        {"codigo": "RETRABALHO", "nome": "RETRABALHO", "tipo_setor": "Solda"},
    ]

    def _snapshot(self, estados):
        from mes.contracts import AnalyticsFilter
        from mes.services.andon import AndonService

        momento = datetime(2026, 9, 4, 7, 0)
        return AndonService(AndonCatalogoFake(self.CATALOGO)).build_snapshot(
            AnalyticsFilter(inicio=datetime(2026, 9, 3, 8, 0), fim=momento),
            operational={"agora": momento, "resources": estados},
            overview={"kpis": {}, "resource_kpis": []},
        )

    def _recursos(self, snapshot):
        return [item for setor in snapshot["sectors"] for item in setor["resources"]]

    def test_catalogo_sem_estado_nao_cria_cards(self):
        snapshot = self._snapshot([])
        codigos = [item["code"] for item in self._recursos(snapshot)]

        self.assertEqual(codigos, [])
        self.assertEqual(snapshot["resource_count"], 0)

    def test_estado_vai_para_o_recurso_do_codigo_e_nao_para_o_homonimo(self):
        snapshot = self._snapshot(
            [
                {
                    "recurso": "ALMOX4",
                    "categoria": "producao",
                    "fonte": "eventos_estado_recurso",
                }
            ]
        )
        recursos = {item["code"]: item for item in self._recursos(snapshot)}

        self.assertEqual(len(recursos), 1)
        self.assertEqual(recursos["ALMOX4"]["state"]["category"], "producao")
        self.assertNotIn("ALMOXF4", recursos)

    def test_nome_repetido_entre_codigos_continua_ambiguo(self):
        """RETR e RETRABALHO compartilham o nome: nome não decide sozinho."""

        snapshot = self._snapshot(
            [
                {
                    "recurso": "RETRABALHO",
                    "categoria": "parada",
                    "fonte": "eventos_estado_recurso",
                }
            ]
        )
        recursos = {item["code"]: item for item in self._recursos(snapshot)}

        # O código RETRABALHO existe e recebe o estado; RETR não é escolhido
        # por semelhança de rótulo.
        self.assertEqual(recursos["RETRABALHO"]["state"]["category"], "parada")
        self.assertNotIn("RETR", recursos)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class CadastroRealTests(unittest.TestCase):
    """Matriz automática sobre o cadastro real de TESTE. Somente leitura."""

    @classmethod
    def setUpClass(cls):
        cls.db = Database()
        cls.catalogo = [
            dict(row) for row in cls._rows(
                """
                SELECT codigo, nome, tipo_setor, habilitado
                FROM catalogo_recursos_pcfactory ORDER BY codigo
                """
            )
        ]

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    @classmethod
    def _rows(cls, query):
        with cls.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def _setorizados(self):
        return [
            item for item in self.catalogo
            if str(item["tipo_setor"] or "").strip() and item["habilitado"]
        ]

    def test_nenhum_codigo_ativo_difere_de_outro_apenas_por_capitalizacao(self):
        ativos = [item for item in self.catalogo if item["habilitado"]]
        vistos = {}
        colisoes = []
        for item in ativos:
            chave = str(item["codigo"]).strip().upper()
            if chave in vistos:
                colisoes.append((vistos[chave], item["codigo"]))
            vistos[chave] = item["codigo"]
        self.assertEqual(colisoes, [], "duplicidade por caixa voltou ao cadastro")

    def test_variante_consolidada_permanece_registrada_apenas_desativada(self):
        """Consolidar não apaga: o histórico do cadastro fica auditável."""

        desativados = [item for item in self.catalogo if not item["habilitado"]]
        self.assertTrue(desativados, "nenhuma variante consolidada encontrada")
        for item in desativados:
            gemeo = [
                outro for outro in self.catalogo
                if outro["habilitado"]
                and str(outro["codigo"]).strip().upper() == str(item["codigo"]).strip().upper()
            ]
            self.assertEqual(
                len(gemeo), 1, f"{item['codigo']} desativado sem variante canônica ativa"
            )
            self.assertEqual(
                str(gemeo[0]["nome"]).strip().upper(), str(item["nome"]).strip().upper()
            )

    def test_matriz_recurso_setor_posto_nao_permite_vazamento(self):
        vazamentos = []
        for item in self._setorizados():
            codigo = str(item["codigo"]).strip()
            setor = str(item["tipo_setor"]).strip()
            for sector in OPERATOR_SECTORS:
                if sector.name.casefold() == setor.casefold():
                    continue
                for posto in sector.resources:
                    if station_matches_route(
                        sector.name, posto, codigo, resource_sector=setor
                    ):
                        vazamentos.append((codigo, setor, f"{sector.name}/{posto}"))
        self.assertEqual(vazamentos, [])

    def test_todo_recurso_de_roteiro_ativo_existe_no_cadastro(self):
        orfaos = self._rows(
            """
            SELECT DISTINCT o.codigo_recurso
            FROM catalogo_operacoes_op o
            LEFT JOIN catalogo_recursos_pcfactory r ON r.codigo = o.codigo_recurso
            WHERE o.ativo IS TRUE AND r.codigo IS NULL
            """
        )
        self.assertEqual(orfaos, [])

    def test_setor_do_cadastro_nunca_contradiz_o_setor_do_roteiro(self):
        contradicoes = self._rows(
            """
            SELECT o.codigo_recurso, r.tipo_setor AS cadastro, o.tipo_setor AS roteiro
            FROM catalogo_operacoes_op o
            JOIN catalogo_recursos_pcfactory r ON r.codigo = o.codigo_recurso
            WHERE o.ativo IS TRUE
              AND NULLIF(BTRIM(r.tipo_setor), '') IS NOT NULL
              AND UPPER(BTRIM(r.tipo_setor)) <> UPPER(BTRIM(COALESCE(o.tipo_setor, '')))
            """
        )
        self.assertEqual(contradicoes, [])

    def test_ingestao_totvs_usa_o_mesmo_cadastro_da_tela_do_operador(self):
        codigos = tuple(self.db.listar_codigos_recursos_totvs())
        setores = tuple(self.db.listar_setores_recursos_totvs())
        desativados = {
            str(item["codigo"]).strip()
            for item in self.catalogo if not item["habilitado"]
        }
        self.assertTrue(desativados)
        self.assertFalse(desativados & set(codigos), "variante desativada chegou ao TOTVS")

        resolver = TotvsResourceResolver(known_resource_sectors=setores)
        for codigo, setor in setores:
            postos = next(
                (
                    sector.resources for sector in OPERATOR_SECTORS
                    if sector.name.casefold() == str(setor).casefold()
                ),
                (),
            )
            elegivel = any(
                station_matches_route(setor, posto, codigo, resource_sector=setor)
                for posto in postos
            )
            if not elegivel:
                continue
            atividade = _atividade(machine_code=codigo)
            with self.subTest(codigo=codigo):
                # O que o posto aceita, a ingestão precisa aceitar também.
                self.assertEqual(
                    resolver.resolve_resource(atividade, sector=setor),
                    canonical_resource_code(codigo),
                )

    def test_ops_totvs_reais_alcancam_o_posto_do_seu_setor(self):
        operacoes = self._rows(
            """
            SELECT o.codigo_op, o.numero_operacao, o.codigo_recurso, o.tipo_setor,
                   r.tipo_setor AS cadastro
            FROM catalogo_operacoes_op o
            JOIN catalogo_pcp_ops p ON p.codigo_op = o.codigo_op
            LEFT JOIN catalogo_recursos_pcfactory r ON r.codigo = o.codigo_recurso
            WHERE p.totvs_unique_id IS NOT NULL AND o.ativo IS TRUE
            ORDER BY o.codigo_op, o.numero_operacao
            """
        )
        self.assertTrue(operacoes, "nenhuma operação de OP TOTVS no cadastro de TESTE")
        for operacao in operacoes:
            setor = str(operacao["tipo_setor"] or "").strip()
            postos = next(
                (
                    sector.resources for sector in OPERATOR_SECTORS
                    if sector.name.casefold() == setor.casefold()
                ),
                (),
            )
            with self.subTest(op=operacao["codigo_op"], recurso=operacao["codigo_recurso"]):
                self.assertTrue(
                    any(
                        station_matches_route(
                            setor,
                            posto,
                            operacao["codigo_recurso"],
                            resource_sector=operacao["cadastro"],
                        )
                        for posto in postos
                    ),
                    f"{operacao['codigo_recurso']} não alcança nenhum posto de {setor}",
                )


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ImportacaoDeRecursosTests(unittest.TestCase):
    """A importação não pode recriar a duplicidade que a 4C consolidou."""

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config

        base = load_postgres_config(testing=True)
        self.schema = "etapa4c_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as conexao:
            conexao.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def tearDown(self):
        import psycopg
        from psycopg import sql

        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as conexao:
            conexao.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _catalogo(self):
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                "SELECT codigo, nome, tipo_setor FROM catalogo_recursos_pcfactory ORDER BY codigo"
            )
            return [dict(linha) for linha in cursor.fetchall()]

    def test_variante_de_caixa_atualiza_a_linha_existente_em_vez_de_duplicar(self):
        self.db.publicar_recursos_pcfactory(
            [{"codigo": "SCGM8", "nome": "SOLD.TANQUE", "tipo_setor": "Solda"}]
        )
        # Exportação seguinte do PC Factory traz o mesmo recurso com outra caixa.
        self.db.publicar_recursos_pcfactory(
            [{"codigo": "SCGm8", "nome": "SOLD.TANQUE"}]
        )

        catalogo = self._catalogo()
        self.assertEqual([item["codigo"] for item in catalogo], ["SCGM8"])
        # O pertencimento cadastral sobrevive a uma importação sem tipo_setor.
        self.assertEqual(catalogo[0]["tipo_setor"], "Solda")

    def test_codigos_realmente_distintos_continuam_separados(self):
        self.db.publicar_recursos_pcfactory(
            [
                {"codigo": "SERRA1", "nome": "SERRA STARRET S4220", "tipo_setor": "Serra"},
                {"codigo": "SERRA2", "nome": "SERRA STRONG SFHA10", "tipo_setor": "Serra"},
            ]
        )
        self.assertEqual(
            [item["codigo"] for item in self._catalogo()], ["SERRA1", "SERRA2"]
        )


if __name__ == "__main__":
    unittest.main()
