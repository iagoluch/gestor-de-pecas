# Integração TOTVS — consulta de MODELO do produto sob demanda

Data: 15/09/2026

## Objetivo

`catalogo_pcp_ops.produto_modelo` existe desde a migration 29 e alimenta a
coluna MÁQUINA/MODELO da tela `/welding-management` (Wave 6D), mas está sempre
nula: não existe mecanismo de carga. O campo fonte é `B1_ZMODELO`
(cadastro de produto, SB1), campo customizado da empresa (posição 322 no
dicionário, confirmado em `integracao_totvs_referencia/parametros_totvs/
Campos totvs banco real.json`).

O `ProductionOrder` que o `GPOPSync` já devolve (Etapa 6.2/7B, homologado) é a
OP (SC2) — não carrega campos de cadastro de produto. `B1_ZMODELO` precisa de
uma consulta separada, ao produto, não à OP.

## Rotina necessária — espelha o `GPOPSync`

Fonte pronto para compilar: [`fontes/10-PCP/GPB1MODL.prw`](../fontes/10-PCP/GPB1MODL.prw)
— `User Function GPB1Modl()`, publicação REST `gestorpecasb1`, rota
`POST /gestorpecas/v1/product-model`. Mesmo appserver/publicação do
`GPOPSync`, mesmo padrão: somente leitura, sem transação, sem side-effect em
SB1. Adicione-o ao mesmo pacote/RPO do `GPOPSYNC.prw` antes de subir ao
TOTVS Cloud — nenhum outro arquivo precisa mudar.

**Entrada** (`POST`, JSON):

```json
{"companyId": "01", "branchId": "010004", "productCode": "SSM014007071"}
```

`productCode` é o `B1_COD` completo, alfanumérico, sem trim de zeros à
esquerda além dos espaços das pontas — mesma regra já usada para `number` no
GPOPSync.

**Comportamento esperado**

1. abrir o ambiente na empresa/filial recebidas (mesmo helper local de
   empresa/filial do GPOPSync — `GPOPGoEmp`/`GPOPRestEmp` ou equivalente);
2. posicionar SB1 pela chave (filial + código do produto);
3. ler `B1_ZMODELO` do registro posicionado — não calcular, não inferir de
   outro campo;
4. devolver o valor tal como cadastrado, sem normalizar caixa/acentos (a
   camada de apresentação do Gestor já trata texto ausente).

**Saída — 200**

```json
{"productCode": "SSM014007071", "modelo": "TRC 710"}
```

Campo `modelo` pode vir vazio (`""` ou ausente) quando `B1_ZMODELO` está em
branco no cadastro — não é erro, é ausência funcional. O Gestor já sabe
representar isso (`DataAvailability.NOT_CONFIGURED`, texto "Modelo não
identificado.").

**Produto inexistente**

```text
HTTP 404, {"status": "notFound"}
```

**Restrições** (idênticas ao GPOPSync)

- não escrever em SB1;
- não expor SQL nem consulta genérica;
- autenticação por ambiente (a mesma credencial REST do GPOPSync serve);
- escopo mínimo: uma entrada, uma saída, nenhuma transação nova;
- não inventar `modelo` quando o campo estiver vazio — devolver vazio.

## Lado Gestor (quando o endpoint existir)

Consumo simétrico ao `ProtheusOnDemandRequestGateway`
(`mes/integrations/totvs/on_demand_gateway.py`): uma nova env var
(`GESTOR_TOTVS_MODEL_PULL_ENDPOINT`) e um gateway fino que só transporta e
reporta, sem decisão de negócio. O resultado grava em
`catalogo_pcp_ops.produto_modelo` do jeito que a coluna já foi desenhada —
nenhuma migration nova necessária.

Enquanto o endpoint não existir do lado TOTVS, nada muda no Gestor: a tela
continua mostrando "Modelo não identificado." — sem inventar dado, do mesmo
jeito que o pull de OP ficou parado até a Etapa 6.2 existir de verdade.

## Prova disponível para a homologação

`mata650.xml` (exportado do browse do MATA650 em 15/09/2026, filial 010004,
~1723 OPs reais) traz **368 ocorrências de "CONJUNTO SOLDADO"** com códigos de
produto reais (ex.: `SSM014007071`, `SSM014007071P`, `SSM014007072`) — massa
suficiente para testar a consulta assim que ela existir no TOTVS TESTE, sem
inventar OP nem produto.
