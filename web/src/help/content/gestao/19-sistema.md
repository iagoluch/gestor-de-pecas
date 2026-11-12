---
titulo: Sistema (reiniciar build)
grupo: Início
ordem: 19
rotas: /inicio/sistema
---

Tela **Admin — Sistema**: "Ações operacionais do servidor." **Só a conta de administração** abre.

## Card "Build do frontend"

O "build" é a montagem das telas que você vê no navegador. O botão **Reiniciar build** remonta tudo. Não desconecta ninguém.

1. Clique em **Reiniciar build**.
2. Confirme em **Reiniciar build** no diálogo.
3. Espere. O botão mostra "Reconstruindo…".
4. Quando terminar, aperte F5 para recarregar.

## Resultados

| Mensagem | Significado |
|---|---|
| "Build concluído em Ns. Atualize a página para ver as alterações." | Deu certo. |
| "O build falhou. Veja o log abaixo." | Falhou. O registro aparece embaixo. Envie ao responsável técnico. |
| "Não foi possível reconstruir o frontend." | Aparece no registro quando o servidor não devolve outra explicação. Se o servidor responder com um motivo, é ele que aparece no registro. |

O registro (log) é mostrado também quando o build dá certo.

Use só quando o responsável técnico pedir. Em dúvida, confirmar com a liderança.
