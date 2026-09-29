# CODE_STYLE.md — Gestor de Peças

Extraído do `AGENTS.md` em 2026-09-29; tem a mesma força normativa do `AGENTS.md`.

## Regras de codificação e arquivos

- Todos os arquivos de texto novos/alterados devem ser UTF-8.
- Preservar corretamente acentos: `Peças`, `Produção`, `Operação`, `Máquina`, `Interrupção`, etc.
- Não aceitar nomes ou conteúdos com mojibake, escapes Unicode indevidos ou caracteres de substituição.
- Antes de empacotar, varrer nomes e conteúdo por corrupção de Unicode.


## Compatibilidade

Durante refatorações:

- atualizar imports internos para a arquitetura atual;
- evitar dependência circular;
- não recriar wrappers antigos na raiz sem necessidade real;
- não apagar arquivo sem confirmar que não existe import ativo;
- não duplicar lógica entre arquivos antigos e novos.

Wrappers temporários são permitidos apenas se ainda houver compatibilidade necessária.

Wrappers não devem conter regra duplicada.
