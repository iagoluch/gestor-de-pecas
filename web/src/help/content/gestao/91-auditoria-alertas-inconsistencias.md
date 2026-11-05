---
titulo: Auditoria - Alertas e inconsistências
grupo: Auditoria
ordem: 91
rotas: /auditoria/alertas-inconsistencias
---

Tela **Auditoria — Alertas e inconsistências**. Reúne o que saiu do normal no período: alertas, avisos internos, inspeções dispensadas e dados que não fecham. Frase da tela: "Desvios do período, alertas internos e conflitos ou lacunas preservados como evidência, sem reescrever histórico nem inventar confiança estatística."

A tela só lista. Não envia mensagem nem corrige nada.

## Filtros

Usa os [filtros globais](topico:04-filtros-globais), menos a seção "Alertas internos", que não usa período nem outros filtros (só o setor da sua conta). As listas de inconsistências e de inspeções dispensadas carregam até 200 linhas.

## Seção 1: Alertas — resumo do período

Cartões: **Críticos**, **Erros**, **Atenções** e **Total**. Quando o valor é maior que zero, ele é clicável e abre a explicação de como foi calculado. Se o sistema tiver um aviso sobre a confiabilidade dos alertas, ele aparece como detalhe do cartão **Total**.

## Seção 2: Alertas do período

| Coluna | O que mostra |
|---|---|
| Tipo | Categoria do alerta. |
| Ocorrência/motivo | O que aconteceu. |
| Setor, Recurso/máquina | Onde aconteceu. |
| Duração/impacto | Tempo afetado. "Não mensurado" quando não há segundos registrados. |
| Situação | Selo colorido (veja cores abaixo). |

## Seção 3: Alertas internos — notificação pendente

São avisos gerados pelo sistema para PCP, supervisão ou responsável pelo retrabalho. Tipos: primeira peça (liberada, em retrabalho, refugo), retrabalho em peça posterior, refugo, necessidade de reposição e necessidade de nova OP.

Colunas: Tipo, OP, Setor, Recurso, Qtd., Destinatário, Ocorrência, Notificação. A lista mostra todos os alertas, não só os pendentes.

O envio é pelo Telegram, para o chat do setor (ou da fábrica, se o setor não tiver chat). A coluna Notificação tem três estados: **pendente** (ainda não saiu), **enviada** e **descartada** (o alerta já foi resolvido ou tem mais de 24 horas, então não vale mais avisar).

Vazio: "Nenhum alerta interno registrado". Eles aparecem aqui assim que acontecem retrabalho, refugo ou necessidade de reposição.

## Seção 4: Inspeções dispensadas no período

Quando a Qualidade dispensa a inspeção de uma OP. Colunas: OP, Operação, Recurso, Setor, Produto, Qtd., Motivo, Autorizado por, Crachá, Data.

Vazio: "Nenhuma inspeção dispensada no período".

## Seção 5: Inconsistências — resumo e lista

Cartões: **Críticas**, **Erros**, **Atenções**, **Total**.

Lista "Inconsistências detectadas": Severidade, Tipo, Descrição, Setor, Recurso, OP, Início, Fonte.

### Inconsistências que o sistema detecta

| Gravidade | Mensagem |
|---|---|
| Crítico | OP ativa sem recurso identificado. |
| Crítico | Fim do apontamento anterior ao início. |
| Crítico | OP atravessou limite oficial de turno sem interrupção programada automática. |
| Crítico | A soma dos tempos atribuídos às OPs não conserva o tempo físico da sessão. |
| Crítico | Também: estados do recurso sobrepostos e incompatíveis; recurso em setores conflitantes; estado físico desconhecido. |
| Erro | Apontamento finalizado sem quantidade de peças boas. |
| Erro | OP ativa sem operador de início identificado. |
| Erro | Operador identificado em apontamento sem recurso. |
| Erro | Execução ativa de recurso sem OP identificada. |
| Erro | Recurso em Produção sem OP operacional sobreposta no mesmo intervalo. |

Considera "ativas" as OPs em: Em processo, Parada, Setup e Retrabalho. A checagem de rateio de tempo só roda sem filtro de OP/operação.

## Cores dos selos

- Vermelho: crítico, erro, parada.
- Amarelo: atenção, alerta, setup.
- Verde: concluído, normal, ok, finalizado.
- Azul: em processo, informação.

## Quem pode ver

Gestão. Líder e supervisor veem só o próprio setor.

## Problemas comuns

- **Muitas inconsistências "OP ativa sem operador"**: operador não registrou o crachá. Converse com o líder do setor.
- **Duração "Não mensurado"**: o alerta não tem tempo gravado. Não é zero.
- **Alerta interno "pendente" parado**: o Telegram está desligado, sem chat configurado para o setor ou falhou. O alerta fica pendente e o sistema tenta de novo (de 1 a 15 minutos). Peça ao Admin para conferir o Telegram na tela [Sistema](topico:19-sistema).

Veja também [confiabilidade](topico:92-auditoria-confiabilidade) e [glossário](topico:05-glossario).
