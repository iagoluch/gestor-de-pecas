# Estado da Wave 4 — 2026-09-08 (fechamento técnico)

Os dois bloqueios estão **fechados** e todas as suítes estão verdes. O banco REAL
continua intocado. A próxima decisão é do usuário, não do código.

## SUÍTES — TODAS VERDES

| Suíte | Comando | Resultado |
|---|---|---|
| Python completa | `.venv\Scripts\python.exe -m unittest discover` | **690 testes, OK (skipped=1)** — 312,9 s |
| Python completa (2ª execução, estabilidade) | idem | **690 testes, OK (skipped=1)** — 242,2 s |
| Cadeia de migrations PostgreSQL | `-m unittest tests.test_migration_chain_11_19` | **8/8 OK** |
| Web | `npm test` em `web/` | **80/80** em 7 arquivos |
| TypeScript + build | `npm run build` em `web/` | `tsc -b` OK; Vite **389 módulos** |
| Imports do produto | 12 módulos do `AGENTS.md` + `andon` + `quality` | 12/12 OK |

O único `skip` é declarado e legítimo: "O banco TESTE ativo não possui fatos na
janela histórica de julho/2026". Não mascara falha.

Duas execuções completas seguidas descartam a intermitência sob carga que já
tinha aparecido na Wave 3 (corrida do on-demand TOTVS).

## BANCO REAL — INTOCADO (verificado read-only ao final)

```
gestor_pecas:      schema=11  applied_at=2026-08-19 19:39:31  col_mig25=0  check25=ausente
gestor_pecas_test: schema=25  applied_at=2026-09-08 16:57:53  col_mig25=1  check25=presente
```

`ck_apontamentos_quantidade_atendida_planejada` no TESTE, íntegra e **não afrouxada**:

```sql
CHECK (((quantidade_boa + quantidade_refugo) <= quantidade)) NOT VALID
```

Nenhum backup, preflight ou promoção foi executado. A promoção 11→25 continua
condicionada a: backup restaurável validado + preflight + **OK explícito do usuário**.

## BLOQUEIO 1 — Andon quebrado no PostgreSQL — RESOLVIDO

Causa raiz: `listar_cortes_ativos_andon` lia `sigmanest_repeat_id` de
`apontamentos_corte`, onde a coluna nunca existiu. Contra PostgreSQL levantava
`UndefinedColumn` e derrubava o snapshot inteiro do Andon. Os fakes escondiam o
defeito porque devolviam o campo direto do apontamento.

**Antes** (`app/database/database.py`):

```sql
SELECT ..., corte.sigmanest_repeat_id, ...
FROM apontamentos_corte corte
WHERE corte.status = 'Em processo'
```

**Depois** (`app/database/database.py`, `listar_cortes_ativos_andon`):

```sql
SELECT ..., plano.sigmanest_repeat_id AS repeticao, ...
FROM apontamentos_corte corte
LEFT JOIN catalogo_sigmanest_planos_corte plano
  ON plano.plano_hash = corte.plano_hash
WHERE corte.status = 'Em processo'
```

A procedência corporativa termina na persistência: o contrato de saída é
`repeticao`, o mesmo vocabulário neutro de `listar_fila_destaque`.
`mes/services/andon.py` passou a ler `cut.get("repeticao")` e voltou a respeitar
o guard `test_execucao_nao_conhece_origem_corporativa`. `tests/fakes.py` foi
corrigido para espelhar o JOIN real, e não o campo inexistente.

Nenhum `try/except` foi adicionado em `andon.py`: com a consulta correta não há o
que engolir, e silenciar erro contraria o `AGENTS.md`.

**Frontend:** nada a mudar. O Andon consome
`resource.state.activity_description` (`web/src/types/andon.ts`,
`web/src/pages/AndonPage.tsx`); o campo e a string renderizada não mudaram.

**Provas:**
- `tests/test_database_professionalization.py::test_andon_descreve_o_corte_ativo_com_a_repeticao_vinda_do_catalogo`
  — teste novo, contra PostgreSQL real, cobre a consulta e o texto final do card.
- Sonda direta em `gestor_pecas_test`: `listar_cortes_ativos_andon`,
  `listar_destaques_ativos_andon`, `listar_fila_destaque` e
  `listar_recursos_pcfactory` executam sem `UndefinedColumn`.
- `08_andon_geral.png` capturado após a correção.

## BLOQUEIO 2 — "teto = planejado" — CONCLUÍDO

Regra vigente, documentada em `docs/REGRAS_MANUFATURA_CANONICAS.md` e com fonte
única em `mes/domain/manufacturing_rules.py`:

- planejado é **teto** de `boas + refugo`;
- saldo é `planejado - (boas + refugo)`;
- retrabalho **não** entra na soma e é o que mantém a operação aberta;
- enquanto há saldo, a finalização é **parcial** e devolve a operação à **fila**,
  exigindo novo `Início` antes do fechamento.

A regra é aplicada em três camadas, sem fórmula duplicada — todas chamam
`ManufacturingRules`:

1. serviço — `mes/services/operator_flow.py` (`quantidade_inconsistente`);
2. persistência — `app/database/database.py` (`ValueError` antes do commit);
3. banco — a CHECK da migration 25.

Nenhuma dessas camadas foi enfraquecida. Os testes/fixtures legados que
esperavam `boas + refugo > planejado` foram atualizados para o ciclo real
(parcial → fila → reabertura → fechamento). A cobertura ficou **mais forte**, não
mais frouxa: `tests/test_web_api.py` passou a exigir HTTP 409 na tentativa de
estourar o teto, e `tests/test_totvs_operator_queue.py` passou a validar a
sequência de eventos incluindo `parcial`.

### Correção de produção associada (necessária, não cosmética)

`mes/services/quality.py`, `_iniciar_operacao_canonica`: com a regra nova, uma
inspeção parcial devolve a operação `INSPECAO` à **fila**. O código reaproveitava
qualquer apontamento "ativo" como se estivesse em execução, e a reinspeção depois
tentava `fila → finalizado`, transição que a máquina de estados canônica proíbe
(`ALLOWED_TRANSITIONS[QUEUED]` não contém `FINISHED`). Agora quem decide é o
estado, via `operator_state_from_status`: só um apontamento fora de `QUEUED`
dispensa o `Início`. Um status desconhecido mantém o comportamento anterior.
Coberto por `tests/test_quality_inspection.py`
(`test_cotas_e_rnc_nao_geram_outbound_e_a_conclusao_usa_o_fluxo_canonico`), que
também prova que continua existindo **um único** apontamento da operação.

### `scripts/homologar_totvs_e2e_etapa7a.py`

Alteração legítima e obrigatória. A OP real tem `ProductionQuantity = 2`; com o
teto novo, o antigo `Finalizado(boas=1, refugo=1)` fecharia a operação de uma vez
e a homologação perderia a evidência do apontamento **parcial** — um dos quatro
eventos outbound que ela existe para produzir. A sequência passou a ser
`Finalizado(boas=0, refugo=1)` → `Início` → `Finalizado(boas=1)`. Nenhum número da
fixture corporativa foi alterado, e o teste automatizado continua provando os 4
eventos, a idempotência, o retry, o lease e a entrega com ACK controlado.

## PENDÊNCIAS

- **Inspeção visual do Andon com dados PostgreSQL:** não executada. O preview
  isolado da porta 8010 (`gestor-preview-visual`) trava o processo e ficou
  proibido. `08_andon_geral.png` existe e é posterior à correção, mas foi gerado
  com o banco fake do preview: naquele cenário não há `apontamentos_corte` ativo,
  então a linha de contexto `Tarefa … • Programa … • Chapa … · repetição N` não
  aparece na captura. Esse texto está provado por teste contra PostgreSQL, não
  visualmente.
- **`listar_destaques_ativos_andon` só tem cobertura por fake**
  (`tests/test_andon_redesign.py`). É a mesma classe de risco do Bloqueio 1. A
  consulta foi executada com sucesso contra `gestor_pecas_test`, então não há
  defeito hoje; falta um teste PostgreSQL que impeça a regressão.
- **Schemas efêmeros órfãos em `gestor_pecas_test`** (execuções interrompidas):
  `gestor_etapa7c_*` (4, com 48 tabelas cada) e `gestor_ondemand_test_*` (1).
  Inofensivos; não foram removidos porque `DROP SCHEMA` é destrutivo e não foi
  pedido.
- **`.env` do workspace contém credenciais em claro** (senha do PostgreSQL e
  `GROQ_API_KEY`). Não entra em artefato entregue; vale rotacionar se já foi
  compartilhado.
- Homologação manual operacional sobre `gestor_pecas_test`: **não iniciada**.

## ITENS BLOQUEADOS POR DADO (manter como estão — não inventar)

- Datas reais de criação/atualização de T3528/T3539 (SigmaNEST sem registros comprobatórios).
- Associação dos logins reais às 10 estações físicas de Solda.

## PROIBIDO

Promover/backup/migration no banco REAL antes da hora; iniciar cenário de
fábrica; inventar datas SigmaNEST; afrouxar a CHECK da migration 25; subir o
preview visual da porta 8010.

## PRÓXIMO PASSO

Decisão do usuário. Nada mais é executável automaticamente sem autorização
explícita: o caminho restante é backup `pg_dump` de `gestor_pecas` → validação do
restore → preflight 11→25 → OK final do usuário → promoção.
