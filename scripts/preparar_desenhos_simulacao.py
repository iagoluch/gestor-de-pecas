"""Cria a massa de desenhos (PDF) usada pela simulação da Wave 5.

O caminho oficial da engenharia é uma pasta de rede (``\\\\servidor\\...``,
publicada no Windows como ``G:``). Nem sempre ela está acessível do ambiente de
homologação, e a simulação não pode depender disso para provar o visualizador.

Este script cria uma **raiz local equivalente**, com três situações que o
prompt exige demonstrar:

* peça com um único desenho;
* peça com vários candidatos, escolhida pelo ``LastWriteTime`` mais recente;
* peça sem desenho nenhum (estado vazio, sem erro técnico).

Nada aqui escreve no banco. O backend continua sendo quem resolve o arquivo, e
o operador continua sem escolher pasta.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RAIZ_PADRAO = PROJECT_ROOT / "dados" / "desenhos_simulacao"

# Peças com desenho. O sufixo NÃO é interpretado: ele existe justamente para
# provar que a seleção usa a data de modificação, e não o nome.
DESENHOS = {
    # produto: [(sufixo, minutos de defasagem em relação à referência)]
    "SIMPRD000001": [("", 0)],
    "SIMPRD000003": [("", 0), ("_m", 90), ("_rev2", 30), ("_a", 240)],
    "SIMPRD000015": [("", 0), ("_rev1", 45)],
    "SIMPRD000016": [("", 0)],
    "SIMPRD000017": [("", 0), ("_m", 15)],
    "SIMCARGA0001": [("", 0)],
    "SIMCARGA0005": [("", 0), ("_rev3", 120)],
    "SIMCARGA0013": [("", 0)],
    "SIMCARGA0021": [("", 0), ("_a", 60), ("_m", 10)],
    "SIMCARGA0033": [("", 0)],
    "SIMCARGA0045": [("", 0)],
    "SIMCARGA0061": [("", 0)],
}

# Peças propositalmente SEM desenho, para o estado vazio do card.
SEM_DESENHO = ("SIMPRD000002", "SIMPRD000019", "SIMCARGA0002", "SIMCARGA0017")

REFERENCIA = datetime(2026, 9, 12, 9, 0, 0)


def _pdf(produto: str, rotulo: str) -> bytes:
    """PDF mínimo, válido e legível pelo visualizador embutido do navegador."""

    texto = f"{produto} {rotulo}".strip()
    conteudo = (
        f"BT /F1 24 Tf 60 720 Td (DESENHO SIMULADO) Tj ET\n"
        f"BT /F1 16 Tf 60 680 Td ({texto}) Tj ET\n"
        f"BT /F1 11 Tf 60 650 Td (Gestor de Pecas - massa de simulacao Wave 5) Tj ET\n"
    ).encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(conteudo)).encode() + b" >>\nstream\n" + conteudo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for indice, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += f"{indice} 0 obj\n".encode() + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n".encode()
    saida += b"0000000000 65535 f \n"
    for offset in offsets:
        saida += f"{offset:010d} 00000 n \n".encode()
    saida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(saida)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    parser.add_argument("--limpar", action="store_true", help="Remove os PDFs antes de recriar.")
    args = parser.parse_args()

    raiz: Path = args.raiz
    if args.limpar and raiz.is_dir():
        for arquivo in raiz.rglob("*.pdf"):
            arquivo.unlink()
    raiz.mkdir(parents=True, exist_ok=True)

    criados = 0
    for produto, variantes in DESENHOS.items():
        # Subpasta por peça em metade dos casos: a varredura precisa funcionar
        # com e sem subpasta, como na rede real da engenharia.
        pasta = raiz / produto[-2:] if len(variantes) > 1 else raiz
        pasta.mkdir(parents=True, exist_ok=True)
        for sufixo, atraso in variantes:
            caminho = pasta / f"{produto}{sufixo}.pdf"
            caminho.write_bytes(_pdf(produto, sufixo or "(sem sufixo)"))
            instante = (REFERENCIA + timedelta(minutes=atraso)).timestamp()
            os.utime(caminho, (instante, instante))
            criados += 1

    print(f"Raiz de desenhos: {raiz}")
    print(f"Arquivos criados: {criados}")
    print(f"Peças com desenho: {len(DESENHOS)}")
    print(f"Peças sem desenho (estado vazio esperado): {', '.join(SEM_DESENHO)}")
    print(
        "\nConfigure a variável de ambiente para o backend resolver a rede:\n"
        f'  GESTOR_OPERATOR_DRAWING_ROOTS={raiz}'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
