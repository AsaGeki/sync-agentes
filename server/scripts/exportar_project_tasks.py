"""Executa a exportação para o Project Tasks MCP pela linha de comando."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.modules.projects.exportacao import main  # noqa: E402, I001


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        sys.exit(1)
