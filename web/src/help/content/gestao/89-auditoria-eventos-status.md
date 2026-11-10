---
titulo: Auditoria - Eventos de Status
grupo: Auditoria
ordem: 89
rotas: /auditoria/eventos-status
---

Tela **Auditoria — Eventos de Status**. Mostra em que condição cada recurso esteve e por quanto tempo: produzindo, em setup, parado, sem demanda ou fora do turno.

Ela só **mostra**. Nada aqui altera o histórico.

## Para que serve

Responde "para onde foi o tempo da máquina?". Cada linha é um intervalo do recurso, com código e descrição do status, classificação (parada planejada ou não planejada), início, fim, duração, colaborador, motivo e a OP quando houver.

## O que observar

- **Em aberto**: o status ainda não terminou; a duração conta até agora.
- **Duração no período**: só o pedaço que cai dentro do filtro de datas.
- Um status de produção **não prova** que a OP foi executada. Para isso, veja **Eventos de Produção**.
