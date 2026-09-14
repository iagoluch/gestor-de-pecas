# Arquitetura-alvo Web

A arquitetura-alvo foi promovida para arquitetura vigente em 24/08/2026.

## Interface única

- React/TypeScript nos navegadores dos postos e gestores;
- FastAPI como único adaptador de entrada do sistema;
- SSE para atualização operacional em tempo real;
- build de `web/dist` entregue pelo próprio backend quando habilitado;
- nenhuma instalação de runtime gráfico Python nos terminais.

## Regras invariantes

- domínio e analytics não importam React nem FastAPI;
- frontend não consulta banco nem calcula OEE, FTT, rateio ou saldo;
- repositórios não mantêm mapas funcionais concorrentes com o domínio;
- nenhuma rota genérica edita ou exclui evento produtivo histórico;
- integração corporativa continua por gateway neutro e depende da TI.

## Evolução

Novos módulos devem adaptar os mesmos contratos e casos de uso. Checklist,
Andon, mensageria, IA, manutenção, CEP e demais evoluções não fazem parte desta
consolidação.
