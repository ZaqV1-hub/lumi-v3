# Deploy automático da Lumi V3

Push em `develop` publica somente `C:\LumiV3-HML`; push em `main` publica somente `C:\LumiV3-PROD`. O workflow também aceita `workflow_dispatch` nessas branches. Ele não instala runner na VM, altera IIS, serviços legados, PostgreSQL, canais Meta ou configurações de IA. A conta SSH é a já autorizada para implantação; seu acesso amplo não amplia os alvos permitidos pelo script.

## Configuração do GitHub

O secret de repositório `RINCAO_VM_SSH_KEY` contém a chave SSH existente de deploy. Foi cadastrado reutilizando a chave local, sem gerar chave nova ou alterar `authorized_keys`. Seu valor nunca entra no Git. A identidade pública SSH da VM está fixada em `.github/rincao_known_hosts`, conferida pela conexão SSH já autenticada. Uma troca dessa identidade precisa ser validada antes de atualizar o arquivo; não usar `StrictHostKeyChecking=no`.

Checkout e setup-python usam revisões fixas. O token do workflow tem somente `contents: read`; a chave SSH só é disponibilizada no passo de publicação, em arquivo temporário com acesso restrito e remoção ao terminar. O workflow não executa deploy em pull requests ou branches diferentes. Testes usam credenciais fictícias e PostgreSQL descartável no runner.

## Sequência

1. Testar no Windows a troca de junction e o retorno com serviços/banco simulados, incluindo falhas de preparação, backup e saúde.
2. Executar a suíte Python com SQLite e PostgreSQL local ao runner, bloqueando inferências e rede externa nos testes.
3. Montar ZIP a partir dos blobs do commit. Arquivos privados, bancos, testes, caches, arquivos não versionados e alterações locais ficam fora. `deployment.json` identifica commit/branch; `release-manifest.json` contém os hashes.
4. Conferir a ponta da branch; se o commit já foi substituído, encerrar sem alterar a VM. Transferir pacote e scripts para `staging` apenas do ambiente correto.
5. Obter trava exclusiva no ambiente, validar hash, manifesto, metadados, caminhos Windows, dependências e configuração de banco. Preparar uma pasta nova em `releases` e conferir a saúde anterior.
6. Parar somente receptor e painel V3 daquele ambiente, aguardando encerramento. Criar backup do banco exclusivo e validar seu catálogo antes de trocar `current`.
7. Iniciar painel/receptor, conferir HTTP do painel, rejeição do challenge sem credencial e consulta de leitura ao banco. Confirmar que arquivos privados e XMLs de serviço não mudaram. Registrar commit, release, hash e release anterior em `deployment-state.json`.

Cada execução usa `gha-<sha12>-<run_id>-<attempt>`. Releases e backups anteriores são preservados. O script nunca remove o destino de uma junction: remove apenas o vínculo `current`, depois de conferir seu tipo. Publicações do mesmo ambiente são serializadas no Actions; uma trava exclusiva por ambiente na VM também impede sobreposição por execução manual. HML e PROD têm filas independentes, serviços, diretórios e bancos distintos; um push de uma branch não cancela a publicação pendente da outra.

## Retorno e limites

Falha após o início da parada tenta restaurar a junction anterior e reiniciar os dois serviços, com nova checagem de saúde. Falha de validação anterior à parada não interrompe serviços. O backup não é restaurado automaticamente: retornar código não deve apagar conversas novas. A release com falha e o backup ficam disponíveis para investigação. Se o próprio retorno falhar, o workflow termina com erro e exige verificação operacional.

O deploy reutiliza o venv existente sem instalar pacotes. Alterações em `requirements.txt` ou `requirements-vm.lock` são recusadas antes de parar serviços; exigem preparar e validar uma atualização de dependências separadamente. Não há execução genérica de migrations destrutivas, seed ou provisionamento de tenants. Mudanças de colunas exigem plano compatível com retorno, backup e migração explícita; `create_all` não substitui esse trabalho.

Há uma interrupção breve dos dois serviços do ambiente durante a troca. Não cancelar manualmente um job durante o deploy: interrupção do processo SSH, timeout ou falha da máquina podem exigir conferir `current`, serviços e `deployment-state.json` antes de tentar novamente. O banco, a chave Fernet e os arquivos `.env` devem permanecer preservados. Ausência de erro HTTP não comprova entrega WhatsApp; os testes do canal real continuam separados.

## Verificação operacional

Veja a execução de `Deploy Lumi V3` no GitHub Actions. Na VM, confira `deployment-state.json`, o `deployment.json` dentro de `current`, os hashes do manifesto e os serviços específicos. O health check público legado não atesta a V3; a automação consulta diretamente as portas locais 8012/8013 em HML e 8014/8015 em PROD.

Logs de testes e comandos de deploy não devem exibir credenciais. Erros de banco/rede são reduzidos à etapa e ao tipo; consulte a configuração privada diretamente no ambiente quando necessário, sem copiá-la para logs do Actions. A investigação do token Meta do Rincão permanece aguardando o usuário e não faz parte deste workflow.
