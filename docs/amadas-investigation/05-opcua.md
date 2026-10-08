# OPC UA: suporte público e investigação local

**[CERTO, produto]** Fujitsu/AMADA declaram OPC UA no VCBox desde 2017. Fontes oficiais em [01-fontes-publicas.md](01-fontes-publicas.md), itens 2–4.

**[HIPÓTESE, instalação]** Nenhum endpoint OPC UA foi identificado. Não foram feitos GetEndpoints, Browse, Read ou subscription. Não houve busca de portas nos CNC nem tentativa em 4840. Ausência de teste não significa servidor ausente.

| Informação solicitada | Resultado nesta sessão |
|---|---|
| Endpoint/host/porta | Não comprovado |
| Papel VCBox: cliente, servidor ou ambos | Não comprovado |
| SecurityPolicy/SecurityMode | Não comprovados |
| Certificado público/trust list | Nenhum certificado de endpoint coletado |
| Autenticação read-only | Não comprovada; nenhuma credencial procurada/testada |
| NamespaceArray / companion spec | Não coletado |
| Nodes / NodeIds / tipos / valores | Nenhuma amostra real |
| Frequência / limites de sessão | Não medidos |

## Próximo teste condicionado a endpoint comprovado

1. Mostrar alvo exato e procedimento antes do teste. Obter endpoint de configuração/manual/AMADA, não assumir porta.
2. Uma chamada GetEndpoints; registrar políticas e certificado público. Não alterar trust list ou aceitar certificado desconhecido silenciosamente.
3. Com modo/identidade read-only aprovados, ler NamespaceArray e fazer Browse limitado. Começar por poucos nós; não varrer milhares de nodes nem configurar subscription em massa.
4. Read dos nós documentados, salvando NodeId, datatype, valor, unidade, StatusCode, SourceTimestamp e ServerTimestamp. Não fazer Write ou Call.
5. Frequência inicial conservadora definida pelo fabricante; medir latência e tamanho antes de polling/subscription contínuos.

**[HIPÓTESE]** OPC UA for Machine Tools 1.02 é um modelo útil, mas aderência AMADA não comprovada. Não inventar NodeIds a partir da companion specification. O cliente read-only precisará de ações técnicas de sessão, porém nunca de comando de máquina; habilitação, licença, firewall e confiança de certificado exigem autorização separada quando alterarem estado.

Tabela Node → significado → exemplo → frequência → máquina → utilidade: **sem linhas medidas**, pois nenhum node real foi obtido. [07-dados-disponiveis.md](07-dados-disponiveis.md) distingue capacidades comerciais, valores offline e dados ao vivo ainda desconhecidos.
