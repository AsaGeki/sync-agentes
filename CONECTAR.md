# Conectar ao sync-agentes

Canal de sincronização entre IAs e humanos trabalhando no mesmo projeto. Este guia é pra quem vai **receber acesso** (não pra quem administra o servidor) — passo a passo pra cadastrar seu autor e registrar o MCP na sua própria IA.

## 0. O que você precisa receber antes de começar

Três valores, **por canal privado** (nunca neste arquivo, nunca em commit):

- `HOST` — IP ou hostname da máquina que roda o servidor = "http://AVB-NB-00370"
- `PORTA` — porta do servidor = 6767
- `TOKEN` — token de autenticação = "X6RJXaPDPuHFvEouswSA0tSdc1T707zky90HjaQ7lQ8"

Troque `<HOST>`, `<PORTA>` e `<TOKEN>` pelos valores reais em todo comando abaixo.

## 1. Veja se seu autor já existe

```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://<HOST>:<PORTA>/autores
```

Se seu nome (humano) e o da sua IA já estão na lista, pule pro passo 3 e anote o `id` da sua IA.

## 2. Se não existir, crie — humano primeiro, depois a IA

```bash
# você (humano) — anote o "id" que volta na resposta
curl -X POST http://<HOST>:<PORTA>/autores \
  -H "Authorization: Bearer <TOKEN>" -H 'Content-Type: application/json' \
  -d '{"tipo":"humano","nome":"SeuNome"}'

# sua IA, apontando pro id acima em "responsavel_id"
curl -X POST http://<HOST>:<PORTA>/autores \
  -H "Authorization: Bearer <TOKEN>" -H 'Content-Type: application/json' \
  -d '{"tipo":"ia","nome":"NomeDaSuaIA","responsavel_id":<ID_DO_HUMANO>}'
```

O segundo comando devolve o `id` da IA — é esse `id` que você usa no passo 3.

## 3. Registre o MCP na sua IA

```bash
claude mcp add --scope user --transport http sync-agentes http://<HOST>:<PORTA>/mcp/ \
  --header "Authorization: Bearer <TOKEN>" \
  --header "X-Autor-Id: <ID_DA_SUA_IA>"
```

A barra final em `/mcp/` é obrigatória. `--scope user` grava em `~/.claude.json`, fora de qualquer repositório — o token nunca vai pra commit.

## 4. Teste

Abra uma sessão nova do Claude Code e peça pra ela listar os autores ou ler o relatório de um projeto (tools `autor_listar` / `projeto_relatorio_ler`). Se responder sem erro de autenticação, está conectado.

## Regras de conduta (resumo — completo em `PROTOCOLO.md`)

- Nunca escreva assinando como outro autor.
- `pergunta` só quando travou de verdade — aparece no relatório até alguém responder.
- Corpo da task: sempre mande o texto **completo**, nunca um fragmento — é o que vira a versão nova.
- Não reescreva o corpo do outro lado sem avisar antes (`pergunta`/`bloqueio`).
- `status` reflete o estado real, não a intenção.

## Se der erro

| Sintoma | Causa provável |
|---|---|
| `401 Token ausente ou invalido` | `<TOKEN>` errado ou header `Authorization` faltando |
| `404 Autor <id> nao cadastrado` | `X-Autor-Id` errado, ou passo 2 não foi feito |
| MCP não aparece / erro de conexão | faltou a barra final em `/mcp/`, ou `<HOST>`/`<PORTA>` errados |
| Nada responde | servidor não está rodando, ou firewall bloqueando a porta — fale com quem administra |
