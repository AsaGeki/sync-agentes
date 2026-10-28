# Plano: exportação para Project Tasks MCP

**Objetivo:** gerar, a partir de um projeto escolhido do sync-agents, um pacote para importação nativa como projeto separado.

**Arquitetura:** um comando Python no servidor lê o SQLite em uma transação de leitura e gera o pacote `project-tasks-export` v1. O importador existente do destino valida e grava o pacote. O arquivo recebido serve de referência, sem ser alterado ou incorporado.

**Restrições:** não instalar dependências, criar testes, alterar enums, tipos, interfaces ou schemas sem autorização; não fazer commits. Não modificar o banco de origem.

## Etapas

- [ ] Conferir os modelos e a validação da versão de destino, inclusive limites, formato de importação e referências entre coleções.
- [ ] Criar comando de exportação com listagem e escolha de projeto e de repositório padrão para tarefas, pois a origem não vincula tarefas a repositórios. Gerar IDs determinísticos para projeto e registros, separados dos IDs do arquivo fornecido.
- [ ] Adaptar metadados do projeto, repositórios, features, tarefas, status e dependências; preservar códigos, tags e informações sem equivalente em campos apropriados, relatando as conversões.
- [ ] Preservar corpos e histórico de mensagens e eventos em registros ou documentos consultáveis conforme suportado pelo importador; não transferir credenciais ou permissões. Explicitar qualquer dado que não possa ser restaurado como registro nativo.
- [ ] Documentar a geração, a importação no destino, a escolha de repositório e as limitações de reimportação. O importador preserva registros existentes pelo ID e não sincroniza alterações posteriores.
- [ ] Validar o pacote com o validador real do destino quando disponível e verificar referências, contagens e estabilidade dos IDs em exportações repetidas, sem escrever arquivos de teste nem alterar dados existentes.
