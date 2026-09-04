import uvicorn

from app.config import HOST, PORT
from app.db import DB_PATH
from app.main import app


def main() -> None:
    print(f"Banco:  {DB_PATH}")
    print(f"Docs:   http://{HOST}:{PORT}/docs")
    if HOST == "0.0.0.0":
        print("AVISO: exposto na rede. Firewall e escopo de acesso sao sua responsabilidade.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
