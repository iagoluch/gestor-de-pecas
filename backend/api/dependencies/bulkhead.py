from fastapi import Request


async def management_read_slot(request: Request):
    """Bulkhead das leituras gerenciais (BK-01).

    Painéis de gestão, análises e relatórios fazem dezenas de consultas por
    requisição. Sem teto próprio, alguns gestores atualizando a tela disputam
    CPU e conexões com o operador que aperta Início no chão de fábrica. Só GET
    entra na fila: gravações da gestão (pausas, turnos, usuários) seguem direto.
    """

    if request.method != "GET":
        yield
        return
    async with request.app.state.management_read_limiter:
        yield
