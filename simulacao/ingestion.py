"""Geração de OPs sintéticas pelo **pipeline canônico** de ingestão.

A seção 9 é explícita: quando as OPs reais do TESTE não bastam, as sintéticas
entram pelo mesmo caminho que o ERP usa — o receptor SOAP
``POST /PcfIntegService`` com o ``TOTVSMessage/ProductionOrder`` V1. Não existe
``INSERT`` direto de OP, de roteiro ou de operação nesta simulação.

O que este módulo respeita, porque é regra do adaptador e não escolha do
simulador (``mes/integrations/totvs/resource_mapping.py``):

* o setor sai da igualdade exata de ``ActivityDescription`` com a rota do setor
  **ou** do pertencimento cadastral do recurso (válido só para Pintura, Solda e
  Montagem). Nome parecido não cria etapa apontável;
* ``MachineCode`` prevalece sobre ``WorkCenterCode``;
* o marco terminal é a assinatura exata ``(99, FINALIZADA, ALMOX4, ALMOX4)``;
* a inspeção da Qualidade é ``(INSPECAO QUALIDADE, CALDER, INSPEC)`` e nasce
  inativa de propósito — ela não aparece no posto do operador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random
from xml.sax.saxutils import escape

import httpx


SOAP_PATH = "/PcfIntegService"
SOAP_ACTION = "http://tempuri.org/EAIService/receiveMessage"
TERMINAL = {"codigo": "99", "desc": "FINALIZADA", "wc": "ALMOX4", "maquina": "ALMOX4"}


@dataclass
class EtapaSintetica:
    codigo: str
    descricao: str
    work_center: str
    maquina: str
    activity_id: str
    final: bool = False


@dataclass
class OrdemSintetica:
    numero: str
    produto: str
    descricao: str
    quantidade: int
    roteiro: str
    classe: str
    modelo: str
    etapas: list[EtapaSintetica] = field(default_factory=list)
    empresa: str = "01"
    filial: str = "010004"

    @property
    def unique_id(self) -> str:
        return f"{self.empresa}|{self.filial}|{self.numero}"


def _texto(tag: str, valor) -> str:
    return f"<{tag}>{escape(str(valor))}</{tag}>"


def montar_production_order(ordem: OrdemSintetica, gerado_em: datetime) -> str:
    """Monta o XML de negócio exatamente no contrato aceito pelo parser."""

    inicio = gerado_em.replace(hour=0, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(days=1)
    atividades = []
    for etapa in ordem.etapas:
        atividades.append(
            "<ActivityOrder>"
            + _texto("ProductionOrderNumber", ordem.numero)
            + _texto("ActivityID", etapa.activity_id)
            + _texto("ActivityCode", etapa.codigo)
            + _texto("ActivityDescription", etapa.descricao)
            + _texto("Split", "000")
            + _texto("ItemCode", ordem.produto)
            + _texto("ItemDescription", ordem.descricao)
            + _texto("ActivityType", "1")
            + _texto("WorkCenterCode", etapa.work_center)
            + _texto("WorkCenterDescription", etapa.work_center)
            + _texto("UnitTimeType", "1")
            + _texto("TimeResource", "0.01")
            + _texto("TimeMachine", "0.1")
            + _texto("TimeSetup", "0")
            + _texto("ScriptCode", ordem.roteiro)
            + _texto("ResourceQuantity", "1")
            + _texto("ProductionQuantity", ordem.quantidade)
            + _texto("ActivityQuantity", ordem.quantidade)
            + _texto("UnitActivityCode", "UN")
            + _texto("IsActivityEnd", "true" if etapa.final else "false")
            + _texto("MachineCode", etapa.maquina)
            + _texto("StartPlanDateTime", inicio.isoformat(timespec="seconds"))
            + _texto("EndPlanDateTime", fim.isoformat(timespec="seconds"))
            + _texto("TimeMOD", "0")
            + _texto("TimeIndMES", "3")
            + "</ActivityOrder>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TOTVSMessage xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:noNamespaceSchemaLocation="xmlschema/general/events/ProductionOrder_2_004.xsd">'
        '<MessageInformation version="2.004">'
        + _texto("UUID", ordem.unique_id)
        + _texto("Type", "BusinessMessage")
        + _texto("Transaction", "ProductionOrder")
        + _texto("StandardVersion", "1.0")
        + _texto("SourceApplication", "SIGAPCP")
        + _texto("CompanyId", ordem.empresa)
        + _texto("BranchId", ordem.filial)
        + _texto("UserId", "SIMULACAO")
        + '<Product name="MATA650" version="12.1.2510"/>'
        + _texto("GeneratedOn", gerado_em.isoformat(timespec="seconds"))
        + _texto("ContextName", "PROTHEUS")
        + _texto("DeliveryType", "Sync")
        + "</MessageInformation>"
        "<BusinessMessage><BusinessEvent>"
        + _texto("Entity", "ProductionOrder")
        + _texto("Event", "upsert")
        + f'<Identification><key name="InternalID">{escape(ordem.unique_id)}</key></Identification>'
        + "</BusinessEvent><BusinessContent>"
        + _texto("Number", ordem.numero)
        + _texto("ProductionOrderUniqueID", ordem.unique_id)
        + _texto("ItemCode", ordem.produto)
        + _texto("ItemDescription", ordem.descricao)
        + _texto("Type", "1")
        + _texto("Quantity", ordem.quantidade)
        + _texto("ReportQuantity", "0")
        + _texto("UnitOfMeasureCode", "UN")
        + _texto("StatusOrderType", "1")
        + _texto("ReportOrderType", "2")
        + _texto("WarehouseCode", "01")
        + _texto("ReleaseOrderDate", inicio.date().isoformat())
        + _texto("StartOrderDateTime", inicio.isoformat(timespec="seconds"))
        + _texto("EndOrderDateTime", fim.isoformat(timespec="seconds"))
        + _texto("ScriptCode", ordem.roteiro)
        + _texto("Priority", "500")
        + "<ListOfActivityOrders>"
        + "".join(atividades)
        + "</ListOfActivityOrders><ListOfMaterialOrders></ListOfMaterialOrders>"
        "</BusinessContent></BusinessMessage></TOTVSMessage>"
    )


def montar_envelope(xml_negocio: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        '<receiveMessage xmlns="http://tempuri.org/">'
        f"<pXmlDocument>{escape(xml_negocio)}</pXmlDocument>"
        "</receiveMessage></soap:Body></soap:Envelope>"
    )


class GeradorDeOrdens:
    """Sorteia ordens plausíveis a partir dos modelos declarados no JSON."""

    def __init__(self, ingestao: dict, seed: int, token: str = ""):
        self.config = ingestao
        self.random = random.Random(seed + 977)
        self.modelos = list(ingestao["modelos"])
        self.pesos = [float(item.get("peso", 1)) for item in self.modelos]
        self.prefixo = str(ingestao["prefixo"])
        self.empresa = str(ingestao["empresa"])
        self.filial = str(ingestao["filial"])
        # O token da execução mantém as OPs de execuções diferentes separadas no
        # catálogo. O cenário continua reproduzível pelo seed: o que muda é o
        # número da OP, não o modelo, a quantidade nem o comportamento.
        self.token = "".join(ch for ch in str(token or "") if ch.isalnum())[:6].upper()
        self._sequencia = 0
        self._activity = 900_000

    def _proximo_numero(self) -> str:
        self._sequencia += 1
        return f"{self.prefixo}{self.token}{self._sequencia:04d}"

    def _proxima_activity(self) -> str:
        self._activity += 1
        return f"{self.token}{self._activity}" if self.token else str(self._activity)

    def gerar(self, quantidade: int) -> list[OrdemSintetica]:
        ordens: list[OrdemSintetica] = []
        for _ in range(quantidade):
            modelo = self.random.choices(self.modelos, weights=self.pesos, k=1)[0]
            numero = self._proximo_numero()
            produto = f"{self.prefixo}{self.token}P{self._sequencia:04d}"
            etapas: list[EtapaSintetica] = []
            for indice, etapa in enumerate(modelo["etapas"], start=1):
                etapas.append(
                    EtapaSintetica(
                        codigo=str(indice * 10),
                        descricao=str(etapa["desc"]),
                        work_center=str(etapa["wc"]),
                        maquina=self.random.choice(list(etapa["maquinas"])),
                        activity_id=self._proxima_activity(),
                    )
                )
            etapas.append(
                EtapaSintetica(
                    codigo=TERMINAL["codigo"],
                    descricao=TERMINAL["desc"],
                    work_center=TERMINAL["wc"],
                    maquina=TERMINAL["maquina"],
                    activity_id=self._proxima_activity(),
                    final=True,
                )
            )
            ordens.append(
                OrdemSintetica(
                    numero=numero,
                    produto=produto,
                    descricao=f"SIMULACAO {modelo['nome'].upper().replace('_', ' ')}",
                    quantidade=self.random.randint(
                        int(self.config["quantidade_minima"]),
                        int(self.config["quantidade_maxima"]),
                    ),
                    roteiro=str(600 + (self._sequencia % 90)),
                    classe=str(modelo["classe"]),
                    modelo=str(modelo["nome"]),
                    etapas=etapas,
                    empresa=self.empresa,
                    filial=self.filial,
                )
            )
        return ordens


class ClienteIngestao:
    """Envia a ProductionOrder pelo receptor SOAP da própria API TESTE."""

    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{SOAP_ACTION}"',
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ingerir(self, ordem: OrdemSintetica, gerado_em: datetime) -> dict:
        xml = montar_production_order(ordem, gerado_em)
        envelope = montar_envelope(xml)
        try:
            resposta = await self._client.post(SOAP_PATH, content=envelope.encode("utf-8"))
        except httpx.HTTPError as exc:
            return {"ok": False, "op": ordem.numero, "erro": f"{type(exc).__name__}: {exc}"}
        corpo = resposta.text
        sucesso = resposta.status_code == 200 and "<Status>OK</Status>" in corpo.replace(
            "&lt;", "<"
        ).replace("&gt;", ">")
        return {
            "ok": sucesso,
            "op": ordem.numero,
            "modelo": ordem.modelo,
            "classe": ordem.classe,
            "quantidade": ordem.quantidade,
            "status_http": resposta.status_code,
            "fault": None if sucesso else corpo[:600],
        }
