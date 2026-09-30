# sync-agents-mcp

Bridge MCP local do [sync-agents](https://github.com/AsaGeki/sync-agentes): roda na máquina de quem conecta, lê o `.git` da pasta do projeto e conversa com o servidor sync-agents por HTTP. O repositório git onde o chat foi aberto define em qual projeto a IA escreve.

## Rodar

```bash
uvx sync-agents-mcp
```

Não é pra rodar na mão: o app de IA (Claude Code, Cursor, Claude Desktop, VS Code, Codex) executa esse comando como servidor MCP stdio.

## Variáveis de ambiente

| Variável | Pra quê |
|---|---|
| `SYNC_AGENTS_URL` | endereço do servidor (padrão `http://127.0.0.1:8787`) |
| `SYNC_AGENTS_TOKEN` | token pessoal, emitido por quem administra o servidor |
| `SYNC_AGENTS_REPO` | caminho do repositório, só pra app que não abre pasta de projeto (Claude Desktop). Também vale `--repo <caminho>` |

Configuração passo a passo por app: [`CONECTAR_MCP.md`](https://github.com/AsaGeki/sync-agentes/blob/main/CONECTAR_MCP.md).
