---
titulo: Produção - Consulta de OP
grupo: Produção
ordem: 45
rotas: /producao/ordens
---

Tela **Produção — Consulta de OP**. Frase de apresentação: "Escolha uma OP para ver o roteiro completo, na ordem das operações. Consulta de gestão; a rastreabilidade fica em Rastreabilidade."

Ela responde: **por onde a OP passa e em que ponto ela está?**

Não há barra de filtros. Você escolhe uma OP pela busca.

## Como consultar

1. No campo **Buscar OP**, digite pelo menos **2 caracteres** do código, do produto ou da descrição.
2. Na lista **OPs encontradas** (até 20), clique na OP.
3. A tela mostra a situação, os dados da OP, o roteiro e o histórico.

Antes de escolher: "Nenhuma OP escolhida. Digite pelo menos 2 caracteres do código, do produto ou da descrição e escolha uma OP da lista."

### OP que não está no sistema

Se a busca não acha nada, aparece "Nenhuma OP no sistema para essa busca." e um botão **Consultar "termo" no Protheus**.

1. Clique no botão. Ele muda para "Consultando o Protheus…".
2. Se a OP existir no Protheus, ela é carregada na hora.

| Resultado | Tipo | Significado |
|---|---|---|
| OP já estava no sistema. | Sucesso | Nada foi carregado. |
| OP encontrada no Protheus e carregada agora. Ainda não passou pelo sistema. | Sucesso | Foi buscada no ERP agora. |
| OP não encontrada no Protheus e nunca passou pelo sistema. | Aviso | O número não existe. Confira a digitação. |
| A OP existe no Protheus, mas sem roteiro utilizável. Ainda não entrou no sistema. | Aviso | O Protheus não tem roteiro válido para ela. |
| (mensagem) Não dá para saber se a OP existe no Protheus. | Erro | O Protheus ficou indisponível ou demorou. Tente mais tarde. |
| Muitas consultas ao Protheus em pouco tempo. Aguarde um minuto e tente de novo. | Limite | Espere 1 minuto. |

## Cartão de situação

| Mensagem | Cor | Significado |
|---|---|---|
| Já passou pelo sistema. | Verde | Mostra "X de Y apontamento(s) iniciados", primeira entrada, última atividade e quando os dados vieram do Protheus. |
| Já está no sistema, mas ainda não foi trabalhada. | Amarelo | Nenhum apontamento iniciado. |
| Ainda não passou pelo sistema. Só existe no Protheus. | Neutra | Veio só da consulta ao ERP. |

## Cartão "OP (código)"

| Campo | O que mostra |
|---|---|
| OP | Código da OP. |
| Produto | Código do produto. |
| Descrição | Descrição do produto. |
| Quantidade | Quantidade da OP, com unidade. |
| Status | Status da OP no PCP. |
| Emissão | Data de emissão. |
| Liberação | Data de liberação. |
| Início planejado | Quando o plano previa começar. |
| Fim planejado | Quando o plano previa terminar. |

## Bloco "Roteiro"

Lista as operações **na ordem do roteiro**.

| Coluna | O que mostra |
|---|---|
| Operação | Número da operação. Etapa criada no Gestor ganha a etiqueta amarela "Adicionada no Gestor". |
| Descrição | Descrição da operação. |
| Setor | Setor da operação. |
| Recurso | "código · nome" do recurso. |
| Tempo padrão | Em segundos, com 2 casas e " s". "n/a" quando não há tempo cadastrado. |
| Situação | Veja abaixo. |
| Ação | Botão "Desativar" (só para quem pode alterar o roteiro). |

"n/a" significa que o tempo padrão não está cadastrado no Protheus. O Protheus manda 0,01 para "não configurado". A engenharia de manufatura ajusta direto no ERP.

### Situação da operação

| Texto | Significado |
|---|---|
| Marco terminal (Protheus) | Etapa final do roteiro vinda do Protheus. |
| Inspeção da Qualidade | Etapa de inspeção. |
| Desativada | Etapa do Gestor que foi desativada. A linha fica esmaecida. |
| Substituída no Protheus | O Protheus trocou a operação. A linha fica esmaecida. |
| Aguardando, Em processo, Finalizado etc. | Último status do apontamento. |
| Não iniciada | Ainda sem apontamento. |

OP sem roteiro mostra "Esta OP não tem roteiro."

## Alterar o roteiro

Só contas dos níveis **admin, manufatura ou PCP** veem os botões "Adicionar etapa" e "Desativar". Os demais só consultam.

### Adicionar etapa

Uso: acrescentar uma etapa que existe só na fábrica. Ela **vale só no Gestor**: o operador aponta nela como em qualquer operação, mas ela **não vai ao Protheus**.

1. Clique em **Adicionar etapa**.
2. Preencha:

| Campo | Regra |
|---|---|
| Depois da operação | A etapa entra depois desta. |
| Setor | Filtra a lista de recursos ("Todos os setores"). |
| Recurso | "Escolha o recurso". Só postos apontáveis, exceto Corte e Destaque. |
| Descrição da etapa | De 3 a 120 caracteres. |
| Motivo | De 3 a 500 caracteres. |

3. Clique em **Adicionar etapa** ("Salvando…"). Para desistir, clique em Cancelar.

Sucesso: "Etapa adicionada ao roteiro. Ela vale só no Gestor e não vai ao Protheus."

### Desativar etapa

1. Clique em **Desativar** na linha da etapa.
2. Leia: "A etapa (nº · descrição) deixa de valer nesta OP. O registro fica no histórico; nada é apagado."
3. Preencha o **Motivo** (mínimo 3 caracteres).
4. Clique em **Desativar etapa**.

Sucesso: "Etapa (...) desativada."

Só podem ser desativadas etapas **criadas no Gestor, ainda ativas e sem apontamento**. Etapas do Protheus não mudam aqui.

## Bloco "Histórico do roteiro"

| Coluna | O que mostra |
|---|---|
| Quando | Data e hora. |
| Quem | Quem alterou. |
| Ação | Adicionou etapa, Desativou etapa ou Alterou etapa. |
| Etapa | A etapa afetada. |
| Motivo | O motivo informado. |

Sem alterações: "Nenhuma alteração no roteiro. O roteiro está como veio do Protheus."

A lista mostra até 100 registros. Toda alteração também vai para a auditoria (veja [Alterações](topico:18-alteracoes)).

## Quem vê

Qualquer conta da gestão consulta. Só admin, manufatura e PCP alteram o roteiro.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Só o PCP, a engenharia de manufatura e a conta administradora alteram o roteiro de uma OP. | Sua conta não tem permissão. | Peça a quem tem. |
| Esta etapa já tem apontamento e não pode ser desativada. | Já houve produção nela. | Nada a fazer aqui. |
| Só etapas adicionadas no Gestor e ainda ativas podem ser desativadas. Etapas do Protheus não são alteradas aqui. | Tentou desativar etapa do ERP ou já desativada. | Ajustes no ERP são feitos no Protheus. |
| A descrição e o motivo precisam ter pelo menos 3 caracteres. | Texto curto demais. | Complete o texto. |
| Escolha um recurso em que algum operador aponta. | Recurso sem apontamento. | Escolha outro. |
| Escolha o recurso da etapa. | Recurso em branco. | Selecione um. |
| A operação escolhida não faz parte do roteiro ativo desta OP. Atualize a tela e tente de novo. | O roteiro mudou enquanto você editava. | Atualize a página. |
| OP não encontrada. | A OP sumiu ou o número está errado. | Busque de novo. |
| Informe o motivo (pelo menos 3 caracteres). | Motivo vazio ao desativar. | Preencha. |
| Não foi possível acessar o servidor. Tente novamente. | Falha de rede. | Use "Tentar novamente". |
| Não foi possível concluir a operação. Tente novamente. | Falha genérica. | Use "Tentar novamente". |

## Veja também

- [Execução das OPs](topico:46-producao-execucao-das-ops).
- [OPs em andamento](topico:32-consulta-ops-em-andamento).
