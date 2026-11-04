---
titulo: Qualidade e inspeção
grupo: Qualidade
ordem: 40
rotas:
---

O operador não tem tela nem aba própria de Qualidade ou Inspeção: a área do operador (`/operador`) não leva a ela. O que você usa no posto é o popup **Setup e Qualidade** (veja [Setup e primeira peça](topico:07-setup-e-primeira-peca)), que tem a medição da primeira peça e o mesmo cadastro de cotas descrito abaixo em "Produto sem cotas".

O restante deste capítulo (fila de inspeção, RNC, histórico) descreve a tela de inspeção da Qualidade. Ela não está ligada a nenhum menu atual do sistema; se a liderança passar a usá-la, valem as regras abaixo. Onde e quando ela é usada: confirmar com a liderança.

O cadastro e a revisão das cotas padrão de cada produto ficam em uma tela da Qualidade, só para a Qualidade e a administração.

## Fila de inspeção

No alto há quatro contadores, em peças: **Aguardando inspeção**, **Aprovadas**, **Retrabalho** e **Refugo**.

| Item | O que faz |
|---|---|
| **Buscar OP, produto ou data** + **Buscar** | Filtra a fila. Se não achar, o sistema explica o estado do roteiro. |
| **Máquinas** | Filtra por recurso (padrão "Todas"). |
| **Histórico** | Abre o histórico da Qualidade. |

A tabela tem: OP, Desc., Produto, Recurso, Quantidade, Data. Em Quantidade, "3/10" significa 3 inspecionadas de 10. Páginas de 8 linhas, com setas ‹ e ›.

Vazio: "Nenhuma OP aguardando inspeção" / "A OP entra aqui quando o roteiro chega na operação de inspeção."

Em cada linha há dois botões:

- **→**: abre a inspeção da OP.
- **Sem inspeção**: abre o popup **Seguir sem inspeção**.

### Seguir sem inspeção

A OP segue sem a inspeção dimensional. Nenhuma peça é aprovada, nenhuma cota é medida e nenhuma RNC é aberta. Fica registrado só que a inspeção foi dispensada.

1. Digite o **Crachá de quem autoriza**.
2. Se quiser, preencha **Motivo (opcional)**.
3. Clique em **Confirmar e seguir** (apagado sem crachá) ou **Cancelar**.

## Inspeção de uma OP

O topo mostra OP, Produto e Progresso ("Peça N de M").

### Produto sem cotas

Aparece **Cadastro das cotas do produto**. Para cada cota:

| Campo | O que informar |
|---|---|
| **Descrição (opcional)** | Nome da medida. |
| **Padrão (mm)** | Valor nominal, ex.: 125,0. |
| **Tolerância (± mm)** | Variação aceita, ex.: 0,5. |
| **Remover** | Tira a cota (se houver mais de uma). |

**+ Adicionar cota** cria outra. **Salvar cotas do produto** só habilita com padrão e tolerância em todas: "Preencha o padrão e a tolerância de todas as cotas para salvar." Ao salvar: "Cotas padrão salvas para este produto." Alterar o padrão depois é atribuição de Supervisor ou Líder.

### Checklist de cotas

| Coluna | Significado |
|---|---|
| **Cota** | Número e descrição. |
| **Padrão** | Valor esperado e "Faixa X a Y mm". |
| **Medida** | Digite só números (ex.: 125,4). Texto errado: "Use só números, ex.: 125,4". |
| **Status** | Automático: Informe a medida / Conforme / Não conforme. Sem faixa automática, você escolhe Selecionar / Conforme / Não conforme. |

Linhas não conformes ficam marcadas.

### RNC

O botão **Abrir RNC** só habilita com cota não conforme. Depois vira "RNC registrada — editar". No popup **RNC — Relatório de Não Conformidade**: veja o resumo (OP, Produto, Peça, Recurso, Operador) e as cotas ruins, escreva o **Motivo / descrição da não conformidade** (mínimo 3 letras) e a **Observação (opcional)**, e clique em **Registrar RNC**. Com cota não conforme, a RNC é obrigatória para concluir a peça.

### Resultado da peça

Escolha **Aprovada**, **Retrabalho** ou **Refugo**. Com cota não conforme, **Aprovada** fica apagada.

### Salvar

- **Salvar e próxima peça**: grava e passa para a próxima. O checklist começa limpo.
- Na última peça o botão é **Finalizar inspeção**: abre o popup com **Crachá do operador** (+), e **Concluir inspeção**.
- **← Voltar** sai sem salvar a peça atual.

O botão só habilita com todas as medidas, o resultado e (se não conforme) a RNC.

### Desenho / PDF da peça

Painel ao lado, com nome do arquivo e versão. Sem visualizador: "Este dispositivo não possui visualizador de PDF embutido." com link "Abrir o desenho em nova guia". Sem desenho: "Nenhum desenho/PDF disponível para este produto." (a inspeção continua liberada).

## Histórico da Qualidade

Filtros: OP, Produto, Recurso, Resultado (Todos, Aprovada, Retrabalho, Refugo), De, Até, e **Filtrar**. A tabela mostra Data/Hora, OP, Produto, Peça, Recurso, Operador, Resultado e RNC. **Ver detalhes** mostra as cotas medidas (Cota, Padrão, Medida, Status). Vazio: "Sem inspeções registradas no filtro atual".

## Crachá e PDF

No fluxo do operador não há impressão de crachá nem PDF de etiqueta. O único PDF é o desenho da peça (veja [Desenho da peça](topico:12-desenho-da-peca)). O crachá é só digitado ou passado nos popups (finalizar, refugo, autorização, chamada). Onde o crachá é impresso: confirmar com a liderança.
