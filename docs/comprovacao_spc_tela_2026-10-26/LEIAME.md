# Prova visual — tela SPC (26/10/2026)

Dados: **sintéticos** (3 séries inventadas em um servidor de prévia descartável, sem banco). Nada foi gravado em banco nenhum.
Servidor: app real + `web/dist` recém-compilado, usuário simulado com nível Qualidade.

- `spc-1280-cartas.jpg` — carta X-barra e R em 1280 px: ponto vermelho = fora dos limites, losangos amarelos = 7 do mesmo lado, linhas LSC/LC/LIC, pontos numerados de 1.
- `spc-1024-topo.jpg` — 1024 px: filtros, Cpk, CPU, CPL, rótulo "Cpk dentro da OP/lote (variação curta); não é a capacidade da máquina." (vem do servidor, não é escrito na tela).
- `spc-amostra-insuficiente.jpg` — série com 6 medidas: Cpk mostra o motivo, "Não calculado", aviso âmbar; carta sem limites.
- `spc-1024-filtro-vazio.jpg` — filtro sem resultado: "Sem medições suficientes".

Console: sem erro do SPC (`/api/v1/quality/spc` → 200). Os 500 vistos são só do sino de chamadas (`/chamadas/nao-vistas`), porque o banco falso da prévia não tem essa consulta.

## Eu fiz certo? Por quê?
Sim, no que a tela promete: ela só lê e mostra; Cpk, limites e sinais vêm prontos do servidor (nada recalculado no navegador), e o rótulo do Cpk de cada série vem do campo `rotulo_cpk`. Corrigido na revisão: pontos eram numerados a partir de 0, agora de 1.
Não provado aqui: dados reais do chão de fábrica (TEST/REAL não têm medições) e TV (tela não é de TV).
Limite conhecido: só Qualidade e administração acessam (mesma trava de "Cotas padrão"); gestão/supervisor recebem 403 — abrir para eles exige mudar a permissão no servidor.
