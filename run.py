import uvicorn

from src.main import app
from src.shared.config import HOST, PORT
from src.shared.db import DB_PATH


def main() -> None:
    print(f"Banco:  {DB_PATH}")
    print(f"Docs:   http://{HOST}:{PORT}/docs")
    if HOST == "0.0.0.0":
        print("AVISO: exposto na rede. Firewall e escopo de acesso sao sua responsabilidade.")
    # Sessao MCP Streamable HTTP mantem conexao aberta esperando push do servidor -
    # sem teto, o shutdown gracioso do uvicorn espera essa conexao fechar pra sempre.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
