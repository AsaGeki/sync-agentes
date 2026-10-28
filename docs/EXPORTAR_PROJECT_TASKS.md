# Exportar para Project Tasks MCP

O arquivo é compatível com o importador nativo do Project Tasks MCP e cria um projeto separado no destino.

Na interface web, abra o projeto desejado, encontre **Exportar projeto**, escolha o repositório padrão das tasks e clique em **Baixar JSON**. O navegador fará o download conforme suas configurações.

Também é possível gerar o arquivo pela linha de comando. O comando lê o banco em uma transação somente de leitura.

Na raiz do sync-agents, execute:

```powershell
python server/scripts/exportar_project_tasks.py
```

Escolha o projeto e o repositório padrão na lista. O arquivo será criado no diretório atual; um arquivo existente não é sobrescrito. Também é possível informar as opções diretamente:

```powershell
python server/scripts/exportar_project_tasks.py --projeto avb-one --repositorio <commit-raiz> --saida avb-one-export.json
```

O banco padrão é `server/sync.db`. Use `SYNC_AGENTS_DB` ou `--banco` para selecionar outro arquivo. O projeto de origem não associa tarefas a repositórios: todas receberão o repositório padrão escolhido. Confira essa associação depois de importar.

## Importação

No Project Tasks MCP com a rota `POST /admin/projects/import`, envie o arquivo como corpo JSON usando uma credencial humana de administrador do sistema. Por exemplo, no PowerShell:

```powershell
$credencial = Get-Credential -UserName admin -Message 'Informe o token humano de administrador no campo de senha'
$cabecalhos = @{ Authorization = 'Bearer ' + $credencial.GetNetworkCredential().Password }
Invoke-RestMethod -Method Post -Uri 'http://localhost:3443/admin/projects/import' -Headers $cabecalhos -ContentType 'application/json; charset=utf-8' -InFile 'avb-one-export.json'
```

Troque a URL e o caminho conforme sua instalação. A rota aceita arquivos de até 25 MB. Confira as contagens, os registros ignorados e os avisos retornados; configure os membros e as permissões no destino.

## Conversões e repetição

- Features, tarefas, dependências e mensagens são convertidas para registros do destino. O corpo mais recente fica nas instruções da tarefa; códigos e tags ficam em texto. Eventos da origem, incluindo versões anteriores do corpo e diffs, são incluídos como eventos históricos com seus dados originais; a apresentação deles depende do destino.
- `feito` vira `concluida`, `cancelada` permanece `cancelada`, `ideia` e `parcial` viram `pendente`, e `bloqueado`, `aguardando_decisao` e `em_andamento` viram `bloqueada`. O estado original fica nas instruções. Nenhuma execução ativa é criada.
- Tags `backend`, `frontend` ou `front` definem a área; se ausentes ou contraditórias, usa-se `outro`. Uma única tag reconhecida como tipo de tarefa define o tipo; se ausente ou ambígua, usa-se `feature`. As tags continuam no texto. A origem não possui prioridade nem critérios de aceite estruturados: o destino receberá prioridade 0 e critérios vazios.
- A visibilidade `team` vira `public` e `private` permanece `private`. Status do projeto, códigos, tags e commit raiz ficam em campos de texto. O vínculo Git e os acessos devem ser configurados no destino.
- IDs são derivados do projeto e dos IDs da origem. Repetir a exportação do mesmo banco mantém os IDs: o importador do destino reconhece um pacote igual e preserva os registros já existentes. Um pacote atualizado pode acrescentar registros novos, mas não atualiza registros existentes nem aplica novas dependências em tarefas existentes. Confira os itens ignorados na resposta.
- Credenciais, permissões, pedidos de acesso e marcas de leitura não são exportados. Textos livres e URLs podem conter dados sensíveis; revise o JSON antes de compartilhá-lo. O destino também aplica sua própria remoção de padrões de segredos na importação.
