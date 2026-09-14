# GESTORPECASPO — endpoint Protheus para OP sob demanda

Fonte publicado e homologado no TOTVS TESTE. Um único fonte, escopo mínimo.

**Fonte:** [`fontes/10-PCP/GPOPSYNC.prw`](../fontes/10-PCP/GPOPSYNC.prw) · **Release alvo:** 12.1.2510 · **Ambiente:** TOTVS TESTE `CSED4J_DEV`

Revisado em 02/09/2026 contra o repositório corporativo `protheus-gts0125`:
`END WSRESTFUL`, `WSMETHOD … WSRESTFUL`, `::SetContentType/::SetStatus/::SetResponse`,
`SetRestFault` e o padrão de ambiente `fGetEmp`/`fGoEmp`/`fRestEmp`.
O fonte já está em `fontes/10-PCP/`, espelhando o caminho do repositório GTS
(`Fontes/10-PCP/GPOPSYNC.prw`).

**Estado real em 03/09/2026:** a correção foi recompilada/aplicada em
`CSED4J_DEV`. `GESTORPECASPO`, autenticação Basic, dispatch POST, parsing JSON,
contexto SM0/SC2 e `MATI650` inline estão comprovados. OP ausente retorna
404/`notFound`; OPs reais de `010001` e `010004` retornam HTTP 200, XML 2.004 e
UniqueID correto. A Etapa 7B consumiu esse transporte no Gestor com a OP
`00615903001`. Não alterar novamente o GPOPSYNC sem fato novo.

## Para que serve

Quando um operador digita no Gestor de Peças uma OP que ainda não existe lá, o
Gestor pede essa OP ao Protheus e a carrega sozinho. O operador não abre o
PCPA109 nem precisa saber se a OP já foi sincronizada antes.

## O que o fonte faz (e o que não faz)

É um **adaptador**. Ele reaproveita a montagem oficial já usada pela
Sincronização do PCPA111 e devolve o XML por HTTP:

```text
PCPA111.prw::sincOP()        posiciona SC2 → mata650PPI(,,.T.,.T.,.F.,.F.)
mata650.prx::mata650PPI()    → PCPa650PPI()
pcpxfun.prx::PCPa650PPI()    define lRunPPI / cPonteiro / INCLUI / ALTERA e chama
                                aRetXML := MATI650("", TRANS_SEND, EAI_MESSAGE_BUSINESS, "2.004")
                                aRetXML[2] := EncodeUTF8(aRetXML[2])
                             e só DEPOIS transporta com PCPWebsPPI()
MATI650.prw::MATI650()       monta e RETORNA o XML em memória (aRet[2])
```

Como `MATI650` devolve o XML **em memória**, a montagem é separável do
transporte. O endpoint chama `MATI650` diretamente e responde o XML (modo
`inline`), sem passar pelo `PCPWebsPPI` e sem os efeitos colaterais do
`PCPa650PPI` (filtro SOE, gravação de `C2_ROTEIRO` quando vazio, geração de
pendência e POST no `PcfIntegService`).

Não faz: montar XML próprio, ler SC2/SG2/SHY para reconstruir a mensagem,
inventar roteiro/`ActivityDescription`/recurso, gravar em SC2/SG2/SH6/SD3,
apontar produção, encerrar OP ou movimentar estoque. O trecho `TRANS_SEND` do
`MATI650` é montagem pura — não há `RecLock`, `MsUnLock`, `dbDelete` nem
transação.

Nenhum fonte padrão TOTVS é alterado.

## Contrato HTTP

### Requisição

```http
POST /rest/GESTORPECASPO/gestorpecas/v1/production-order
Content-Type: application/json
Authorization: Basic <credencial REST do ambiente>

{"companyId": "01", "branchId": "010004", "number": "1079689C001"}
```

`number` é a OP completa `C2_NUM + C2_ITEM + C2_SEQUEN`. Pode ser alfanumérica.
O fonte não converte para número, não remove zeros, não altera a caixa e não
divide o código por tamanho inventado — o tamanho vem do dicionário
(`GetSx3Cache("C2_NUM"/"C2_ITEM"/"C2_SEQUEN", "X3_TAMANHO")`).

### Respostas

| HTTP | Content-Type | Corpo |
| --- | --- | --- |
| 200 | `text/xml; charset=utf-8` | `<?xml …?><TOTVSMessage …>` gerado pelo Protheus |
| 400 | `application/json` | `SetRestFault` — corpo JSON inválido, `number`/`branchId` ausentes, `number` maior que o dicionário, ou filial inexistente em SM0 |
| 404 | `application/json` | `{"status":"notFound"}` |
| 409 | `application/json` | `SetRestFault` — empresa diferente da publicação |
| 500 | `application/json` | `SetRestFault` — falha inesperada, sem stack |

O **404 não usa `SetRestFault`**: ausência de OP é resposta funcional normal, não
falha. Os demais são falhas de verdade e seguem o idioma GTS (`SetRestFault` +
`Return .F.`). O Gestor decide pelo status HTTP e também aceita o corpo
`{"status":"notFound"}` — funciona nos dois casos.

401/403 são produzidos pelo próprio framework REST quando a credencial falta ou
não está liberada. Nenhuma resposta devolve stack: o `ErrorBlock` é local ao
fonte (`GPOPCatch`) e escreve descrição e pilha apenas no `ConOut` do servidor.
Deliberadamente **não** usamos `wspcpexecp` do `WSPCP.prw`: embora seja uma
`Function` pública do RPO padrão e acessível, é interna ao fonte TOTVS e chama
`disarmTransaction()`, que aqui não faz sentido — não queremos uma dependência
que só apareceria em runtime.

## Empresa e filial

Segue o padrão corporativo GTS (`GTSxFUN.PRW` / `WS_GTS_SC7.prw`), reimplementado
localmente como `GPOPGetEmp` / `GPOPGoEmp` / `GPOPRestEmp` — **sem depender de
`U_fGoEmp`**, que vive em `Fontes/Não Compilar - Produção` e cuja presença no RPO
não é garantida.

```text
GPOPGetEmp()  guarda { SM0->(Recno()), cFilAnt, cNumEmp }
GPOPGoEmp()   SM0->(dbSeek(SubStr(cEmp,1,2)+cFil)) ; cFilAnt := cFil
              cNumEmp := SM0->M0_CODIGO + SM0->M0_CODFIL
GPOPRestEmp() SM0->(dbGoTo(...)) ; cFilAnt := ... ; cNumEmp := ...
```

- **Filial:** vem de `branchId` em cada requisição. Além de `cFilAnt`, o fonte
  posiciona **SM0** e ajusta **`cNumEmp`** — é isso que faz `xFilial("SC2")`,
  `MATI650` e `completXml` enxergarem `01/010004`. A restauração acontece sempre,
  inclusive em erro. `cFilAnt`/`cNumEmp` são por thread e cada requisição REST
  roda na sua, então filiais diferentes em paralelo não vazam contexto.
- Uma diferença deliberada em relação ao helper corporativo: `GPOPGoEmp`
  **valida** o `dbSeek`. Filial inexistente em SM0 → **400**, em vez de seguir
  com contexto inválido.
- **Empresa:** o serviço atende a empresa do ambiente publicado. Um `companyId`
  diferente recebe **409**, em vez de devolver dados da empresa errada. Trocar
  de empresa dentro da thread HTTP exigiria reabrir dicionário e tabelas, e não
  seria seguro sob concorrência.

Isso resolve a limitação dos web services padrão, que ficam presos à
empresa/filial da publicação (`01/010001`).

## Concorrência

Todo o estado é local/`Private` da requisição: OP, filial e XML nunca ficam em
variável global mutável. Duas requisições simultâneas — OPs diferentes ou a
mesma OP — são independentes. O Protheus não depende da arbitragem que o Gestor
faz no PostgreSQL.

## Compilação e publicação

1. Copiar `fontes/10-PCP/GPOPSYNC.prw` para `Fontes/10-PCP/` do repositório GTS
   (mesmo caminho relativo).
2. Compilar no RPO customizado do ambiente **TESTE** (`CSED4J_DEV`) pelo
   TDS/VSCode. Includes usados: `TOTVS.CH`, `RestFul.ch`, `FWADAPTEREAI.CH` —
   os três já existem em `Include/` do repositório GTS.
3. Garantir que o serviço REST esteja habilitado no `appserver.ini` e que a
   raiz `/rest/` já esteja publicada (hoje já está, na porta **1467**).
4. Reiniciar/recarregar o serviço REST para que a rota apareça.
5. Conferir o registro em `https://<host>:1467/rest/` — deve aparecer
   `GESTORPECASPO` com `POST /gestorpecas/v1/production-order`; a URL efetiva é
   `/rest/GESTORPECASPO/gestorpecas/v1/production-order`.
6. Liberar o usuário técnico REST para o serviço, se o ambiente exigir
   liberação por usuário.

Nada de credencial no fonte. A autenticação é a do framework REST do ambiente —
a mesma já comprovada na porta 1467.

O procedimento acima fica como runbook de republicação. A publicação corrigida
e a execução do método estão comprovadas no TESTE.

## Teste rápido de diagnóstico

OP existente (troque host, OP e credencial):

```bash
curl -k -u "USUARIO:SENHA" -X POST "https://gtsdo143182.protheus.cloudtotvs.com.br:1467/rest/GESTORPECASPO/gestorpecas/v1/production-order" -H "Content-Type: application/json" -d "{\"companyId\":\"01\",\"branchId\":\"010004\",\"number\":\"1079689C001\"}"
```

OP inexistente — deve responder `404` com `{"status":"notFound"}`:

```bash
curl -k -u "USUARIO:SENHA" -X POST "https://gtsdo143182.protheus.cloudtotvs.com.br:1467/rest/GESTORPECASPO/gestorpecas/v1/production-order" -H "Content-Type: application/json" -d "{\"companyId\":\"01\",\"branchId\":\"010004\",\"number\":\"ZZ00000ZZ99\"}"
```

PowerShell:

```powershell
$c = Get-Credential; Invoke-WebRequest -SkipCertificateCheck -Method POST -Credential $c -Uri "https://gtsdo143182.protheus.cloudtotvs.com.br:1467/rest/GESTORPECASPO/gestorpecas/v1/production-order" -ContentType "application/json" -Body '{"companyId":"01","branchId":"010004","number":"1079689C001"}'
```

## Critérios de homologação

1. `200` com `Content-Type` XML e corpo iniciando em `<?xml`.
2. `MessageInformation/Transaction` = `ProductionOrder`, `version` = `2.004`,
   `Type` = `BusinessMessage`, `SourceApplication` = `SIGAPCP`.
3. `CompanyId` = `01` e `BranchId` = **`010004`** (a filial pedida, não a da
   publicação).
4. `BusinessContent/Number` igual à OP enviada, preservando letras e zeros.
5. `ProductionOrderUniqueID` = `01|010004|<Number>`.
6. `ItemCode` e `ItemDescription` preenchidos.
7. `ListOfActivityOrders` com as operações, cada uma com `ActivityCode`,
   `ActivityDescription`, `WorkCenterCode` e `MachineCode`.
8. Para uma OP com etapa final, aparece `99 / FINALIZADA / ALMOX4` exatamente
   como o PCPA111 envia hoje. A classificação de marco terminal é do Gestor;
   o endpoint apenas entrega o ProductionOrder oficial.
9. OP inexistente → `404` `{"status":"notFound"}`, sem criar OP e sem SC2.
10. Antes e depois da chamada, a OP no Protheus permanece inalterada:
    `C2_QUJE`, `C2_DATRF`, situação/legenda e SH6/SD3 idênticos.

## Configuração atual do Gestor

O `.env` do Gestor TESTE usa:

```ini
GESTOR_TOTVS_OP_PULL_ENDPOINT=https://gtsdo143182.protheus.cloudtotvs.com.br:1467/rest/GESTORPECASPO/gestorpecas/v1/production-order
GESTOR_TOTVS_OP_PULL_MODE=inline
GESTOR_TOTVS_OP_PULL_COMPANY_ID=01
GESTOR_TOTVS_OP_PULL_BRANCH_ID=010004
GESTOR_TOTVS_OP_PULL_USERNAME=<usuario REST>
GESTOR_TOTVS_OP_PULL_PASSWORD=<senha>
```

Para reconciliar a homologação ponta a ponta sem repetir uma OP já importada:

```bash
.venv/Scripts/python.exe scripts/homologar_totvs_e2e_etapa7b.py --inspect-existing-main --verify-matrix
```
