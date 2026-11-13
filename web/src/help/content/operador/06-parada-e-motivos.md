---
titulo: Parada e motivos
grupo: Tela do posto
ordem: 6
rotas:
---

Use **Parada** sempre que o posto ou uma OP parar de produzir, por qualquer motivo. Sem registrar, o tempo parado fica sem explicação.

## Quando o botão Parada funciona

- O botão se chama **Parada**, com ou sem OP ativa.
- Fica apagado se o posto já está parado e não há OP, ou se todas as OPs ativas já estão paradas.

## Registrar uma parada

1. Clique em **Parada**. Abre o popup **Registrar parada**.
2. Se há **várias OPs ativas**, aparece a lista "OPs que vão parar" com uma caixa para cada OP. Marque ao menos uma. OPs já paradas não entram na lista.
3. Em **Buscar motivo**, digite o código ou parte da descrição. Se o código for exato, ou se sobrar um só resultado, o motivo é escolhido sozinho.
4. Em **Motivo da parada**, escolha o motivo na lista. Se nada combinar: "Nenhum motivo corresponde ao filtro informado."
5. Se o motivo exigir, preencha **Comentário (obrigatório)**.
6. Clique em **Confirmar parada**.

O botão **Confirmar parada** fica apagado enquanto faltar: o motivo (mostra "Selecione"), o comentário obrigatório, ou a marcação de ao menos uma OP.

Motivos em amarelo (cor de aviso) são os **planejados** (parada programada: pausa, intervalo, reunião, limpeza, manutenção preventiva e semelhantes). Todos os outros são **não planejados**. A lista vem do cadastro de motivos da fábrica; o nome exato de cada motivo: confirmar com a liderança.

Alguns motivos não aparecem para o operador: "Fora de turno" (o sistema lança sozinho no fim do turno) e os de falta ou saída antecipada (lançados pela liderança). Há motivos só de certos setores (por exemplo, troca de arame e de gás na Solda, ajuste da dobradeira na Dobra). Motivos que dependem de outro setor (como "Aguardando setor Solda") ficam no fim da lista.

Sem OP carregada e sem nada em andamento, parar o posto também é permitido pelo mesmo botão **Parada**.

Com várias OPs marcadas, o sistema registra uma parada por OP, em sequência. Se o sistema recusar uma, as seguintes não são registradas. Leia a mensagem de erro no popup.

## Depois de parar

- A barra de estado muda para **Parado** e mostra o motivo e o tempo parado.
- Aparece a faixa vermelha: "Recurso parado — {motivo}. Retome para voltar a apontar."
- Nos cards, a OP mostra "Motivo:", "Desde:" e "Tempo parado:".

## Retomar

1. Clique em **Retomar produção** (é o botão Iniciar, com outro nome).
2. O estado volta para **Produzindo**.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| **Confirmar parada** apagado | Falta motivo, comentário obrigatório ou OP marcada. |
| Motivo não aparece | Apague o texto do campo **Buscar motivo**. |
| "OP não encontrada" no campo da OP | A OP digitada não existe. Corrija o código ou apague o campo. |
| Preciso de ajuda para o problema | Use [Chamar alguém](topico:11-chamar-alguem). |
