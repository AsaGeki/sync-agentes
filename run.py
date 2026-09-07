import asyncio
import logging

import uvicorn

from src.main import app
from src.shared.config import HOST, PORT
from src.shared.db import DB_PATH


class SilenciarCancelamentoShutdown(logging.Filter):
    """Esconde o traceback de CancelledError que o uvicorn loga como erro ao
    forçar o fechamento de sessões MCP Streamable HTTP ainda abertas no shutdown -
    o cancelamento é esperado, não indica falha."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[0] is asyncio.CancelledError:
            return "graceful shutdown" not in str(record.exc_info[1])
        return True


def main() -> None:
    logging.getLogger("uvicorn.error").addFilter(SilenciarCancelamentoShutdown())

    print(f"Banco:  {DB_PATH}")
    print(f"Docs:   http://{HOST}:{PORT}/docs")
    if HOST == "0.0.0.0":
        print("AVISO: exposto na rede. Firewall e escopo de acesso são sua responsabilidade.")
    # Sessão MCP Streamable HTTP mantém conexão aberta esperando push do servidor -
    # sem teto, o shutdown gracioso do uvicorn espera essa conexão fechar pra sempre.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
