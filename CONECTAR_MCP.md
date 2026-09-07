# Conectar via MCP — sync-agents

Este arquivo é pra qualquer IA (ou humano configurando uma) que vai operar o canal: o que é o projeto, o modelo de dados, e como conectar. As regras do dia a dia — quando usar cada tipo de mensagem, o que fazer antes de responder, como não pisar no corpo do outro lado — **não estão aqui**: vêm embutidas nas `instructions` do próprio servidor MCP (`src/mcp_server.py`) e todo cliente MCP mostra isso pra IA automaticamente assim que conecta. Duplicar aqui seria o mesmo texto em 2 lugares, e só um deles a IA realmente lê.

## O que é

Canal de alinhamento entre agentes de IA e humanos, por projeto e task — pensado pra 2 lados (2 pessoas, cada uma com sua IA) trabalhando na mesma coisa de máquinas diferentes, sem depender de arquivo markdown compartilhado na mão. Serve pra qualquer projeto: `projetos` é a raiz, `tasks` pendura em projeto, toda escrita fica registrada numa trilha única de eventos (é dali que saem "o que mudou desde X" e o relatório).

## Modelo de dados (resumo)

- **`autores`** — cadastro de quem escreve (IA ou dev). Toda IA tem um `responsible_id` apontando pra um autor `dev` (obrigatório). Autor é quem assina todo evento.
- **`projetos`** — raiz, endereçado por `slug`. Tem `name`, `description`, `git_repositories` (lista de repo git que o projeto usa), `status`, `created_by` (autor que criou).
- **`tasks`** — pendura em projeto, endereçada por `code` (`T-001`, único por projeto). Tem `title`, `status`, `tags`, `owner_id`, e um **corpo versionado** (texto de referência, cada atualização gera diff contra a versão anterior).
- **`eventos`** — trilha única de tudo (task criada, mensagem, campo mudou, corpo novo). Não existe dependência formal entre tasks — se precisar registrar uma relação, é mensagem ou fica no próprio corpo.

**Nomenclatura**: campo estrutural (id, tipo, nome, datas, quem-é-dono) é em inglês — `type`, `name`, `status`, `created_at`, `owner_id`, `code`, `title`, `tags`. Campo de conteúdo livre (o que alguém escreveu) continua português — `texto`, `corpo`, `diff`, `versao`, `campo`, `valor_de`, `valor_para`. As duas coisas convivem na mesma tool/resposta — não é inconsistência, é o critério.

## Como conectar

### 1. Descubra ou crie sua identidade

Toda escrita exige um autor cadastrado. Liste os que já existem:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://$HOST:8787/authors
```

Se seu nome (dev) e o da sua IA já estão na lista, anote o `id` da IA e pule pro passo 2. Senão, crie — dev primeiro, depois a IA apontando pro dev:

```bash
curl -X POST http://$HOST:8787/authors \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"dev","name":"SeuNome"}'
# guarda o "id" da resposta

curl -X POST http://$HOST:8787/authors \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"ia","name":"SuaIA","responsible_id":<ID_DO_DEV>}'
# guarda o "id" da resposta - é o seu
```

### 2. Registre o servidor MCP

Com o `id` da sua IA em mãos, registra uma vez só — depois disso toda operação (criar task, mandar mensagem, ler relatório) existe como tool nativa:

```bash
claude mcp add --scope user --transport http sync-agents http://$HOST:8787/mcp/ \
  --header "Authorization: Bearer $TOKEN" \
  --header "X-Autor-Id: <seu id>"
```

A barra final em `/mcp/` é obrigatória — sem ela o Starlette redireciona (307) e alguns clientes MCP não seguem o redirect. `--scope user` grava em `~/.claude.json`, fora de qualquer repo — o token nunca deve ir pra commit.

Registrado, você nunca mais passa `Authorization`/`X-Autor-Id` como parâmetro — o cliente MCP já leva fixado, e é impossível escrever assinando como outro autor por engano.

### 3. Fique sabendo das mudanças em tempo real

```
Monitor({
  ws: { url: 'ws://<host>:8787/ws?projeto=<slug>&token=<token>&autor_id=<seu id>' },
  description: 'mudancas do outro lado no projeto <slug>',
  persistent: true,
})
```

`autor_id` filtra o próprio eco — você não é notificado do que você mesmo escreveu. Sem WebSocket, faz polling por cursor: `GET /projetos/{slug}/mudancas?desde=<ultimo_cursor>`.

## Se o MCP não estiver disponível

O mesmo contrato existe via REST — contrato inteiro navegável em `http://<host>:8787/docs`. `GET /health` devolve a versão atual; `GET /changelog` devolve o [`CHANGELOG.md`](CHANGELOG.md) — é lá que mudança de contrato fica registrada (rota nova, campo renomeado, comportamento diferente).
