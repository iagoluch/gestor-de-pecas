# ETAPA 4B — Simulação integral da fábrica

**Ambiente:** `gestor_pecas_test`, schema 17. Banco REAL `gestor_pecas` intocado.
SigmaNEST em modo **somente leitura**. Porta 8000 reservada à integração TOTVS;
porta 8001 dedicada à simulação e ao acompanhamento visual.

**Relógio:** virtual e exclusivo da simulação (`ApplicationClock`), ancorado em
`time.monotonic` e acelerado. Windows e PostgreSQL **não** tiveram seus relógios
alterados. Fora do modo de simulação o relógio apenas delega para
`datetime.now`.

---

## 1. O que a simulação precisava provar

A Etapa 4A fechou a consistência entre execução e leitura gerencial com a
fábrica parada. A 4B exige a mesma consistência com a fábrica **operando**:
vários setores ao mesmo tempo, tempo passando de verdade, turno terminando,
dia virando e uma OP corporativa atravessando tudo isso.

---

## 2. Como as ações chegaram ao domínio

Nenhum evento produtivo foi inserido diretamente no banco. Dois caminhos foram
usados, ambos canônicos:

| Caminho | Onde | O que exercita |
| --- | --- | --- |
| HTTP completo | `factory_shift_simulator.py` | login, CSRF, roteadores, serviços, máquina de estados |
| Serviços canônicos | `totvs_h2_continuation.py` | `OperatorFlowService` → máquina de estados → repositórios |

O segundo caminho existe porque a continuação foi executada sem sessão HTTP
disponível. Ele **não** é um bypass: usa o mesmo serviço que o roteador usa,
com a mesma máquina de estados e as mesmas transações. O que ele não exercita é
apenas a camada de autenticação, já provada pelo primeiro caminho.

As interrupções automáticas (intervalos, 17:30 e 21:30) **não** foram
produzidas por nenhum dos dois scripts. Elas vêm do laço
`_simulation_shift_boundary_loop` do backend na porta 8001, que aplica
`ShiftBoundaryService.apply_due` contra o relógio virtual. Os scripts apenas
**esperam e observam** o resultado.

---

## 3. Continuidade temporal

### 3.1 Limites oficiais

`ManufacturingRules` define os limites homologados:

```text
Jornada oficial   08:00 – 17:30
H1 (hora extra)   06:00 – 08:00
H2 (hora extra)   17:30 – 21:30
Corte automático  17:30 e 21:30
Intervalos        12:10–12:52 (Almoço) e 15:30–15:45 (Café)
```

A interrupção é **persistida no horário oficial**, não no instante em que o
temporizador a detecta. O repositório garante idempotência: o mesmo limite não
é aplicado duas vezes ao mesmo apontamento.

### 3.2 H2 com recurso ativo e corte às 21:30

Dois cenários independentes comprovam o comportamento, ambos com o recurso
realmente em Produção ao atravessar a janela:

**Usinagem / Eurostec (`CNC-02`), OP `TEST-AP-T05-N02`**

```text
01/09 14:01:53  setup
01/09 14:02:58  produção
01/09 17:30:00  fora_turno   ← corte automático das 17:30 (SISTEMA)
01/09 17:42:29  produção     ← retomada manual dentro de H2
01/09 17:42:53  parada       0015 - PEÇA NÃO CONFORME
01/09 17:44:28  produção     ← ATIVO em H2 por 3h45min
01/09 21:30:00  fora_turno   ← corte automático das 21:30 (SISTEMA)
02/09 06:02:30  produção     ← retomada em H1, no dia seguinte
02/09 08:02:04  finalizado   22 boas + 1 refugo
```

**Solda / Estação 3 (`ROBO P`), OP TOTVS `A9717101001`**

```text
03/09 21:03:33  produção     ← início dentro de H2
03/09 21:03:36  parada       0011 - MANUTENÇÃO CORRETIVA
03/09 21:05:37  produção     ← ATIVO rumo às 21:30
03/09 21:30:00  fora_turno   ← corte automático das 21:30 (SISTEMA)
04/09 00:00     —            OP aberta atravessando a meia-noite
04/09 06:03     produção     ← retomada em H1, novo dia
04/09 06:48     finalizado
```

### 3.3 Divisão diária

O evento físico **não é fatiado** na gravação: um período `fora_turno` de
21:30 a 06:02 do dia seguinte é uma única linha em `eventos_estado_recurso`. A
divisão por dia acontece na **leitura**, recortando o segmento contra a janela
do filtro. Isso preserva a continuidade do estado e evita tanto duplicação
quanto perda de evento — verificado por ausência de sobreposição por recurso e
por conferência de que a soma diária de quantidades fecha com o total do
período.

### 3.4 Parada programada x não programada

| Origem | `automatico` | `planejado` | `tipo_interrupcao` |
| --- | --- | --- | --- |
| Intervalo (Almoço/Café) | `true` | `true` | `intervalo_programado` |
| Fim de turno (17:30/21:30) | `true` | `true` | `fim_turno` |
| Parada do operador | `false` | `false` | — |

---

## 4. OP com origem corporativa TOTVS

O catálogo de TESTE tem três OPs vindas do `ProductionOrder` do Protheus
(`totvs_source_application = SIGAPCP`):

| OP | Roteiro | Situação |
| --- | --- | --- |
| `A9716901001` | 10 CORTE/`PLASMA` → 20 USINAGEM/`CNC-01` | bloqueada pela dependência legítima de Corte |
| `A9717001001` | 10 SOLDA/`ROBO P` | **executada e finalizada** |
| `A9717101001` | 10 SOLDA/`ROBO P` | **executada e finalizada** (cenário H2/21:30) |

A cadeia completa foi percorrida:

```text
ProductionOrder (SOAP)
  → catalogo_pcp_ops + catalogo_operacoes_op   (fonte: totvs_production_order_v1)
  → fila do posto de Solda                     (elegibilidade posto ↔ setor)
  → OperatorFlowService                        (máquina de estados canônica)
  → apontamentos_operacionais
  → eventos_apontamento_operador + eventos_estado_recurso
  → eventos_quantidade_producao + historico
  → ManagementService.get_overview → Dashboard / Andon / Consulta Operacional
```

**Identidade do recurso preservada.** O apontamento guarda
`codigo_recurso = 'ROBO P'` (o recurso real do roteiro) e `maquina = 'Estação N'`
(o posto físico que o operador escolheu). Nenhum alias foi criado e `ROBO P`
não foi convertido em `SOLDA4`. A elegibilidade vem do pertencimento cadastral
(`catalogo_recursos_pcfactory.tipo_setor = 'Solda'`), conforme a correção de
Pintura/Solda da Etapa 3.

---

## 5. Andon — contrato real

O verificador anterior reprovava um snapshot correto porque procurava
`andon["resources"]` ou `andon["items"]`. **Essas chaves não existem.** O
contrato real agrupa por setor:

```json
{
  "sectors": [{"name": "Solda", "resources": [{"code": "...", "state": {...}}]}],
  "summary": {"resources": 0, "production": 0, "out_of_shift": 0, "oee": {...}},
  "resource_count": 0,
  "availability": "disponivel",
  "sources": {"physical_state": "eventos_estado_recurso"}
}
```

Somente o **verificador** foi corrigido. O Andon não foi alterado.

**O Andon não recalcula nada:** `AndonService.build_snapshot` recebe
`consulta_operacional` e `ManagementService.get_overview` prontos e apenas
reagrupa. Os KPIs do resumo são cópias diretas de `overview["kpis"]`.

**O Andon não inventa estado.** A Consulta Operacional, *apenas em modo de
simulação*, acrescenta linhas sintéticas `livre`/`aguardando` para recursos do
catálogo sem estado físico — com fonte declarada
`catalogo_recursos_pcfactory+apontamentos_operacionais`. O Andon não propaga
essas categorias: mantém `desconhecido`, porque ausência de evento não é
estado. Esse comportamento está correto e ficou travado por teste. Em produção
(`simulation_mode` desligado) as linhas sintéticas não existem.

---

## 6. Reconciliação

A reconciliação é feita por `tests/etapa4b_factory_shift/verify_stage4b.py`. O
lado **esperado** é reconstruído por SQL bruto e aritmética própria do
verificador; o lado **observado** vem dos mesmos objetos usados pelos
roteadores HTTP. O relatório completo fica em
`artifacts/final_verification.json`.

Janela fixada em **31/08 11:20 → 04/09 07:00** (relógio da simulação):
**60 de 60 verificações consistentes**.

| Grandeza | Esperado (evento bruto) | Observado (serviço) |
| --- | --- | --- |
| Peças boas | 140 | 140 |
| Refugo | 4 | 4 |
| Retrabalho | 2 | 2 |
| Setups | 3 | 3 |
| Parciais | 1 | 1 |
| Finalizações de OP | 8 | 8 |
| Finalizações de nesting | 4 | 4 |
| Paradas manuais (não programadas) | 6 | 6 |
| Interrupções programadas | 23 (10 fim de turno + 13 intervalos) | 23 |
| Retomadas | 15 | 15 |
| Linhas de histórico legível | 54 | 54 |

Tempo físico por categoria, em segundos (bruto x `ResourceStateService`):

| Categoria | Segundos |
| --- | --- |
| Produção | 127.393 |
| Fora de turno | 393.257 |
| Parada | 21.891 |
| Setup | 18.131 |
| Desconhecido | 18.379 |
| Retrabalho | 3.533 |

Indicadores, recalculados de forma independente e batendo dígito a dígito com
`mes/analytics/oee.py`:

```text
disponível  = 189.327 s      trabalhado = 149.057 s
Disponibilidade = 78,729922 %
Performance     = 14,534037 %
FTT             = 95,890411 %
OEE             = 10,972391 %
```

Fórmulas recalculadas sem reusar `mes/analytics/oee.py`:

```text
disponível = produção + setup + retrabalho + atividade_sem_op + parada + fila + desconhecido
trabalhado = produção + setup + retrabalho + atividade_sem_op
Disponibilidade = trabalhado / disponível
FTT             = boa / (boa + refugo + retrabalho)
OEE             = Disponibilidade × Performance × FTT
```

**Fora de turno é medido e fica de fora do tempo disponível.** Ele aparece em
`hours.out_of_shift_seconds` e na composição de tempo do Dashboard, mas não
entra em `available_seconds`. Consequência verificada: acrescentar horas de
`fora_turno` não altera a Disponibilidade nem o OEE.

---

## 7. Gaps de cadastro — registrados, não corrigidos

Estes gaps **não pertencem a esta etapa** e não foram mascarados. Eles exigem
decisão da Manufatura sobre o cadastro real, não código.

### 7.1 Recurso de roteiro sem posto elegível

| Setor | Recurso do roteiro | Postos do setor | OPs afetadas |
| --- | --- | --- | --- |
| Serra | `SERRA4` | `SFG-330`, `S4220`, `SFHA-10` | 12 |
| Serra | `SERRA6` | `SFG-330`, `S4220`, `SFHA-10` | 12 |
| Corte | `LASER` | `Laser Ensis 3015` (→ `LASER1`) | 28 |

Os postos de Serra representam `SERRA1`/`SERRA2` (e `SFG-330` não representa
código nenhum), enquanto o roteiro pede `SERRA4`/`SERRA6`. Serra não é setor
de posto-por-setor, então a igualdade exata é obrigatória e o bloqueio é o
comportamento **correto** para a configuração atual.

Evidência: a OP `TEST-AP-T04-N01` avançou por Dobra (`DOBRA1`, 17 boas) e
Usinagem (`CNC-02`, 17 boas) e parou na operação 40 (Serra/`SERRA4`). Os três
postos de Serra mostram fila vazia. A operação 50 (Pintura) fica pendente por
dependência da etapa anterior — não por falha de Pintura.

Nenhum alias foi criado, nenhuma equivalência por nome foi inventada e Serra
não foi convertida em posto genérico de setor.

### 7.2 Outros achados para o saneamento futuro

- **313 de 382 recursos sem `tipo_setor`** no cadastro. Para Pintura, Solda e
  Montagem isso impede a elegibilidade por pertencimento canônico.
- **4 códigos que diferem apenas por capitalização**: `SCGm8`/`SCGM8`,
  `SCLCGm`/`SCLCGM`, `SCCGmm`/`SCCGMM`, `SSEDCGm`/`SSEDCGM`. O Andon trata
  esses aliases como ambíguos e recusa atribuir estado por inferência — o que
  está certo, mas o cadastro precisa resolver a duplicidade.
- **Montagem sem recurso cadastrado.** Setor, permissões e regra canônica já
  existem; falta a Manufatura classificar os recursos reais.

---

## 8. Bugs comprovados e corrigidos

### 8.1 Tempo de nesting aberto contava tempo que ainda não passou

`listar_tempos_nesting_corte` passou a recortar a execução no fim da janela
(`as_of = fim or agora`). O recorte está certo, mas a tela envia
`fim = <data>T23:59:59` — quase sempre no futuro. Para um nesting **aberto**, o
resultado era o tempo até o fim do dia, não o tempo decorrido.

Medido: nesting iniciado há **1 s**, janela terminando 1 h à frente →
`real_segundos = 3.600`. Com o filtro diário real da Management View, um
nesting iniciado às 09:00 reportaria ~15 h de corte às 10:00. `ManagementService`
consome `real_periodo_segundos` em `cutting_real_seconds`, então a distorção
chegava aos indicadores — a mesma família de erro que a Etapa 4A corrigiu, por
outra porta.

Correção mínima: `as_of = min(fim, agora)`. O recorte de janela continua valendo
para janelas passadas; tempo futuro deixa de virar tempo produzido. Nada de
migration, regra ou dado gravado mudou. Nestings finalizados nunca foram
afetados (usam `data_fim`).

Regressão: `tests/test_execution_to_management_consistency.py` passou a exigir
que uma janela até `23:59:59` devolva a mesma duração de uma janela até agora.

### 8.2 A mesma máquina listada duas vezes na Consulta Operacional

Em modo de simulação, `consulta_operacional` completa a lista com recursos do
catálogo que não têm estado físico. A presença era testada comparando o
**código técnico** do catálogo (`DOBRA1`) com o **nome do posto** gravado no
estado físico (`Gasparini`) — que nunca coincidem. Resultado: a mesma máquina
aparecia duas vezes no mesmo instante, uma com o estado real (`fora_turno`) e
outra como `livre`, e `count` vinha inflado.

Correção mínima: resolver a identidade pelo mapa canônico já existente
(`resource_display_name`) antes de decidir se o recurso já está listado. Nenhum
alias criado, nenhum `codigo_recurso` alterado. O Andon nunca foi afetado —
ele já unificava código e nome pela identidade do catálogo.

Regressão: `tests/test_stage4b_factory_shift.py::OperationalViewIdentityTests`.

### 8.3 Dublê de teste fora de sintonia com o repositório

`tests/fakes.py` não acompanhou a inclusão do parâmetro `agora` em
`listar_fila_corte` e `listar_apontamentos_corte`, quebrando 13 testes com
`TypeError`. O dublê passou a espelhar a assinatura e a semântica canônicas: o
instante de referência vem do chamador e só cai para o relógio local quando não
é informado.

---

## 9. Observações registradas, sem correção

**Dois eventos `fora_turno` para uma única ausência física.** Um apontamento
interrompido às 17:30 e não retomado recebe um segundo evento de apontamento às
21:30, porque `listar_apontamentos_abertos_no_limite_turno` inclui o status
`Parada` (necessário para que uma parada manual anterior ao limite termine no
fim do turno). O estado físico **não** duplica: `eventos_estado_recurso` mantém
uma única linha contínua de 17:30 até a retomada. Nenhuma métrica é afetada —
o log de transições fica com uma linha a mais, e o histórico do operador exibe
duas linhas de "Fim de turno". Registrado para decisão futura.

**Calendário de TESTE cobre apenas dois dias da semana.** O calendário
`ETAPA4B_TESTE_20260831` tem turnos para `dia_semana` 0 e 1. Isso afeta apenas
`data_quality.calendar_configured`; os limites de turno vêm de
`ManufacturingRules` e continuaram funcionando nos dias não cobertos.

**Um apontamento permanece aberto ao fim da janela.** O apontamento 52
(`TEST-AP-T05-N03`, Dobra/`DOBRA1`, posto Gasparini) foi iniciado em 03/09
21:15:47 pela porta 8001 durante o acompanhamento visual — não pelos scripts
desta etapa — e recebeu o corte automático das 21:30. Ninguém o retomou, então
ele continua em `fora_turno`, que é o estado correto. Ele funciona como uma
terceira comprovação independente do limite das 21:30 com recurso ativo.

---

## 10. Como reproduzir

```bash
python tests/etapa4b_factory_shift/prepare_snapshot.py
python tests/etapa4b_factory_shift/factory_shift_simulator.py
python tests/etapa4b_factory_shift/totvs_h2_continuation.py
python tests/etapa4b_factory_shift/verify_stage4b.py
```

Testes automatizados da etapa:

```bash
.\.venv\Scripts\python.exe -m unittest tests.test_stage4b_factory_shift -v
```
