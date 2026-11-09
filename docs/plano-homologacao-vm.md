# Passagem operacional — Lumi V3

Atualizado em 07/11/2026. O usuário autorizou a implantação na VM Rincão e a publicação do código no GitHub. A convenção aprovada é `develop` para homologação e `main` para produção. O código dos dois ambientes corresponde à mesma release; configurações, bancos e credenciais continuam separados.

## Estado comprovado

Na sincronização inicial, HML e PROD executavam `20261107-tenant-ai-r3`. Após habilitar a automação, a release atual de cada ambiente deve ser consultada em `deployment-state.json`; o fluxo está em [deploy automático](deploy-automatico.md). Na conferência para sincronização do GitHub, os 186 arquivos de cada instalação coincidiram com o manifesto original e os quatro serviços Windows estavam em execução. O registro e os hashes estão em [versionamento e publicação](versionamento-e-publicacao.md). Os arquivos executáveis do checkout coincidem com o pacote; a documentação recebeu atualizações posteriores.

PostgreSQL usa bancos e usuários exclusivos por ambiente. A importação preservou a configuração sanitizada recebida, sem migrar históricos, logins ou canais antigos. A tabela aditiva de IA guarda provider, modelo e chave cifrada por tenant, sem fallback global. Preserve banco e chave Fernet separadamente.

HML usa Codex pelo gateway do Mac para o tenant Rincão. O canal de teste terminou o fluxo com mensagens recebidas, respostas e confirmação de leitura. PROD usa a chave OpenAI original do Rincão, distinta da Estância, com `gpt-6-luna`. Duas inferências no simulador de PROD funcionaram; o relatório distingue custo conhecido, desconhecido e total parcial. Detalhes em [produção](producao-vm.md) e [homologação](homologacao-vm.md).

Na revisão para publicação, 244 testes passaram com SQLite e PostgreSQL local isolado. A revisão independente estática de segurança e qualidade não encontrou bloqueadores. Testes anteriores de navegador validaram o painel em desktop/mobile; não foram repetidas inferências pagas nesta sincronização.

## Canal Rincão em produção — pendente

O usuário decidiu aguardar acesso ao número para concluir a verificação Meta e usar somente o app Rincao. Não prosseguir com a alternativa Ingressos_rincao. O app Rincao atende outros números: seu callback global deve ser preservado. Nenhum callback Meta de produção foi alterado.

O token de envio existente é válido, mas foi emitido pelo Ingressos_rincao. A auditoria somente leitura de bancos, versões históricas e backups não encontrou token operacional emitido pelo app Rincao nas fontes examinadas. O App Secret correto do Rincao foi encontrado e validado; ele não substitui o token de gestão necessário para configurar o override no contexto desse app.

Próxima ação depende do usuário: concluir a verificação e provisionar privadamente o token do app Rincao. Depois, validar aplicativo emissor, acesso ao telefone e permissões; registrar a rota anterior; alterar somente o override do telefone autorizado; verificar ambos os caminhos de entrega para evitar atendimento paralelo. Não remover assinaturas, modificar outros números ou ativar Instagram como atalho. O aceite exige mensagem real autorizada, recebimento, resposta e confirmação de entrega na V3, seguido de conferência do consumo do tenant.

## Recursos e limites

Atualização de 09/11/2026 após o teste: o usuário confirmou o WhatsApp 5705 e foram encontrados recibos de entrega/leitura. A revisão autorizada de conteúdo da Estância foi aplicada apenas na V3 HML: identidade/personality corrigidas, cinco textos revisados, preços antigos retirados e quatro fotos oficiais cadastradas. Os 18 itens e seus IDs foram mantidos; ferramentas continuam desligadas, outros tenants e canais preservados. Backup, manifesto de origem e recibo ficam privados na VM; detalhes e retorno em [conteúdo e fotos](homologacao-vm.md#estância--conteúdo-e-fotos-em-hml). JPEGs e catálogo do prompt passaram na verificação. Falta o teste real de envio de foto; Instagram continua dependendo das credenciais/acesso do app correto. Não há execução em segundo plano.

Em 09/11/2026, o usuário autorizou transferir o WhatsApp 5705 do tenant Brevia na Spark HML para Estância na V3 HML. Vínculo e override específico foram aplicados e conferidos; app Meta Lumi, callback `/webhooks/whatsapp`. Callback global, 3861, produção e demais canais preservados. Challenge e assinatura passaram sem envio; o teste real posterior está registrado acima. Instagram confirmado como `@testebrev`: receptor e rota IIS HML preparados, challenge validado, sem vínculo no banco ou alteração na Meta. Faltam as credenciais da instalação do Isaque; o usuário não possui o arquivo, o backup é sanitizado e o app Lumi-V3 não aparece na sessão Meta disponível. Próxima ação depende de recuperar acesso ao app/perfil para validar a identidade e concluir o vínculo. Detalhes e retorno em [homologação](homologacao-vm.md#estância--whatsapp-5705). Não há processo de migração em segundo plano. O usuário autorizou publicar somente a documentação em `develop`; arquivos privados permanecem fora do Git.

Arquivos privados, backups, logs, capturas e scripts transitórios permanecem fora do Git. O histórico detalhado da investigação está preservado localmente em `.data/plano-homologacao-vm-before-github-sync.md`. Nenhum processo de investigação de token permanece executando em segundo plano.

A automação de deploy por branch foi solicitada depois desta sincronização; consulte [deploy automático](deploy-automatico.md). O procedimento autorizado de migração, os backups e o retorno estão nos guias dos ambientes. Não restaurar banco sobre conversas novas para desfazer apenas código; não substituir chave Fernet nem reintroduzir chave OpenAI global. Instagram de produção e WhatsApp Rincão de produção não possuem aceite de ponta a ponta nesta entrega.
