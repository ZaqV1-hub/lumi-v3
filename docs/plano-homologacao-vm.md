# Passagem operacional — Lumi V3

Atualizado em 07/11/2026. O usuário autorizou a implantação na VM Rincão e a publicação do código no GitHub. A convenção aprovada é `develop` para homologação e `main` para produção. O código dos dois ambientes corresponde à mesma release; configurações, bancos e credenciais continuam separados.

## Estado comprovado

HML e PROD executam `20261107-tenant-ai-r3`. Na conferência para sincronização do GitHub, os 186 arquivos de cada instalação coincidiram com o manifesto original e os quatro serviços Windows estavam em execução. O registro e os hashes estão em [versionamento e publicação](versionamento-e-publicacao.md). Os arquivos executáveis do checkout coincidem com o pacote; a documentação recebeu atualizações posteriores.

PostgreSQL usa bancos e usuários exclusivos por ambiente. A importação preservou a configuração sanitizada recebida, sem migrar históricos, logins ou canais antigos. A tabela aditiva de IA guarda provider, modelo e chave cifrada por tenant, sem fallback global. Preserve banco e chave Fernet separadamente.

HML usa Codex pelo gateway do Mac para o tenant Rincão. O canal de teste terminou o fluxo com mensagens recebidas, respostas e confirmação de leitura. PROD usa a chave OpenAI original do Rincão, distinta da Estância, com `gpt-6-luna`. Duas inferências no simulador de PROD funcionaram; o relatório distingue custo conhecido, desconhecido e total parcial. Detalhes em [produção](producao-vm.md) e [homologação](homologacao-vm.md).

Na revisão para publicação, 244 testes passaram com SQLite e PostgreSQL local isolado. A revisão independente estática de segurança e qualidade não encontrou bloqueadores. Testes anteriores de navegador validaram o painel em desktop/mobile; não foram repetidas inferências pagas nesta sincronização.

## Canal Rincão em produção — pendente

O usuário decidiu aguardar acesso ao número para concluir a verificação Meta e usar somente o app Rincao. Não prosseguir com a alternativa Ingressos_rincao. O app Rincao atende outros números: seu callback global deve ser preservado. Nenhum callback Meta de produção foi alterado.

O token de envio existente é válido, mas foi emitido pelo Ingressos_rincao. A auditoria somente leitura de bancos, versões históricas e backups não encontrou token operacional emitido pelo app Rincao nas fontes examinadas. O App Secret correto do Rincao foi encontrado e validado; ele não substitui o token de gestão necessário para configurar o override no contexto desse app.

Próxima ação depende do usuário: concluir a verificação e provisionar privadamente o token do app Rincao. Depois, validar aplicativo emissor, acesso ao telefone e permissões; registrar a rota anterior; alterar somente o override do telefone autorizado; verificar ambos os caminhos de entrega para evitar atendimento paralelo. Não remover assinaturas, modificar outros números ou ativar Instagram como atalho. O aceite exige mensagem real autorizada, recebimento, resposta e confirmação de entrega na V3, seguido de conferência do consumo do tenant.

## Recursos e limites

Arquivos privados, backups, logs, capturas e scripts transitórios permanecem fora do Git. O histórico detalhado da investigação está preservado localmente em `.data/plano-homologacao-vm-before-github-sync.md`. Nenhum processo de investigação de token permanece executando em segundo plano.

Publicar branches não implanta código automaticamente. O procedimento autorizado de migração, os backups e o retorno estão nos guias dos ambientes. Não restaurar banco sobre conversas novas para desfazer apenas código; não substituir chave Fernet nem reintroduzir chave OpenAI global. Instagram de produção e WhatsApp Rincão de produção não possuem aceite de ponta a ponta nesta entrega.
