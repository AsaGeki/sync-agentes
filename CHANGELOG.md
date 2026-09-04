# Changelog

Formato livre, mais recente no topo. Versao segue `app/main.py` (`FastAPI(version=...)`), exposta em `GET /health`.

## 1.1.0

- `GET /health` devolve `versao` (contrato/versao da API).
- Migracao de schema real: coluna nova numa tabela existente agora e aplicada em banco ja criado, nao so em banco novo. Ver `app/db.py` (`MIGRACOES`).

## 1.0.0

- Primeira versao: `autores`, `projetos`, `tasks`, `dependencias`, `corpos` (versionado, com diff), `eventos` (trilha unica). Contrato REST + mesmo contrato como servidor MCP em `/mcp/`. Tempo real via WebSocket (`/ws`) e SSE (`/stream`).
