# Cadastro de recursos e postos do operador

**Etapa 4C — saneamento.** Atualizado em 31/08/2026, banco `gestor_pecas_test`.

## 1. Como a identidade de um recurso é decidida

Existe **um único mapa** para todo o produto, em `app/core/resource_mapping.py`.
Ingestão TOTVS, fila, Tela do Operador e relatórios consomem o mesmo módulo.

```text
codigo_recurso do roteiro
  → canonical_resource_code()      identidade canônica (resolve alias oficial)
  → station_resource_code()        o código que o posto físico representa
  → sector_serves_resource()       pertencimento cadastral (Pintura/Solda/Montagem)
  → station_matches_route()        decisão final de elegibilidade
```

Duas famílias de setor, com regras diferentes e deliberadas:

| Família | Setores | Regra |
| --- | --- | --- |
| Posto-máquina | Corte, Dobra, Usinagem, Serra | igualdade exata entre o recurso do roteiro e a máquina do posto |
| Posto-setor | Pintura, Solda, Montagem | qualquer recurso com `tipo_setor` do setor é apontável |

**O código do roteiro nunca é reescrito.** O alias e o mapa de postos servem
para *comparar* e *exibir*. O apontamento grava `codigo_recurso` exatamente como
veio (`ROBO P` continua `ROBO P`, não vira `SOLDA4`; `PREP` não vira `PINT.L`).

## 2. Aliases oficiais

Alias é decisão registrada da Manufatura, não semelhança de nome. A lista é
curta de propósito:

| Código recebido | Identidade canônica | Origem |
| --- | --- | --- |
| `LASER` | `LASER1` | decisão funcional/Manufatura de 27/08/2026 |

Até a 4C esse alias existia **apenas no adaptador TOTVS**. A ingestão aceitava
`LASER`, a Tela do Operador não — o mesmo recurso tinha duas verdades. Agora
vive no núcleo e os dois lados consomem a mesma tabela.

Associação oficial de setor para recurso sem `tipo_setor` cadastrado:

| Recurso | Setor | Origem |
| --- | --- | --- |
| `JATO` | Pintura | decisão da Manufatura (Etapa 3) |

## 3. Serra — relação apurada

O cadastro tem seis códigos `SERRA*`; nem todos são máquina real.

| Código | Nome no cadastro | Fonte | Posto | Situação |
| --- | --- | --- | --- | --- |
| `SERRA1` | SERRA STARRET **S4220** | PC Factory D0021 | `S4220` | máquina real, mapeada |
| `SERRA2` | SERRA STRONG **SFHA10** | PC Factory D0021 | `SFHA-10` | máquina real, mapeada |
| `SERRA3` | SERRA **FRANHO** RF-420 | PC Factory D0021 | `SFG-330` | máquina real, mapeada na 4C |
| `SERRA5` | SERRA STRONG SFDC13 | PC Factory D0021 | — | máquina real **sem posto** |
| `SERRA4` | `SERRA4` | `planilha_teste_roteiro` | — | fictícia, massa de teste |
| `SERRA6` | `SERRA6` | `planilha_teste_roteiro` | — | fictícia, massa de teste |

**S4220 → SERRA1 e SFHA-10 → SERRA2** já estavam mapeados e ficaram provados: o
modelo aparece dentro do próprio nome cadastral.

**SFG-330 → SERRA3** foi a correção da 4C. A prova é composta:

1. o painel de chão de fábrica lista exatamente três serras em produção —
   `SERRA1/0001`, `SERRA2/0001`, `SERRA3/0001`;
2. a Tela do Operador tem exatamente três postos de Serra;
3. dois pares já estavam fechados pelo modelo no nome;
4. a foto oficial do posto `SFG-330` mostra uma máquina da marca **FRANHO**, e
   `SERRA3` é a única Franho do cadastro.

O modelo não bate ao pé da letra (`SFG 330` na foto, `RF-420` no cadastro), então
este é o único par de Serra apoiado em **marca + eliminação** em vez de igualdade
de modelo. Está registrado como tal no código e na lista de confirmação.

**SERRA4 e SERRA6 não são gap de cadastro.** São recursos inventados por uma
planilha de teste e usados só por OPs fictícias (`TEST-AP-*`, `FICOPR*`).
Nenhuma OP do TOTVS depende delas. A Etapa 4B as reportou como falha cadastral;
a 4C corrige esse diagnóstico. Elas continuam recusadas nos postos — o que é o
comportamento certo, porque não existem no chão de fábrica.

O histórico de apontamentos feitos nesses postos foi preservado. Os eventos
antigos já registram `recurso_divergente = true`, com o código do roteiro e o
posto apontado lado a lado.

## 4. Duplicidades

**Consolidadas (4 pares).** O PC Factory exportou o mesmo recurso duas vezes com
capitalização diferente — 18/08 em caixa mista, 20/08 em caixa alta. Nome
idêntico, zero uso nos dois lados:

| Mantido | Desativado | Nome |
| --- | --- | --- |
| `SCCGMM` | `SCCGmm` | SOLD.CABECALHO UPGRAIN |
| `SCGM8` | `SCGm8` | SOLD.TANQUE |
| `SCLCGM` | `SCLCGm` | SOL.CHAPAS LATERAIS |
| `SSEDCGM` | `SSEDCGm` | SOL.SUPORTE EIXO DIANTEIRO |

A variante antiga foi **desativada, nunca apagada**: continua auditável e some
das leituras que filtram `habilitado`. O Andon deixou de tratá-las como alias
ambíguo — antes recusava atribuir estado a esses códigos por ambiguidade.

**Causa-raiz fechada.** `publicar_recursos_pcfactory` passou a resolver o código
recebido contra a linha existente ignorando caixa, em vez de criar uma segunda
linha. Uma reimportação do PC Factory não recria a duplicidade.

**Não são duplicidade.** Recursos com o mesmo *nome* e códigos distintos
(`MONTAGEM ADESIVOS` em `CG.ADE`/`CS.ADE`/`DC.ADE`/`NT.ADE`/`PN.ADE`/`SM.ADE`,
`TESTE PROD/LUBRIF` em cinco códigos, etc.) são postos de linhas de produto
diferentes. Consolidá-los apagaria informação real.

**Colisão entre código e nome — identidade vence rótulo.** Dois pares têm o
código de um recurso igual ao nome de outro:

| Código | Nome | Colide com |
| --- | --- | --- |
| `ALMOX4` | ALMOX F IV | `ALMOXF4`, cujo nome é `ALMOX4` |
| `RETRABALHO` | RETRABALHO | `RETR`, cujo nome também é RETRABALHO |

O Andon indexava código e nome com o mesmo peso, então a colisão anulava os
dois aliases: a máquina aparecia **duas vezes** — uma pelo catálogo e outra
como recurso sem cadastro. Como o código cadastral é a identidade do recurso,
ele passou a vencer o nome de qualquer outro registro. O nome continua
resolvendo apenas quando não colide, e nome repetido entre códigos distintos
segue ambíguo — não escolhe vencedor por semelhança.

Efeito medido: o Andon passou de 380 para 378 cartões, exatamente o número de
recursos habilitados no catálogo, sem nenhum recurso duplicado ou perdido.

## 5. Recursos sem `tipo_setor`

São **313 de 382**. Cruzando com roteiro, apontamento e estado físico:

```text
em roteiro ........... 0
com apontamento ...... 0
com estado físico .... 0
```

Nenhum tem qualquer uso, e o próprio arquivo de origem do PC Factory
(`docs/pcfactory_recursos_sem_pessoas.csv`) só traz `codigo;nome;fonte` — não
existe coluna de setor para importar. Não há evidência a aplicar.

Classificar por nome (`SOLD.*` → Solda) seria exatamente a inferência por
semelhança que a regra canônica proíbe, e criaria elegibilidade real em Solda,
que é setor dono do recurso. **Permanecem sem setor**, e a classificação é
decisão da Manufatura.

`tipo_setor` já cadastrado sobrevive a reimportação (`COALESCE` no upsert): uma
carga sem a coluna não apaga a classificação existente.

## 6. Matriz de elegibilidade

Gerada por `scripts/sanear_recursos.py --matriz` e travada por
`tests/test_stage4c_resource_registry.py`.

69 recursos setorizados: **64 elegíveis, 5 sem posto, 0 vazamentos** entre
setores.

| Setor | Recursos | Postos | Observação |
| --- | --- | --- | --- |
| Corte | `PLASMA`, `LASER1`, `LASER` | Plasma TerraBlade 4, Laser Ensis 3015 | `LASER` alcança o mesmo posto pelo alias oficial |
| Dobra | `DOBRA1`, `DOBRA2`, `DOBRA3` | Gasparini, 2204, 1303 | completo |
| Usinagem | 7 recursos | 5 postos | `PMCV` e `ROSQU` sem posto |
| Serra | 6 códigos | S4220, SFHA-10, SFG-330 | `SERRA5` sem posto; `SERRA4`/`SERRA6` fictícias |
| Pintura | 6 recursos | Pintura | todos elegíveis por pertencimento |
| Solda | 44 recursos | Estação 1–10 | todos elegíveis por pertencimento |
| Montagem | 0 | — | sem recurso cadastrado |

Não elegíveis, com o motivo:

| Recurso | Setor | Motivo |
| --- | --- | --- |
| `PMCV` | Usinagem | máquina real sem posto na tela; sem uso em roteiro |
| `ROSQU` | Usinagem | máquina real sem posto na tela; sem uso em roteiro |
| `SERRA5` | Serra | máquina real sem posto na tela; sem uso em roteiro |
| `SERRA4` | Serra | recurso fictício de massa de teste |
| `SERRA6` | Serra | recurso fictício de massa de teste |

## 7. Pendências para a Manufatura

Curtas e objetivas — só o que não dá para provar pelos dados:

1. **`SFG-330` é mesmo a `SERRA3` (Franho RF-420)?** Implementado por marca e
   eliminação. Se o posto for outra máquina, é uma linha em
   `STATION_RESOURCE_CODES`.
2. **`SERRA5` (Strong SFDC13) tem posto?** Existe no cadastro e não aparece no
   painel de produção. Ativa sem posto, desativada, ou fora de uso?
3. **`PMCV` e `ROSQU` viram posto de Usinagem?** São recursos reais sem posto e
   sem roteiro. Há ícones `MCV 800.svg` e `Rosqueadeira.svg` no acervo visual,
   o que sugere postos planejados e nunca ligados.
4. **Classificação dos 313 recursos sem `tipo_setor`.** Decisão em bloco, por
   setor. Sem isso eles não entram em nenhum fluxo — o que hoje é inofensivo,
   porque nenhum é usado.
5. **`LASER` e `LASER1` continuam dois registros.** O alias já os trata como a
   mesma máquina. Aposentar `LASER` na origem depende de retirar as 28 OPs
   fictícias que o referenciam.

## 8. Como reproduzir

```bash
python scripts/sanear_recursos.py --dry-run    # classifica e relata
python scripts/sanear_recursos.py              # aplica o comprovável
python scripts/sanear_recursos.py --matriz     # RECURSO → SETOR → POSTO → ELEGÍVEL
```

```bash
.\.venv\Scripts\python.exe -m unittest tests.test_stage4c_resource_registry -v
```

O script só opera em banco de teste, nunca apaga linha e nunca toca em
apontamento, evento ou histórico. Consolidação exige mesmo código ignorando
caixa, mesmo nome e zero uso nas duas variantes.
