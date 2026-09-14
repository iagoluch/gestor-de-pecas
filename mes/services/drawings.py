"""Localização do desenho (PDF) da peça a partir da OP — Wave 5.

O operador nunca escolhe pasta, nunca procura arquivo, nunca instala leitor e
nunca acessa uma unidade mapeada do Windows. Ele digita a OP; o **backend**
resolve o produto, varre os caminhos de rede configurados pela gestão e
devolve um único candidato: o de ``LastWriteTime`` mais recente.

Duas decisões funcionais registradas:

* **Sufixo não é versão.** ``PECA123.pdf``, ``PECA123_m.pdf``, ``PECA123_a.pdf``
  e ``PECA123_rev2.pdf`` são candidatos equivalentes. Interpretar ``_rev2`` como
  "mais novo" seria inventar uma convenção que a engenharia não garante. A
  ordem é exclusivamente a data de modificação do arquivo.
* **Ausência não é erro.** Uma peça sem desenho devolve estado vazio com motivo
  de negócio. Traceback, caminho de rede e erro de I/O nunca chegam à tela do
  operador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
from pathlib import Path

from app.core.normalization import limpa_codigo


# Extensão aceita. O visualizador embutido do navegador lê PDF nativamente; é
# isso que permite "tudo dentro da aplicação web", sem leitor instalado.
DRAWING_EXTENSION = ".pdf"

# Limite de arquivos examinados por raiz. Uma pasta de engenharia com dezenas de
# milhares de arquivos não pode transformar a abertura de uma OP em varredura
# interminável no terminal do chão de fábrica.
MAX_CANDIDATES_SCANNED = 4000

# Motivos de negócio devolvidos ao operador.
REASON_OK = "disponivel"
REASON_NOT_CONFIGURED = "nao_configurado"
REASON_NO_PRODUCT = "produto_nao_identificado"
REASON_NOT_FOUND = "sem_desenho"
REASON_UNAVAILABLE = "origem_indisponivel"


@dataclass(frozen=True)
class DrawingCandidate:
    path: Path
    filename: str
    modified_at: datetime
    size_bytes: int

    def como_dicionario(self) -> dict:
        return {
            "filename": self.filename,
            "modified_at": self.modified_at,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class DrawingLookup:
    """Resultado da busca, já pronto para virar card ou estado vazio."""

    available: bool
    reason: str
    op: str = ""
    produto: str = ""
    produto_descricao: str = ""
    selected: DrawingCandidate | None = None
    candidates: tuple[DrawingCandidate, ...] = field(default_factory=tuple)
    message: str = ""

    @property
    def path(self) -> Path | None:
        return self.selected.path if self.selected else None

    def como_dicionario(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "op": self.op,
            "produto": self.produto,
            "produto_descricao": self.produto_descricao,
            "message": self.message,
            "filename": self.selected.filename if self.selected else None,
            "modified_at": self.selected.modified_at if self.selected else None,
            "size_bytes": self.selected.size_bytes if self.selected else None,
            "candidates": [item.como_dicionario() for item in self.candidates],
            "candidate_count": len(self.candidates),
        }


def parse_drawing_roots(raw) -> tuple[Path, ...]:
    """Lê a configuração gerencial de caminhos de rede.

    Aceita ``;`` como separador porque um caminho UNC do Windows contém ``\\``
    e uma unidade mapeada contém ``:`` — nenhum dos dois serve de separador.
    """

    texto = str(raw or "").strip()
    if not texto:
        return ()
    caminhos = []
    for parte in texto.split(";"):
        valor = parte.strip().strip('"')
        if valor:
            caminhos.append(Path(valor))
    return tuple(caminhos)


class DrawingLookupService:
    """Resolve o desenho da peça de uma OP, sem expor a rede ao operador."""

    def __init__(self, db, *, roots=(), max_scanned=MAX_CANDIDATES_SCANNED):
        self.db = db
        self.roots = tuple(Path(item) for item in roots or ())
        self.max_scanned = int(max_scanned or MAX_CANDIDATES_SCANNED)

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.roots)

    def resolver_produto(self, op) -> tuple[str, str]:
        """Produto e descrição da OP, lidos do catálogo local canônico."""

        codigo = limpa_codigo(op)
        if not codigo:
            return "", ""
        for nome in ("buscar_op_planejada", "buscar_op_por_codigo"):
            finder = getattr(self.db, nome, None)
            if not callable(finder):
                continue
            try:
                linha = finder(codigo)
            except Exception:  # pragma: no cover - catálogo indisponível
                logging.exception("Falha ao resolver o produto da OP %s.", codigo)
                continue
            if linha:
                dados = dict(linha)
                produto = str(dados.get("produto_codigo") or "").strip()
                if produto:
                    return produto, str(dados.get("produto_descricao") or "").strip()
        return "", ""

    def buscar(self, op, *, produto=None) -> DrawingLookup:
        """Busca o desenho da OP e devolve sempre um estado apresentável."""

        codigo = limpa_codigo(op)
        produto_codigo = str(produto or "").strip()
        descricao = ""
        if not produto_codigo:
            produto_codigo, descricao = self.resolver_produto(codigo)
        if not self.configured:
            return DrawingLookup(
                False,
                REASON_NOT_CONFIGURED,
                op=codigo,
                produto=produto_codigo,
                produto_descricao=descricao,
                message="O caminho dos desenhos ainda não foi configurado.",
            )
        if not produto_codigo:
            return DrawingLookup(
                False,
                REASON_NO_PRODUCT,
                op=codigo,
                message="Não foi possível identificar a peça desta OP.",
            )
        try:
            candidatos = self._candidatos(produto_codigo)
        except Exception:  # pragma: no cover - rede indisponível
            logging.exception("Falha ao varrer os desenhos do produto %s.", produto_codigo)
            return DrawingLookup(
                False,
                REASON_UNAVAILABLE,
                op=codigo,
                produto=produto_codigo,
                produto_descricao=descricao,
                message="O desenho não está acessível no momento.",
            )
        if not candidatos:
            return DrawingLookup(
                False,
                REASON_NOT_FOUND,
                op=codigo,
                produto=produto_codigo,
                produto_descricao=descricao,
                message="Nenhum desenho disponível para esta peça.",
            )
        return DrawingLookup(
            True,
            REASON_OK,
            op=codigo,
            produto=produto_codigo,
            produto_descricao=descricao,
            selected=candidatos[0],
            candidates=tuple(candidatos),
            message="Desenho disponível.",
        )

    # ------------------------------------------------------------------
    def _candidatos(self, produto_codigo) -> list[DrawingCandidate]:
        """Arquivos da mesma peça, do mais recente para o mais antigo."""

        alvo = str(produto_codigo).strip().casefold()
        encontrados: dict[str, DrawingCandidate] = {}
        examinados = 0
        for raiz in self.roots:
            if examinados >= self.max_scanned:
                break
            if not raiz.is_dir():
                # Raiz configurada porém indisponível não invalida as outras.
                logging.warning("Raiz de desenhos indisponível: %s", raiz)
                continue
            for caminho in self._varrer(raiz):
                examinados += 1
                if examinados > self.max_scanned:
                    logging.warning(
                        "Varredura de desenhos interrompida em %s arquivos.",
                        self.max_scanned,
                    )
                    break
                nome = caminho.name
                if not nome.casefold().endswith(DRAWING_EXTENSION):
                    continue
                base = nome[: -len(DRAWING_EXTENSION)].casefold()
                # O sufixo não é interpretado: basta a peça ser o começo do
                # nome, seguida de fim de nome ou de um separador conhecido.
                if base != alvo and not base.startswith(f"{alvo}_") and not base.startswith(
                    f"{alvo}-"
                ):
                    continue
                try:
                    info = caminho.stat()
                except OSError:  # pragma: no cover - arquivo sumiu no meio
                    continue
                chave = str(caminho).casefold()
                encontrados[chave] = DrawingCandidate(
                    path=caminho,
                    filename=nome,
                    modified_at=datetime.fromtimestamp(info.st_mtime).replace(
                        microsecond=0
                    ),
                    size_bytes=int(info.st_size),
                )
        return sorted(
            encontrados.values(),
            key=lambda item: (item.modified_at, item.filename),
            reverse=True,
        )

    @staticmethod
    def _varrer(raiz: Path):
        """Percorre a raiz e as subpastas sem estourar em link quebrado."""

        for pasta, _subpastas, arquivos in os.walk(raiz, onerror=None):
            base = Path(pasta)
            for nome in arquivos:
                yield base / nome


__all__ = [
    "DRAWING_EXTENSION",
    "DrawingCandidate",
    "DrawingLookup",
    "DrawingLookupService",
    "REASON_NOT_CONFIGURED",
    "REASON_NOT_FOUND",
    "REASON_NO_PRODUCT",
    "REASON_OK",
    "REASON_UNAVAILABLE",
    "parse_drawing_roots",
]
