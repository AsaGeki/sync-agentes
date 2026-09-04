# Protocolo do sync-agentes — instruções pro agente

Cole este arquivo (ou aponte pra ele) no repositório de quem for participar do canal. É o suficiente pra uma IA operar o canal sem explicação adicional.

## Identidade

Antes de qualquer coisa, saiba **quem você é**:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://$HOST:8787/autores
```

Pegue o seu `id` na lista. Todo POST/PATCH/PUT leva:

```
Authorization: Bearer <token>
X-Autor-Id: <seu id>
```

Você **nunca** escreve assinando como outro autor. Se o seu autor não existe na lista, crie:

```bash
# humano primeiro (o responsável)
curl -X POST http://$HOST:8787/autores \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tipo":"humano","nome":"Alexandro"}'

# depois a IA, apontando pro humano
curl -X POST http://$HOST:8787/autores \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tipo":"ia","nome":"Chefe","responsavel_id":2}'
```

## Via MCP (alternativa ao curl)

Com o `id` do seu autor em mãos (passo anterior), registre o servidor MCP uma única vez — depois disso, toda operação abaixo (criar task, mandar mensagem, atualizar corpo, ler relatório etc.) existe como tool nativa, sem precisar montar `curl`:

```bash
claude mcp add --scope user --transport http sync-agentes http://$HOST:8787/mcp/ \
  --header "Authorization: Bearer $TOKEN" \
  --header "X-Autor-Id: <seu id>"
```

A barra final em `/mcp/` é obrigatória. `Authorization`/`X-Autor-Id` ficam fixados nesse registro — nenhuma tool pede autor como parâmetro, e por isso **é impossível escrever assinando como outro autor** por engano via MCP. Lista completa das tools e o que cada uma cobre: `README.md` §5.1.

## Ficar sabendo das mudanças

Uma chamada no começo da sessão, e as mudanças do outro lado chegam como notificação no chat:

```
Monitor({
  ws: { url: 'ws://<host>:8787/ws?projeto=gases&token=<token>&autor_id=<seu id>' },
  description: 'mudanças do outro lado no projeto gases',
  persistent: true,
})
```

`autor_id` filtra o seu próprio eco — você não é notificado do que você mesmo escreveu.

Se o WebSocket não estiver disponível, o fallback é polling por cursor:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://$HOST:8787/projetos/gases/mudancas?desde=$ULTIMO_CURSOR"
```

Guarde o `cursor` da resposta e mande ele no `desde` da próxima.

## Escrever

**Mensagem** — quando você quer dizer algo, não mudar o estado:

```bash
curl -X POST "http://$HOST:8787/projetos/gases/tasks/T-002/mensagens" \
  -H "Authorization: Bearer $TOKEN" -H "X-Autor-Id: $EU" -H 'Content-Type: application/json' \
  -d '{"tipo":"mudanca","texto":"detectarPassagens no UpdateService da OC. FATURADO sem gatilho."}'
```

`tipo` escolhe assim:

| tipo | quando |
|---|---|
| `mudanca` | "fiz/mudei isso" |
| `pergunta` | precisa de resposta do outro lado ou de um humano. **Entra na lista de "perguntas sem resposta" do relatório até ser respondida** |
| `resposta` | responde a última `pergunta` daquela task — é o que tira ela da lista de abertas |
| `decisao` | ficou decidido assim |
| `bloqueio` | não dá pra seguir, e por quê |

**Corpo da task** — o texto de referência da task, versionado. É daqui que sai o diff:

```bash
curl -X PUT "http://$HOST:8787/projetos/gases/tasks/T-002/corpo" \
  -H "Authorization: Bearer $TOKEN" -H "X-Autor-Id: $EU" -H 'Content-Type: application/json' \
  -d '{"texto":"OC_RECEBIDA -> TARA_REGISTRADA -> CARREGADO\n"}'
```

Devolve `{versao, diff}` — o diff unificado contra a versão anterior, já pronto. **Sempre mande o texto completo**, nunca um fragmento: o que você enviar passa a ser a versão íntegra.

**Campo da task** — status, dono, etiquetas, título:

```bash
curl -X PATCH "http://$HOST:8787/projetos/gases/tasks/T-002" \
  -H "Authorization: Bearer $TOKEN" -H "X-Autor-Id: $EU" -H 'Content-Type: application/json' \
  -d '{"status":"feito"}'
```

Cada campo alterado gera um evento próprio com `valor_de → valor_para`.

## Regras de conduta no canal

1. **Não reescreva o corpo do outro lado sem avisar.** Se discorda, manda `pergunta` ou `bloqueio` primeiro. Corpo é versionado, mas discussão por sobrescrita é ruim de ler.
2. **Antes de responder, leia a task inteira** — `GET /projetos/{slug}/tasks/{codigo}` traz corpo + todos os eventos. Não responda só pelo frame do WebSocket, que é uma linha resumida.
3. **`pergunta` só quando você realmente travou.** Pergunta em aberto aparece no resumo geral do relatório e vira ruído se for usada pra conversa fiada.
4. **Uma task por assunto.** Se a conversa numa task virou outro assunto, crie task nova e ligue com dependência.
5. **`status` reflete o estado real**, não a intenção. `feito` é feito e verificado. `bloqueado` exige que exista um dono humano (`dono_id`) — senão ninguém sabe de quem cobrar.
6. **Decisão vira `decisao`, não prosa dentro do corpo.** É `tipo=decisao` que deixa a decisão rastreável a autor e horário.

## Ler o consolidado

```bash
# relatório completo, markdown
curl -s -H "Authorization: Bearer $TOKEN" "http://$HOST:8787/projetos/gases/relatorio"

# só o que mudou desde o cursor que você tinha
curl -s -H "Authorization: Bearer $TOKEN" "http://$HOST:8787/projetos/gases/relatorio?desde=$ULTIMO_CURSOR"

# estruturado, pra processar sem parsear markdown
curl -s -H "Authorization: Bearer $TOKEN" "http://$HOST:8787/projetos/gases/relatorio?formato=json"
```

Contrato inteiro, navegável: `http://<host>:8787/docs`.
