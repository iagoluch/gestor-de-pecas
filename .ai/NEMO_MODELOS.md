# Modelos livres para delegação (`scripts/nemo.sh <slug> <prompt> [modelo]`)

Medido em 05/10/2026 no repo real, gabarito oculto. **Uma amostra por modelo e tarefa** (kimi: 2 no F) — ranking provisório; reavaliar com mais dados antes de endurecer a regra.

| Alias | Modelo | Via | F: função + testes (spec fechada) | E: bug com sintoma claro | Quando usar |
|---|---|---|---|---|---|
| `super` | nemotron-3-super-120b-a12b | NVIDIA | código 19/19, testes pegam a mutação, relatório completo, 449 s | correto, 164 s (o mais rápido) | **padrão para tarefa que escreve testes** e para correção pontual |
| `kimi` | kimi-k3 | NVIDIA | amostra 1: patch vazio (abortou após chamada negada); amostra 2: 19/19, testes pegam a mutação, 423 s | correto, 379 s | segunda via / comparação do `super`; rodar em paralelo e aceitar quem passar na verificação |
| `ultra` (padrão) | nemotron-3-ultra-free | OpenCode Zen | código 19/19, **testes vácuos** (passam com a decisão quebrada) | aceito | mapeamento "onde está" (só leitura), refatoração mecânica, constantes; maior base de testes (T1–T8, C–H) |
| `glm` | glm-5.3 | NVIDIA | 19/19 e testes ok, mas **estourou 15 min** sem relatório | correto, 840 s | só quando o tempo não importa; lento demais para o fluxo diário |
| `gemma` | gemma-4-31b-it | NVIDIA | 19/19, **testes vácuos**, estourou 15 min sem relatório | correto, 562 s | nenhum nicho provado aqui; nicho hipotético (multimodal, texto simples) **não testado** |

## Regras de uso

- Tarefa que cria testes: o prompt traz o caso discriminante **ou** o Claude roda mutação no patch antes de aceitar (a decisão de arredondamento era o caso que os vácuos erravam).
- Fan-out de workers só com verificação objetiva (comando de validação + mutação). Sem verificador, rodar 2 modelos só dobra a revisão.
- Cross-layer, R2/R3 e tudo da lista "Nunca vai" do protocolo seguem fora, qualquer modelo.
- Limite de caixa de tempo: `timeout 900` no runner. `glm` e `gemma` encostaram nele; `super` e `kimi` não.
- NVIDIA free: ~40 req/min por modelo, chave única; 503 "overloaded" acontece (plugin `auto-retry` cobre). `ultra` roda no Zen, sem essa cota.
- Termos de uso comercial dos endpoints gratuitos da NVIDIA não estão claros: não mandar dados REAL nem segredo, só código do repo.
- Os runs com `kimi`/`glm` carregaram a skill `task-observer` do OpenCode no WSL e bateram em `external_directory: deny` (3 negações seguidas no glm; abortou o kimi na 1ª amostra). Provável causa de parte do tempo gasto. Remover a skill do OpenCode no WSL (config do usuário) deve ajudar; não feito.
