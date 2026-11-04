---
titulo: Áreas - tela de cada área
grupo: Áreas
ordem: 35
rotas: /areas
---

Cada **área** da fábrica tem uma tela própria, com o título **Área — nome da área**. Todas as áreas usam a mesma tela. O que muda é o conjunto de setores mostrado.

Frase de apresentação: "Recursos de (setores) no dia corrente: estado, OP, operador e duração."

## Áreas e setores

| Área | Setores incluídos | Tópico |
|---|---|---|
| Dobra e Corte | Dobra, Corte | [Dobra e Corte](topico:36-area-dobra-e-corte) |
| Usinagem | Usinagem | [Usinagem](topico:37-area-usinagem) |
| Serra | Serra | [Serra](topico:38-area-serra) |
| Solda | Solda Aço, Solda Alumínio, Solda Robô | [Solda](topico:39-area-solda) |
| Pintura | Pintura | [Pintura](topico:40-area-pintura) |
| Protótipo | Protótipo | [Protótipo](topico:41-area-prototipo) |
| Projetos/Ferramentaria | Proj. Ferramentaria | [Projetos e Ferramentaria](topico:42-area-projetos-ferramentaria) |

Cada área aparece no menu como uma seção com **uma única aba: "Recursos"**. Não há outras sub-abas.

## Quem vê qual área

A área vem do **nível** da conta (veja [Perfis e acessos](topico:02-perfis-e-acessos)).

| Nível | Áreas que vê |
|---|---|
| Supervisor Caldeiraria | Dobra e Corte, Usinagem, Serra |
| Supervisor Almoxarifado/Solda/Pintura | Solda, Pintura |
| Supervisor Protótipo | Protótipo |
| Líder Dobra e Corte | Dobra e Corte |
| Líder Usinagem | Usinagem |
| Líder Serra | Serra |
| Líder Pintura/Almoxarifado e Líder Pintura | Pintura |
| Líder Projetos/Ferramentaria | Projetos/Ferramentaria |
| Líder Solda | Solda |
| Líder Almoxarifado | Nenhuma |
| Admin e Gerente industrial | Todas |
| Demais níveis (Diretoria, Qualidade, Manufatura, Gestor etc.) | Nenhuma |

Admin e Gerente industrial **não têm seções de área no menu**. Eles usam o filtro Setor em [Consulta Operacional — Recursos](topico:31-consulta-recursos). Mesmo assim, o endereço `/areas/<área>` abre para eles.

Contas de líder e supervisor só recebem dados do próprio setor. Isso é feito no servidor, não só na tela.

## O que a tela mostra

Sem período nem filtros. Sempre o dia corrente. A tela lê os recursos do dia e mostra só os dos setores da área (até 200).

### Cartões

| Cartão | O que mostra | Observação |
|---|---|---|
| Recursos da área | Quantos recursos a área tem. | Conta as linhas da tabela. |
| Em produção agora | "X de Y". | Verde. Clicável. O painel diz: "Recursos dos setores da área ..." |
| Parados | Recursos em parada. | Vermelho se houver ("Verifique o motivo na tabela"). Verde com "Nenhuma parada aberta". |
| OPs em execução | Soma das OPs ativas. | Azul. Clicável. |

### Tabela "Recursos"

As colunas são as mesmas de [Consulta Operacional — Recursos](topico:31-consulta-recursos): Recurso, Setor, Estado, OP, Produto, Operador, Início, Duração, Motivo.

## Fila de prioridades

O painel **Fila de prioridades** aparece no fim da tela, **só para quem pode ordenar a fila daquela área**.

| Conta | Pode ordenar? |
|---|---|
| Líder e supervisor | Sim, nas áreas do próprio nível. |
| Admin | Sim, em todas. |
| Gestor, Gerente industrial, Qualidade, Diretoria | Não. Apenas enxergam. |

Texto do painel: "A ordem desta fila vale até a OP sair dela (concluída ou removida). Ela não zera no dia seguinte."

A fila que o operador vê é a mesma que o líder edita. Cada mudança chega ao operador em tempo real.

### Regras

1. Só a **próxima operação liberada** da OP pode ser puxada para a fila.
2. A OP pode vir de qualquer recurso.
3. A posição vale até a OP sair da fila (concluída ou removida).
4. **Corte e Destaque ficam de fora.** Eles têm fila automática.

### Como adicionar uma OP

1. Escolha o **Recurso** na lista (só postos apontáveis da área).
2. Digite o número no campo **OP** ("Número da OP").
3. Clique em **Adicionar à fila**. O botão fica desabilitado sem OP.

### Tabela da fila

| Coluna | O que mostra |
|---|---|
| Posição | Lugar na fila. |
| OP | Número da OP. |
| Operação | A operação que será feita. |
| Produto | Produto da OP. |
| Quantidade | Quantidade da OP. |
| Origem | "Fixada pelo líder" (azul) para OP posta à mão. "Veio de (recurso)" (amarelo) se a OP estava em outro recurso. |
| Ações | Subir, Descer, Remover. |

Subir fica desabilitado na primeira linha. Descer, na última. Remover tira a OP da fila fixada.

### Mensagens da fila

| Mensagem | O que significa |
|---|---|
| Nenhuma OP na fila deste recurso | A fila do recurso está vazia. |
| Nenhum recurso disponível para a fila desta área | A área não tem posto com fila manual. |
| Informe o número da OP. | O campo OP está vazio. |
| OP (x) não encontrada. | O número não existe no sistema. |
| OP (x) não está ativa. | A OP já foi encerrada ou cancelada. |
| Já em execução em (recurso) desde (hora). | A OP já está sendo trabalhada. |
| OP (x) já está aguardando em (recurso). | A OP já está na fila de outro posto. |
| OP (x) não tem roteiro importado. | Sem roteiro, não há operação para puxar. |
| OP (x) já teve todas as etapas concluídas. | Nada a puxar. |
| OP (x) aguarda a etapa (nº e descrição) ser concluída. | A etapa anterior ainda não terminou. |
| A próxima etapa da OP (x) não é apontada em recurso. | A próxima etapa não tem posto de apontamento. |
| Esta OP não está fixada na fila deste recurso. | Tentou remover ou mover OP que não é fixada. |
| Seu perfil não gerencia a fila desta área. | Sua conta só enxerga. |
| Este recurso não pertence à sua área ou não tem fila manual. | Escolha outro recurso. |
| Não foi possível concluir a operação. Tente de novo. | Falha genérica. Depois de qualquer erro a lista é recarregada. |

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Área indisponível para a sua conta | Esta área não faz parte do seu setor. | Peça a um administrador, se precisar de acesso. |
| Painel Fila de prioridades ausente | Sua conta não ordena a fila dessa área. | Normal para gestor, qualidade e diretoria. |
| Menu sem seção de área | Seu nível não é líder nem supervisor (inclui admin e gerente industrial). | Use o filtro Setor em Recursos. |
