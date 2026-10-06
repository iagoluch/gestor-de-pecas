# Modelos livres para delegação (`scripts/nemo.sh <slug> <prompt> [modelo]`)

Medido em 05/10/2026 no repo real, gabarito oculto. **Uma amostra por modelo e tarefa** (kimi: 2 no F) — ranking provisório; reavaliar com mais dados antes de endurecer a regra.

Funcionários ativos (só quem rodou e ajudou fica no painel e no `nemo.sh`):

| Alias | Modelo | Via | F: função + testes (spec fechada) | E: bug com sintoma claro | Quando usar |
|---|---|---|---|---|---|
| `super` | nemotron-3-super-120b-a12b | NVIDIA | código 19/19, testes pegam a mutação, relatório completo, 449 s | correto, 164 s (o mais rápido) | **padrão para tarefa que escreve testes** e para correção pontual |
| `kimi` | kimi-k3 | NVIDIA | amostra 1: patch vazio (abortou após chamada negada); amostra 2: 19/19, testes pegam a mutação, 423 s | correto, 379 s | segunda via / comparação do `super`; rodar em paralelo e aceitar quem passar na verificação |
| `ultra` (padrão) | nemotron-3-ultra-free | OpenCode Zen | código 19/19, **testes vácuos** (passam com a decisão quebrada) | aceito | mapeamento "onde está" (só leitura), refatoração mecânica, constantes; maior base de testes (T1–T8, C–H) |

## Descartados (05/10/2026)

Saíram do painel e dos aliases por não renderem no fluxo diário. Para reabrir: voltar a linha do alias em `scripts/nemo.sh` (`glm) model=nvidia/z-ai/glm-5.3`, `gemma) model=nvidia/google/gemma-4-31b-it` — conferir o id na lista do provedor), acrescentar o id em `WORKERS` no `scripts/nemo-hub.py` e a mesa no `scripts/nemo-hub.html`.

| Alias | Modelo | Por que saiu |
|---|---|---|
| `glm` | glm-5.3 (NVIDIA) | F: 19/19 e testes ok, mas **estourou os 15 min** (905 s) sem relatório; E: 840 s. Lento demais. |
| `gemma` | gemma-4-31b-it (NVIDIA) | F: 19/19 com **testes vácuos** e estourou 15 min (909 s) sem relatório; E: 562 s. Nenhum nicho provado; multimodal/texto simples **não testado**. |

## Regras de uso

- Tarefa que cria testes: o prompt traz o caso discriminante **ou** o Claude roda mutação no patch antes de aceitar (a decisão de arredondamento era o caso que os vácuos erravam).
- Fan-out de workers só com verificação objetiva (comando de validação + mutação). Sem verificador, rodar 2 modelos só dobra a revisão.
- Cross-layer, R2/R3 e tudo da lista "Nunca vai" do protocolo seguem fora, qualquer modelo.
- Limite de caixa de tempo: `timeout 900` no runner.
- NVIDIA free: ~40 req/min por modelo, chave única; 503 "overloaded" acontece (o plugin `auto-retry` cobre parte; quando o provedor recusa de vez a run termina em `erro` e o painel mostra o motivo). `ultra` roda no Zen, sem essa cota.
- Termos de uso comercial dos endpoints gratuitos da NVIDIA não estão claros: não mandar dados REAL nem segredo, só código do repo.
- A skill `task-observer` foi retirada dos workers (OpenCode no WSL e geradores do repo): ela disparava leitura fora do repo e acumulava negações de `external_directory`. No Claude Code continua ativa.

## Painel "Escritório Nemo" (`scripts/nemo-hub.py`)

- Subir: `python scripts/nemo-hub.py` e abrir `http://127.0.0.1:8765/`. Só escuta em 127.0.0.1; token novo a cada subida, injetado no HTML.
- Despachar: escolha o tipo de tarefa, preencha o objetivo, marque 1–3 funcionários e envie. Até 3 runs simultâneas; a primeira de cada lote sai na hora, as outras com 4 s de intervalo.
- Acompanhar: estado/cronômetro por mesa, log ao vivo (inclui os erros do provedor), cancelar com confirmação.
- Revisar: patch com `git apply --check` contra a árvore atual, veredito (ok/parcial/rejeitado) e "reenviar".
- Os arquivos de trabalho ficam fora do repo: `../nemo-runs.js` (eventos), `../nemo-logs/`, `../nemo-prompts/`, `../nemo-hub-state.json`.
- Sem o servidor, abrir `scripts/nemo-hub.html` como arquivo mostra só o benchmark embutido (modo leitura, sem despacho).
