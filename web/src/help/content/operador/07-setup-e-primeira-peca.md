---
titulo: Setup e primeira peça
grupo: Tela do posto
ordem: 7
rotas:
---

**Setup** é a preparação da máquina para fabricar a peça. **Primeira peça** é a conferência da primeira unidade feita depois do setup. Em alguns setores, o lote só é liberado depois que a primeira peça for aprovada.

O botão **Setup** só existe nos setores que têm setup.

## Registrar o Setup

O botão **Setup** fica ativo quando a etapa está selecionável e a OP está na fila (Aguardando), Em processo, Parada ou Retrabalho. Não precisa clicar em **Iniciar** antes.

O Setup pode ser apontado de novo: por exemplo, quando a OP foi finalizada em parte, voltou para a fila e a máquina precisa ser preparada outra vez.

Se a máquina parar no meio do setup, clique em **Parada**. Para continuar o setup depois, clique em **Setup** de novo.

1. Selecione a etapa.
2. Clique em **Setup**.
3. Abre **Confirmar Setup**: "Confirme o registro de setup para a operação selecionada."
4. Clique em **Confirmar** (mostra "Enviando…") ou **Cancelar**.
5. Se o setor exige conferência da primeira peça, abre o popup **Setup e Qualidade**.

Com o Setup em curso, clicar de novo em **Setup** reabre a conferência, se ela ainda estiver pendente.

## Aviso do portão

Quando o sistema exige a primeira peça, aparece: "Aponte o Setup para conferir a primeira peça: o lote só é liberado — e a operação só pode ser finalizada — depois que ela for aprovada."

Em resumo: o **Iniciar** é livre. Sem aprovar a primeira peça, não dá para **Finalizar**: o botão continua clicável, mas o clique só mostra o aviso do sistema. Ele só fica apagado se o Setup obrigatório ainda não foi registrado.

## Popup "Setup e Qualidade" (Caldeiraria)

Ele tem três modos, conforme a situação.

### Modo 1 — Primeira peça bloqueada

Aparece só em OPs que ficaram bloqueadas por um retrabalho feito antes de 09/11/2026. Hoje o retrabalho não bloqueia mais a OP. O popup mostra o texto do sistema e: "O responsável precisa estar no posto e informar o próprio crachá. Não existe login para ele: a autorização fica registrada com OP, recurso, operador, horário e decisão."

| Campo ou botão | O que faz |
|---|---|
| **Crachá do responsável** | O responsável passa o próprio crachá. |
| **Chamar responsável** | Abre o chamado (veja [Chamar alguém](topico:11-chamar-alguem)) com motivo "Qualidade". |
| **Observação** | Texto livre. |
| **Cancelar** | Fecha sem liberar nada. |
| **Autorizar e liberar** | Libera a OP. Depois a OP entra em Retrabalho sozinha. |

O título do popup é "Primeira peça bloqueada". Enquanto uma OP antiga estiver bloqueada, o botão **Iniciar** fica apagado. Para abrir este popup, clique em **Retrabalho** (ou em **Setup**).

### Modo 2 — Produto sem cotas cadastradas

O popup mostra o cadastro de cotas do produto (com botão **Cancelar**), para cadastrar as medidas padrão. Veja [Qualidade e inspeção](topico:40-qualidade-e-inspecao). Ao salvar: "Cotas padrão salvas para este produto."

### Modo 3 — Medição da primeira peça

O título é "Medição da primeira peça". Para cada cota aparece:

| Item | O que é |
|---|---|
| **Cota N — descrição** | Qual medida conferir. |
| **Padrão** | O valor esperado. |
| **Faixa aceita** | Do menor ao maior valor aceito. |
| **Medida (mm)** | Você digita o valor medido. |
| **Situação** | Só aparece nas cotas que não têm faixa automática: escolha Selecione, Conforme ou Não conforme. |

Se a peça for reprovada, aparece **Destino da peça reprovada**:

- **Retrabalho** (é a opção que já vem marcada): você retrabalha a peça e mede de novo. A OP não fica bloqueada e não precisa de crachá.
- **Refugo — consome o saldo e exige outra peça**: exige **Crachá do responsável que autoriza o refugo** (com o botão **Chamar responsável**) e uma nova primeira peça.

Há também o campo **Observação** ("O que foi verificado no posto") e o botão **Cancelar**. O botão principal é **Liberar lote**. Fica apagado, com o motivo escrito, enquanto faltar algo:

- "Informe a medida de todas as cotas para liberar o lote."
- "Informe o crachá do responsável para registrar o refugo."

Quando o lote é liberado, o popup fecha e a OP volta à produção sozinha (você não precisa clicar em Iniciar). Se o destino foi Refugo, o popup também fecha e a produção é retomada sozinha.

### Outras mensagens do popup

| Mensagem | O que fazer |
|---|---|
| "Carregando o Setup/Qualidade…" | Aguarde. |
| "Aponte o Setup desta operação pelo botão Setup do posto: ..." | Feche e clique em **Setup**. |
| "Esta operação não possui o Setup/Qualidade estruturado." | Não há checklist. Clique em **Fechar** e fale com a liderança. |

**Fechar** e **Cancelar** nunca liberam nada.

## Popup "Primeira peça" (Solda e Pintura, sem Setup e sem cotas)

| Campo | Opções |
|---|---|
| **Resultado da primeira peça** | "Conforme — libera o lote"; "Retrabalho — você retrabalha e mede de novo"; "Refugo — produzir outra primeira peça" |
| **Observação** | Texto livre. |

Clique em **Registrar primeira peça**. Se o resultado for Conforme, o lote é liberado e você segue para **Finalizar**.

## Problemas comuns

| Situação | Causa | O que fazer |
|---|---|---|
| **Finalizar** apagado | Setup obrigatório ainda não registrado. | Clique em **Setup**. |
| **Finalizar** mostra só um aviso | Primeira peça ainda não aprovada. | Clique em **Setup** e conclua a conferência. |
| **Iniciar** apagado com OP bloqueada | OP antiga, bloqueada por retrabalho feito antes de 09/11/2026. | O responsável vem ao posto e usa o próprio crachá em **Autorizar e liberar**. |
| **Liberar lote** apagado | Falta medida ou crachá. | Leia o motivo escrito embaixo do botão. |
