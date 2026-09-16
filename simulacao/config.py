"""Parâmetros da simulação industrial prolongada.

A velocidade virtual **nunca** é digitada: ela é derivada de
``factory_duration / duration``, como manda a seção 2 do documento. Tudo o que
varia entre execuções (duração, seed, janela virtual, portas) entra por CLI ou
pelo JSON de configuração; o código não guarda constante escondida.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "simulacao_industrial.json"
RUNS_ROOT = PROJECT_ROOT / "simulation_runs"

#: Banco único autorizado. Qualquer outro alvo aborta o preflight.
EXPECTED_DATABASE = "gestor_pecas_test"
#: Banco proibido. O nome existe aqui para ser comparado, nunca para ser usado.
FORBIDDEN_DATABASE = "gestor_pecas"


@dataclass(frozen=True)
class Posto:
    """Um posto físico da fábrica simulada.

    ``login`` é a identidade da tela (o perfil do Gestor) e ``cracha`` é a
    identidade do operador que aparece nas participações. Os dois existem
    separados porque o Gestor modela exatamente assim: o setor vem do perfil e
    a pessoa vem do crachá.
    """

    id: str
    setor: str
    recurso: str
    login: str
    cracha: str
    fluxo: str  # "bancada" | "corte" | "destaque"
    nome: str


@dataclass(frozen=True)
class Fase:
    """Janela de carga dentro do turno virtual (seção 8)."""

    nome: str
    inicio: str  # HH:MM virtual
    ocupacao_alvo: float  # fração dos postos que tenta estar ocupada


@dataclass(frozen=True)
class SimulationConfig:
    seed: int
    duration_seconds: float
    factory_seconds: float
    virtual_start: datetime
    api_base: str
    api_port: int
    observatory_port: int
    viewport_base_port: int
    sim_password: str
    postos: tuple[Posto, ...]
    fases: tuple[Fase, ...]
    autorizador_cracha: str
    cracha_invalido: str
    crachas_apoio: tuple[str, ...]
    processo_minutos: dict[str, tuple[int, int]]
    comportamento: dict[str, float]
    thresholds: dict[str, float]
    ingestao: dict[str, object]
    selecao_postos: dict[str, object]
    checkpoints: tuple[dict[str, str], ...]
    calendar: dict[str, object]
    run_dir: Path = field(default=RUNS_ROOT)

    # ------------------------------------------------------------------
    @property
    def time_scale(self) -> float:
        """Velocidade virtual derivada — seção 2."""

        return self.factory_seconds / self.duration_seconds

    @property
    def virtual_end(self) -> datetime:
        return self.virtual_start + timedelta(seconds=self.factory_seconds)

    def com_inicio_virtual(self, novo_inicio: datetime) -> "SimulationConfig":
        """Devolve a mesma configuração com outra âncora de início virtual.

        Usado quando o TESTE já carrega histórico à frente da janela pedida:
        a janela é deslocada em semanas inteiras, e todo o resto (fases,
        checkpoints, durações) continua ancorado no novo início.
        """

        return replace(self, virtual_start=novo_inicio)

    def virtual_at(self, hhmm: str) -> datetime:
        """Resolve ``HH:MM`` dentro da janela virtual.

        Um horário anterior ao início da janela pertence ao **passado** dela —
        é uma fase que já começou —, e só é empurrado para o dia seguinte quando
        a própria janela atravessa a meia-noite.
        """

        hour, minute = (int(part) for part in hhmm.split(":"))
        candidate = self.virtual_start.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < self.virtual_start and self.virtual_end.date() > self.virtual_start.date():
            candidate += timedelta(days=1)
        return candidate

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "duracao_real_segundos": self.duration_seconds,
            "duracao_virtual_segundos": self.factory_seconds,
            "velocidade_virtual": round(self.time_scale, 6),
            "inicio_virtual": self.virtual_start.isoformat(),
            "fim_virtual": self.virtual_end.isoformat(),
            "api_base": self.api_base,
            "banco_esperado": EXPECTED_DATABASE,
            "banco_proibido": FORBIDDEN_DATABASE,
            "observatorio": f"http://127.0.0.1:{self.observatory_port}/",
            "viewport_base_port": self.viewport_base_port,
            "postos": [
                {
                    "id": posto.id,
                    "setor": posto.setor,
                    "recurso": posto.recurso,
                    "login": posto.login,
                    "cracha": posto.cracha,
                    "fluxo": posto.fluxo,
                    "nome": posto.nome,
                }
                for posto in self.postos
            ],
            "fases": [
                {"nome": fase.nome, "inicio": fase.inicio, "ocupacao_alvo": fase.ocupacao_alvo}
                for fase in self.fases
            ],
            "crachas": {
                "autorizador": self.autorizador_cracha,
                "invalido": self.cracha_invalido,
                "apoio": list(self.crachas_apoio),
            },
            "processo_minutos": {k: list(v) for k, v in self.processo_minutos.items()},
            "comportamento": self.comportamento,
            "thresholds": self.thresholds,
            "ingestao": self.ingestao,
            "selecao_postos": self.selecao_postos,
            "checkpoints": [dict(item) for item in self.checkpoints],
            "calendar": self.calendar,
        }


def _parse_duration(text: str) -> float:
    """Aceita ``60m``, ``8h``, ``90s`` e ``3600``."""

    value = str(text or "").strip().lower()
    if not value:
        raise ValueError("duração vazia")
    multiplier = 1.0
    if value.endswith("h"):
        multiplier, value = 3600.0, value[:-1]
    elif value.endswith("m"):
        multiplier, value = 60.0, value[:-1]
    elif value.endswith("s"):
        multiplier, value = 1.0, value[:-1]
    number = float(value.replace(",", "."))
    if number <= 0:
        raise ValueError("duração deve ser positiva")
    return number * multiplier


def load_config(
    *,
    duration: str = "60m",
    factory_duration: str = "8h",
    seed: int = 20260912,
    virtual_start: str | None = None,
    api_port: int | None = None,
    observatory_port: int | None = None,
    ops_iniciais: int | None = None,
    ops_continuas: int | None = None,
    config_file: Path = CONFIG_FILE,
) -> SimulationConfig:
    raw = _load_config_file(Path(config_file))
    if ops_iniciais is not None:
        raw["ingestao"]["lote_inicial"] = max(0, int(ops_iniciais))
    if ops_continuas is not None:
        raw["ingestao"]["lote_continuo"] = max(0, int(ops_continuas))

    postos = tuple(
        Posto(
            id=item["id"],
            setor=item["setor"],
            recurso=item["recurso"],
            login=item["login"],
            cracha=item["cracha"],
            fluxo=item["fluxo"],
            nome=item["nome"],
        )
        for item in raw["postos"]
    )
    fases = tuple(
        Fase(nome=item["nome"], inicio=item["inicio"], ocupacao_alvo=float(item["ocupacao_alvo"]))
        for item in raw["fases"]
    )
    selecao_postos = dict(raw.get("selecao_postos") or {"modo": "vinculo_operacional_backend"})
    if selecao_postos.get("modo") != "vinculo_operacional_backend":
        raise ValueError("selecao_postos.modo deve ser vinculo_operacional_backend.")
    start_text = virtual_start or raw["relogio"]["inicio_virtual"]
    return SimulationConfig(
        seed=int(seed),
        duration_seconds=_parse_duration(duration),
        factory_seconds=_parse_duration(factory_duration),
        virtual_start=datetime.fromisoformat(start_text),
        api_base=f"http://127.0.0.1:{api_port or raw['api']['porta']}",
        api_port=int(api_port or raw["api"]["porta"]),
        observatory_port=int(observatory_port or raw["observatorio"]["porta"]),
        viewport_base_port=int(raw["observatorio"]["viewport_base_port"]),
        sim_password=str(raw["credenciais"]["senha_simulacao"]),
        postos=postos,
        fases=fases,
        autorizador_cracha=str(raw["crachas"]["autorizador"]),
        cracha_invalido=str(raw["crachas"]["invalido"]),
        crachas_apoio=tuple(raw["crachas"]["apoio"]),
        processo_minutos={
            key: (int(value[0]), int(value[1]))
            for key, value in raw["processo_minutos"].items()
        },
        comportamento={k: float(v) for k, v in raw["comportamento"].items()},
        thresholds={k: float(v) for k, v in raw["thresholds"].items()},
        ingestao=raw["ingestao"],
        selecao_postos=selecao_postos,
        checkpoints=tuple(raw["checkpoints"]),
        calendar=dict(raw.get("calendar") or {}),
    )


def _merge_config(base: dict, override: dict) -> dict:
    """Merge a scenario overlay without mutating the reusable base config."""

    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config_file(config_file: Path) -> dict:
    raw = json.loads(config_file.read_text(encoding="utf-8"))
    base_name = raw.pop("base_config", None)
    if not base_name:
        return raw
    base_file = (config_file.parent / str(base_name)).resolve()
    if base_file == config_file.resolve():
        raise ValueError("base_config não pode referenciar o próprio arquivo.")
    return _merge_config(_load_config_file(base_file), raw)
