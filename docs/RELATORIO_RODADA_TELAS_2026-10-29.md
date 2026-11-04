# Rodada de testes das telas — 29/10/2026

Tudo foi feito só no banco TEST (API :8002). O banco REAL não foi tocado.

## 1. Tela de apontamento (operador)
- Testei como operador: iniciar, pausar, retomar, refugo, retrabalho e finalizar.
- Achei 3 problemas e corrigi (commit `57b458b`):
  1. Finalizar com quantidade recusada agora mostra a recusa dentro da própria janela.
  2. Retrabalho com saldo 0 aceita 0/0.
  3. Parada que começa e termina no mesmo minuto não é enviada ao Protheus.

## 2. Telas de gestão
- Percorri as telas em todos os níveis de acesso que têm usuário cadastrado.
- Para ver dados de verdade, rodei a simulação da fábrica no TEST (dados fictícios, datados de 03/11/2026).
- Conferi: Gerencial, Produção, Perdas, Indicadores, Dados analíticos, Produção realizada, Horas, Qualidade, Diretoria.
- Os totais bateram com o banco (ex.: Usinagem 161 boas / 12 refugo, Dobra 68 / 4, Serra 65 / 4).
- Os exports (técnico e simples) também bateram com o banco para 03/11.

## 3. Erro real achado e corrigido (commit `bf213f8`)
- Nos filtros de data, digitar o Início e clicar em "Aplicar" sem sair do campo usava a data antiga.
- Agora a data digitada vale assim que está completa. Há um teste automático para isso.
- Efeito: os primeiros prints dos relatórios misturavam 29/10 com 03/11 por causa desse erro. Os exports, feitos depois da correção, estão certos.

## 4. Também commitado
- Ajustes na simulação: aceite local do SOAP, checagem de API autenticada e banco fixado no TEST.

## 5. Observações (não são erros comprovados, ficam para decidir)
- **Eficiência acima de 100%**: Diretoria mostra Pintura com 1.087,7%. Vem de tempo padrão cadastrado vs. durações simuladas; em dado real vale conferir.
- **OEE 33%** com aviso "tempo padrão ausente para 297 de 1149 peças": o aviso está correto e explica o número.
- **"Perdas por motivo: Não disponível"** na tela de OEE.
- **Nome do setor** varia: "Protótipo" no Gerencial, "Operador Protótipo" em Produção realizada.
- **Tela Produção**: o texto "Fonte de qualidade" se repete igual em todas as linhas (poluição visual).
- **Horas**: "Tempo físico" de 126h por recurso em 6 dias inclui todos os estados do recurso, não só produção. Vale um rótulo mais claro.

## 6. Pendências
- Andon TV, Mapa da fábrica e Rastreabilidade não foram revistos nesta rodada.
- `web/src/pages/areas/AreaPage.tsx` tem alteração antiga não commitada (não é desta rodada).
