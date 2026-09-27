# Governança

## Autoridade
1. decisão explícita de Iago / Engenharia de Manufatura;
2. `AGENTS.md`;
3. código e testes atuais;
4. documentação atual;
5. evidência externa;
6. inferência.

Inferência nunca vira regra industrial por decisão de agente.

## Aprovação humana obrigatória
- regra industrial nova/ambígua;
- destruição/reescrita em REAL;
- envio real ao TOTVS;
- escrita em máquina/PLC/OT;
- segredo/credencial;
- ação externa irreversível;
- relaxamento de gate de segurança.

## Invariantes
- regra industrial não vai para frontend/transporte;
- dado ausente não vira valor inventado;
- teste/gate não é mascarado;
- segurança não é reduzida para "funcionar";
- MCP/ferramenta não vira dependência do runtime MES;
- credencial não é versionada;
- produção não é ambiente de experimento.

## Revisão
R2/R3 exigem olhos independentes. `technical-reviewer` é read-only por padrão.

## Contexto/custo
Graphify e busca dirigida primeiro; skills on-demand; subagentes por isolamento real; MCP apenas quando agrega dados/ferramenta externa; parar quando a evidência basta.

## Commits
Mensagem descreve intenção/efeito. Nunca usar saída de `git status` como mensagem.
