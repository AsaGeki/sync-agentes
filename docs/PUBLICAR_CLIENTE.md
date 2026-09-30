# Publicar o cliente MCP no PyPI

O cliente (`client/`, pacote `sync-agents-mcp`) é publicado pelo workflow `.github/workflows/publicar-cliente.yml` quando uma tag `client-v*` sobe. Não usa token guardado: o PyPI confia no workflow via Trusted Publishing.

## Configuração única

1. Em [pypi.org](https://pypi.org), com a conta que vai ser dona do pacote, abra **Your account → Publishing → Add a new pending publisher**.
2. Preencha:
   - **PyPI project name:** `sync-agents-mcp`
   - **Owner:** `AsaGeki`
   - **Repository name:** `sync-agentes`
   - **Workflow name:** `publicar-cliente.yml`
   - **Environment name:** `pypi`
3. No GitHub, em **Settings → Environments**, crie o environment `pypi` (pode ficar sem regras; se quiser uma trava, exija aprovação manual).

O publisher pendente vira definitivo na primeira publicação.

## Lançar uma versão

1. Suba a versão em `client/pyproject.toml` (`version = "X.Y.Z"`) e commite.
2. Crie e envie a tag:

   ```bash
   git tag client-vX.Y.Z
   git push origin client-vX.Y.Z
   ```

O workflow confere que a tag bate com a versão do `pyproject`, builda com `uv build --package sync-agents-mcp` e publica.

Mudou algum dos enums em `client/src/sync_agents_mcp/enums.py` ou o contrato das tools? É mudança de cliente: suba a versão e publique de novo.

## Conferir

Abra `https://pypi.org/project/sync-agents-mcp/` e confira a versão. Numa máquina com o MCP registrado, `claude mcp list` deve mostrar `sync-agents` conectado (a primeira checagem depois de publicar pode dar timeout enquanto o `uvx` baixa o pacote).
