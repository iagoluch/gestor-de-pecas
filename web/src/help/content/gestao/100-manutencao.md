---
titulo: Manutenção - Sugestões
grupo: Manutenção
ordem: 100
rotas: /manutencao
---

Tela **Manutenção — Sugestões**. Lista paradas de máquina que provavelmente precisam de manutenção. Quem decide é a Manutenção: aceitar ou descartar. Frase da tela: "Sugestão automática a partir de paradas de manutenção não planejadas. Aceitar/descartar é só registro interno; nada é enviado ao TOTVS."

É um **registro interno**. Não cria ordem no Protheus e não altera apontamento nem parada.

## Quem pode ver

- Conta de **Manutenção** (abre direto nesta tela, no visual de terminal, sem o menu da gestão). Essa conta **não acessa** as telas da gestão nem o Andon: só esta tela.
- **Administração**, pelo menu normal da gestão.

Outros perfis veem: "Seu perfil não tem acesso às sugestões de manutenção. Só a Manutenção e a administração usam esta tela."

## Como a sugestão nasce

O sistema olha as paradas dos últimos 7 dias (contados desde a meia-noite de 7 dias atrás). Vira sugestão quando a parada:

- é de motivo de **manutenção corretiva** (falha de equipamento);
- é **não planejada**;
- dura **10 minutos ou mais** (paradas menores são ignoradas como ruído).

A tela mostra no máximo as 200 mais recentes de cada aba; se chegar nesse limite, avisa "Mostrando as 200 mais recentes. Decida estas para ver as anteriores."

A geração acontece ao abrir a tela e não duplica: a mesma parada gera uma sugestão só.

## Abas

| Aba | O que mostra | Vazio |
|---|---|---|
| Sugeridas | Aguardando decisão | "Nenhuma sugestão pendente." |
| Aceitas | Já aceitas | "Nenhuma sugestão aceita." |
| Descartadas | Já descartadas | "Nenhuma sugestão descartada." |

## Colunas

Recurso, Setor ("Não informado" se vazio), Início (da parada), Duração (ex.: 45 s, 25 min, 1 h 05 min), Motivo ("Não informado" se vazio), OP ("Sem OP").

Em **Sugeridas** há ainda a coluna Decisão: caixa "Nota (opcional)" (até 500 caracteres) e botões **Aceitar** e **Descartar**.

Em **Aceitas/Descartadas**: Decidida por (selo + nome), Quando e Nota ("Sem nota").

## Como decidir

1. Abra a aba Sugeridas.
2. Escreva uma nota se quiser.
3. Clique em Aceitar ou Descartar.
4. A tela confirma ("Sugestão de <recurso> aceita." ou "descartada.") e atualiza a lista.

## Problemas comuns

- **"Já decidida por <nome> em <data>. A lista foi atualizada."**: outra pessoa decidiu antes.
- **"Esta sugestão não existe mais. A lista foi atualizada."**
- **"A nota é inválida (máximo de 500 caracteres)."**
- **"Não foi possível carregar as sugestões"**: tente de novo.
- **"Não foi possível acessar o servidor."**: verifique a conexão.

## Trava da Qualidade

A conta de Manutenção usa a base de permissões do Líder, mas o sistema barra nela a **alteração das cotas padrão já salvas** da Qualidade. Quem edita cotas continua sendo Supervisor/Líder, Qualidade e Admin.

Veja [perfis e acessos](topico:02-perfis-e-acessos) e [paradas](topico:72-analises-paradas).
