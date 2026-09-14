"""Relógio injetável para serviços Web e simulações isoladas."""


def request_now_func(request):
    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    if settings.simulation_mode and clock is not None:
        return clock.now
    return None
