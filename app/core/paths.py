"""Caminhos de filesystem compartilhados pelo backend Web."""

import os
import sys


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_path(relative_path):
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = base_dir()
    return os.path.join(base_path, relative_path)


DADOS_DIR = os.path.join(base_dir(), "dados")
CONFIG_PATH = os.path.join(DADOS_DIR, "config.ini")


def ensure_data_dir():
    os.makedirs(DADOS_DIR, exist_ok=True)
    return DADOS_DIR
