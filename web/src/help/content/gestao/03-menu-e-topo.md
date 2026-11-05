---
titulo: O topo e o menu lateral
grupo: Primeiros passos
ordem: 3
rotas:
---

## Menu lateral (à esquerda)

Cada item é uma **seção**. Clique para abrir a primeira aba dela. As abas da seção aparecem em cima do conteúdo.

| Seção | Abre em | Abas |
|---|---|---|
| Tela inicial | Visão Geral | Visão Geral, IA, Chamadas da Gestão |
| Painéis Operacionais | Andon | Andon, Mapa da fábrica, Pausas |
| Consulta Operacional | Visão Geral | Visão Geral, Recursos, OPs em andamento |
| Produção | Consulta de OP | Consulta de OP, Execução das OPs, Produção realizada, Planejado × Realizado |
| Análises | OEE | OEE, Horas & Utilização, Paradas & Setup, Qualidade, Tempo padrão, Cronoanálise, Capacidade, Confiabilidade |
| Auditoria | Apontamentos | Apontamentos, Alertas e inconsistências, Confiabilidade dos dados |
| Relatórios | Relatórios | sem abas |
| Rastreabilidade | OP / Produto | OP / Produto, Lote / Material / Nesting |
| Manufatura | Manufatura | sem abas por enquanto (o tempo padrão é ajustado direto no Protheus) |
| Qualidade | Cotas padrão | Cotas padrão, SPC, Decisão de RNC |
| Diretoria | Diretoria | Diretoria (uma aba só) |
| Melhoria Contínua | Oportunidades | Oportunidades |
| Seções por área | Recursos | Recursos |
| IagoDev | Crachás | Crachás, Cadastro, Chamadas do IagoDev, Turnos, Alterações, Sistema |

Quem vê cada seção está em [Perfis e o que cada um vê](topico:02-perfis-e-acessos).

Detalhes:

- **Andon** e **Mapa da fábrica** abrem telas próprias, fora do menu normal (painéis feitos para TV).
- A aba **Metas** existe (veja [Metas](topico:12-metas)), mas está **oculta** no menu. Só abre se alguém digitar o endereço.
- O endereço antigo de **Alertas** da tela inicial leva à aba "Alertas e inconsistências" de Auditoria. O antigo **Setores** leva à Visão Geral.
- No rodapé do menu aparece o crédito "Desenvolvido por: Iago Luchtenberg da Silva".

### Recolher o menu

O botão com a seta **‹** (Recolher menu) deixa o menu estreito. A seta **›** (Expandir menu) volta ao normal. O sistema lembra a sua escolha na próxima vez que você entrar neste navegador.

### No celular

O menu vira uma gaveta. O botão de três linhas (**Abrir navegação**) abre. Feche com **Fechar navegação**, com o **×**, clicando fora ou apertando Esc. O link invisível "Pular para o conteúdo" ajuda quem navega pelo teclado.

## Topo da tela (da esquerda para a direita)

| Item | O que é | O que acontece ao clicar |
|---|---|---|
| Caminho "Gestão / Seção / Aba" | Mostra onde você está. | Nada, só informa. |
| **Ir para qualquer tela…** (Ctrl K) | Busca de telas. | Abre a busca (veja abaixo). |
| Relógio | Hora e data do sistema, atualizadas a cada 30 segundos. Quando existe, usa o relógio de referência do servidor. | Nada. |
| **?** (Manual: ajuda sobre esta tela) | Abre este manual em nova aba, já no tópico da tela. | Abre `/ajuda/gestao`. |
| Lua/sol | Alterna tema claro e escuro. | Muda na hora. |
| Sino | Chamadas ainda não vistas. | Abre **Chamadas da Gestão** e marca tudo como visto. |
| Seu nome e botão de sair | Quem está logado. | O botão de sair encerra a sessão. |

### Busca no topo (Ctrl K)

1. Clique em **Ir para qualquer tela…** ou aperte **Ctrl K** (no Mac, Cmd K).
2. Digite parte do nome da seção ou da aba (o campo mostra "Digite o nome de uma tela…"). Exemplo: "paradas".
3. Use as setas do teclado para escolher e aperte **Enter**. **Esc** fecha.

Cada resultado mostra a aba em negrito e a seção em letra pequena. A busca ignora maiúsculas e só lista telas que o seu nível pode abrir. Sem resultado, aparece "Nenhuma tela encontrada".

### O sino

Mostra um número vermelho com as chamadas novas para a sua conta (acima de 99 mostra "99+"). Ao clicar, o sistema abre [Chamadas](topico:15-chamadas) e zera a contagem.

## Botão redondo "?" no canto da tela (atalhos)

É outro "?", diferente do manual do topo. Fica no canto da tela. Clique nele (ou passe o mouse) para abrir os dois atalhos:

| Atalho | O que faz |
|---|---|
| **Perguntar à IA** | Abre uma janela pequena "IA Industrial" com ícone para abrir em página inteira. Só aparece se a IA estiver ligada e você não estiver na tela de IA. Veja [IA](topico:21-ia). |
| **Chamar alguém** | Abre o botão de chamada para avisar uma pessoa cadastrada. |

**Esc** fecha o painel da IA e os atalhos.

## Cabeçalho de cada tela

Cada tela mostra o título no formato "Seção — Aba" e uma frase explicando o objetivo. Algumas têm botões de ação à direita (por exemplo **Nova pausa**) e uma barra de filtros ([Filtros](topico:04-filtros-globais)).

Se a atualização dos dados falhar e a tela já tinha dados antigos, aparece o aviso: "Atualização temporariamente indisponível. Os dados exibidos podem estar desatualizados."

A aba **IA** some da barra de abas da Tela inicial quando a IA está desligada no servidor. Enquanto o sistema ainda não respondeu, ou se a consulta falhar, a aba continua aparecendo.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| "Nenhuma tela encontrada" na busca | Nenhuma tela casa com o texto, ou seu nível não a vê. | Tente outra palavra. |
| O sino não mostra número | Não há chamadas novas para a sua conta. | Nada. |
| O "?" do topo abre o manual na página inicial | A tela não tem tópico próprio. | Use a busca do manual. |
| "Atualização temporariamente indisponível…" | O servidor não respondeu na última tentativa. | Aguarde ou recarregue a página. |
