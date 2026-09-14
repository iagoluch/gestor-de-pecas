# Refatoração da UI operacional — v12

> Registro histórico de 19/08/2026. A interface descrita foi removida na consolidação Web-only de 24/08/2026.

Data: 19/08/2026

## Escopo

Esta etapa refatora somente as telas operacionais de apontamento. As telas gerenciais não foram alteradas.
A identidade visual e a paleta existente do Gestor de Peças foram preservadas.

## Alterações principais

- Cards de Produção e Fila de Ordem reorganizados em hierarquia fixa: OP, estado, operação, produto, descrição e indicadores.
- Cards de OP em parada passam a exibir motivo e tempo de parada quando os dados estão disponíveis.
- Descrições longas usam truncamento visual com tooltip, sem invadir outros campos.
- Painéis vazios exibem estados informativos em vez de grandes áreas brancas sem contexto.
- Modal de Parada ganhou busca incremental de motivo, lista rolável, contexto da operação, motivo selecionado, comentário e confirmação explícita.
- Histórico de Produção ganhou busca, filtro por status, cards refinados e estado vazio.
- "Ver mais" da Fila de Ordem foi convertido para lista compacta selecionável, adequada a descrições grandes.
- Confirmações de Setup e Retrabalho mantidas e enriquecidas com o recurso do posto.
- Destaque segue o fluxo Início → Fim, com Parada como ocorrência contextual; os três botões permanecem disponíveis e ações incompatíveis são explicadas ao operador.
- Detalhes do Destaque agora mostram Início, Fim, estado, tempo total e, quando parado, motivo e contador de parada.
- Tabela de OPs da tarefa foi reorganizada e a coluna técnica de edição ficou oculta no modo operador.
- Foi criada confirmação específica de Finalização do Destaque com tarefa, OPs relacionadas, crachá do operador, horário de início e tempo total.
- Tela de Corte ganhou busca por tarefa, plano, material e nesting e os cards foram reorganizados em blocos de informação.
- Parada manual do Corte agora registra o estado físico do recurso sem encerrar o nesting; o mesmo controle permite retomada manual.
- Mensagens técnicas de implementação foram substituídas por feedback operacional quando alteradas neste escopo.

## Regras preservadas

Nenhuma regra industrial foi redefinida nesta etapa. Permanecem válidas as regras oficiais da Manufatura e do backend v11, inclusive quantidade produzida somente por peças boas, Setup produtivo sem penalizar Disponibilidade/Performance, paradas manuais não programadas, interrupções automáticas programadas, fim de turno e rateio físico de recurso.

## Compatibilidade

- Não há migration nova de banco nesta refatoração visual.
- Não há alteração de schema.
- `ProductionService.registrar_finalizado` recebeu apenas parâmetro opcional para persistir a identificação confirmada do operador no evento de fim do Destaque quando o fluxo temporal do Destaque está disponível; chamadas antigas continuam válidas.

## Validação no ambiente de geração

- `python -m compileall`: aprovado.
- Suíte de backend/domínio selecionada: 95 testes aprovados + 2 subtestes.
- PySide6 não está instalado no ambiente Linux de geração; portanto os testes que importam Qt e a inspeção visual de runtime precisam ser executados no ambiente Windows do projeto.
- Psycopg, requests-ntlm e DPAPI/Windows também não estão disponíveis neste ambiente e seus testes não foram contabilizados como aprovados.
