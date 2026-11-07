# Versionamento e publicação

Convenção aprovada em 07/11/2026: `develop` representa homologação; `main`, produção. Ambas recebem nesta sincronização o código já implantado da release `20261107-tenant-ai-r3`. As configurações e os dados dos ambientes são independentes e não pertencem às branches.

## Correspondência com a VM

O pacote original tem SHA-256 `a6549cbca304ed22096a7ac17532127cc6fd97f7777a174d70f49474b39fde4f`. O [manifesto original](releases/20261107-tenant-ai-r3.manifest.json) tem SHA-256 `e724ad024865c86624a57688f345eda021762266859d456a7721c2fe6051783d` e identifica os 186 arquivos do pacote, sem incluir o próprio manifesto.

A conferência somente leitura nas duas instalações confirmou cada arquivo contra esse manifesto e os quatro serviços em execução. O checkout contém o mesmo código executável, recursos estáticos, scripts de serviço e `requirements-vm.lock` do pacote. O lock foi recuperado do artefato original; não foi recalculado com dependências atuais. Testes e documentação complementam o pacote e não precisam estar instalados na VM.

A documentação no Git inclui decisões posteriores à publicação: branches, investigação de credenciais e espera pela verificação Meta. Assim, hashes de documentação podem diferir da release original. O manifesto preserva a evidência histórica e não deve ser reescrito para esconder essas diferenças.

## Fluxo das próximas mudanças

Um push em `develop` inicia a publicação automática em homologação; um push em `main`, em produção. Integre em `main` somente a versão aprovada para produção. O workflow também pode ser reexecutado manualmente nessas branches. O commit, a branch e os hashes ficam no artefato e no estado de implantação da VM. Não mova uma referência de release antiga para código diferente.

O workflow [Deploy Lumi V3](../.github/workflows/deploy.yml) testa o retorno no Windows e a aplicação com SQLite/PostgreSQL isolados. Depois empacota somente arquivos de runtime do commit, verifica se ele ainda é o mais recente da branch e publica por SSH. As execuções são serializadas entre os ambientes e não cancelam um deploy em andamento. Consulte [deploy automático](deploy-automatico.md) para configuração, verificações, retorno e limites. O estado inicial e as rotas dos ambientes estão em [homologação](homologacao-vm.md) e [produção](producao-vm.md).

## Conteúdo privado

Não versionar `.env`, arquivos privados de acesso, chaves, tokens, dumps, bancos, logs, capturas com dados de clientes nem o ZIP de configuração recebido. `.env.example` contém somente placeholders; fixtures usam valores fictícios. Segredos de IA ficam cifrados no banco do ambiente; a chave Fernet e as credenciais de infraestrutura são provisionadas fora do repositório.

## Validação desta sincronização

Foram executados 244 testes com SQLite e PostgreSQL isolados, sem chamadas externas, com sucesso. Revisões independentes estáticas de segurança e qualidade não encontraram bloqueadores. A busca por padrões de credenciais e a comparação com segredos privados locais não devem imprimir valores; achados fictícios são revisados antes do commit. Não houve nova publicação na VM, alteração Meta, envio de mensagem ou inferência paga durante esta sincronização.
