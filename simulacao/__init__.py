"""Simulação industrial prolongada (soak test) do Gestor de Peças.

O pacote executa uma fábrica virtual contra a aplicação TESTE real: relógio
virtual acelerado, operadores concorrentes, apontamentos pelos mesmos endpoints
que o chão de fábrica usa, observabilidade de API/PostgreSQL e um observatório
que exibe as telas reais dos operadores simulados.

Fronteiras absolutas (documento SIMULACAO_INDUSTRIAL_PROLONGADA_OBSERVABILIDADE,
seções 1 e 46):

* só roda contra ``gestor_pecas_test``;
* nunca escreve no banco REAL, no TOTVS ou no SigmaNEST;
* nunca fabrica execução por SQL — toda ordem nasce do pipeline canônico de
  ingestão e todo apontamento passa pela API HTTP;
* nunca mascara erro: recusa esperada e defeito real são classificados
  separadamente e ambos ficam registrados.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
