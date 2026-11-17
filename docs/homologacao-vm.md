# Lumi V3 — homologação na VM Rincão

Atualização operacional de 09/11/2026: os serviços da Lumi antiga foram parados por autorização do usuário. V3 e bancos continuam ativos; as rotas que ainda apontam à Spark ficam indisponíveis. O inventário, o estado de inicialização e o retorno estão na [passagem operacional](plano-homologacao-vm.md#recursos-e-limites). Os registros anteriores abaixo descrevem o estado na data de cada implantação.

Implantação autorizada pelo usuário e concluída em 05/11/2026. Painel: https://api-hml.lumi.brevia.company/admin. O simulador exige login, disponível em `/chat/rincao` ou pelos links do painel. A URL anterior do painel independente permanece preservada; o acesso à V3 é pelo endereço acima.

## Estado entregue

Windows/PowerShell, Python 3.11.9 existente e PostgreSQL 17.5 em `127.0.0.1:5442`. Banco e usuário exclusivos `lumi_v3_hml`. Foram importados seis tenants, 43 conhecimentos e duas imagens do SQLite sanitizado original; quatro tenants são visíveis no console porque o backup já continha dois arquivados. Somente Rincão está ativo para o simulador. Não foram importadas conversas ou contas locais: a VM recebeu conta própria e contém apenas os testes fictícios executados nela. Ferramentas de negócio permanecem desligadas. Por solicitação posterior do usuário, foi habilitado somente o WhatsApp terminado em 3861 para Rincão; demais canais permanecem preservados.

O serviço `lumi-v3-hml` executa um único Uvicorn em `127.0.0.1:8012`, com início automático e dependência do PostgreSQL HML. Usa `LocalService` com SID próprio do serviço: leitura de código/configuração e escrita apenas em dados/logs. IIS termina TLS e encaminha a aplicação; o backend aceita headers de proxy somente de `127.0.0.1`. O IIS sobrescreve `X-Forwarded-Proto=https`; login HTTPS retorna cookie `Secure`, `HttpOnly` e `SameSite=Strict`. HTTP da V3 redireciona para HTTPS.

`LUMI_PRIVATE_SIMULATOR=true` restringe página, criação, mensagens, imagens e anexos a sessão autenticada e tenant autorizado. Continua valendo a restrição do responsável pelas conversas de gestão. No desenvolvimento local, o padrão permanece público. A chave não deve ser colocada no navegador nem em campos de conhecimento do tenant.

## Codex do Mac por gateway

O provider ativo é `codex_gateway`, modelo `gpt-6.1-terra`, esforço `low`. A VM chama o gateway por HTTPS/ngrok com Bearer dedicado e chave de idempotência. O gateway roda no Mac em `127.0.0.1:4317` usando o Codex CLI autenticado pela conta ChatGPT local; não foi copiada a sessão para a VM. Não há fallback para API paga. O gateway limita a uma inferência concorrente, com timeout de 120 segundos; o cliente da V3 espera até 125 segundos.

O repositório recuperado é `~/Documents/ChatGPT/lumi-codex-local-gateway-restored`, origin `juansouza09/lumi-codex-local-gateway`. As pastas anteriores foram preservadas. Houve ajuste para aceitar até duas imagens JPEG de 5 MiB; o limite HTTP do gateway foi configurado em 16 MiB para acomodar base64. São validados modelo efetivo, JSON Schema e autenticação. O gateway tem 76 testes passando, lint/types/build aprovados e nenhuma vulnerabilidade de dependência de runtime no audit executado; permanecem 13 avisos de desenvolvimento.

LaunchAgents do Mac: `com.brevia.lumi-codex-local-gateway` e `com.brevia.lumi-codex-ngrok`. Configuração privada em `~/Library/Application Support/LumiV3-Dev/gateway.env`. O túnel está com inspeção de requisições desativada. O gateway HML antigo em outra porta foi preservado. O Mac precisa permanecer ligado, acordado, conectado e com a sessão Codex válida. Se a URL do ngrok mudar, atualize `LUMI_CODEX_GATEWAY_URL` no `hml.env` da VM e reinicie os dois serviços V3. Não publique o token.

## Seleção de IA por tenant

Desde 06/11/2026, provider, modelo e chave OpenAI são definidos por tenant em Configurações → Inteligência artificial. As variáveis globais de seleção e `OPENAI_API_KEY` foram removidas do arquivo ativo. Rincão HML usa `codex_gateway`; Estância usa `openai`, modelo `gpt-6.1-sol`, chave exclusiva cifrada. A conta da Estância autenticou e listou esse modelo, mas a inferência retornou `credit_balance_exhausted` em 06/11. É necessário adicionar créditos para validar resposta real; não há fallback para outro tenant.

A chave de criptografia `LUMI_AI_SECRET_KEY` fica no arquivo privado do ambiente, separada do PostgreSQL. Leia [IA por tenant](ia-por-tenant.md) para cadastro, preservação/remoção de chave, migração e retorno. A UI não mostra a chave salva. Trocar provider/modelo pelo painel não exige reinício. O Codex HML continua dependendo do Mac e do túnel; a produção do Rincão preserva sua própria API OpenAI, conforme [operação de produção](producao-vm.md).

## Acessos e arquivos

O login da equipe está em `C:\LumiV3-HML\private\acesso-hml.txt`, protegido por ACL. Uma cópia privada foi entregue neste Mac em `~/Library/Application Support/LumiV3-Dev/acesso-hml.txt`. Credenciais e hashes de senha não estão nesta documentação.

Código: junction `C:\LumiV3-HML\current`, apontando para a release registrada em `C:\LumiV3-HML\deployment-state.json`. A release inicial `20261107-tenant-ai-r3` foi preservada; novas publicações usam o [deploy automático](deploy-automatico.md). Ambiente Python: `C:\LumiV3-HML\venv`. Dados e cache do transcritor: `C:\LumiV3-HML\data`. Logs rotativos: `C:\LumiV3-HML\logs`, até cinco arquivos de aproximadamente 10 MiB por fluxo. Logs de acesso do Uvicorn foram desligados para não registrar tokens de conversa em URLs.

O pacote inicial foi criado a partir do checkout com alterações locais e depois sincronizado no GitHub. As publicações automáticas usam o commit de `develop` e registram commit/hash em `deployment-state.json`; o histórico do pacote inicial está em `docs/versionamento-e-publicacao.md`. `release-manifest.json` registra hashes individuais; `requirements-vm.lock` fixa as versões usadas, com a dependência adicional de Windows `colorama` instalada pelo pip. Não copie a `.venv` do Mac para Windows.

A definição do serviço está em `service\lumi-v3-hml.xml`, reproduzida em `scripts/windows/lumi-v3-hml.xml` no repositório. O script de troca/retorno está em `C:\LumiV3-HML\staging\switch-hml-proxy.ps1`, correspondente a `scripts/windows/switch-hml-proxy.ps1`. A [documentação WinSW 2](https://winsw.github.io/v2/doc/xmlConfigFile/) descreve serviço, conta e recuperação.

## Verificações executadas

Passaram 234 testes automatizados locais na etapa de IA por tenant e segredo WhatsApp por canal, incluindo PostgreSQL real, importação transacional, isolamento e a nova proteção da homologação. Além da conversa inicial de duas rodadas, cinco chamadas reais ao Codex local validaram conhecimento, continuidade, imagem cadastrada e ausência de confirmação inventada de disponibilidade/pagamento. A duração dessas cinco chamadas foi de aproximadamente 5 a 10 segundos.

Na VM foram verificados login, conteúdo importado, imagem cadastrada, criação de conversa, persistência, bloqueio anônimo e resposta em modo demo temporário. No navegador pela URL HTTPS passaram login, cookie seguro, conversa, upload de imagem, histórico após recarregar e largura mobile, sem erros JavaScript. Upload de áudio WAV fictício de 4,6 segundos passou pela transcrição real no serviço e resposta demo; o modelo local de voz já está em cache na VM. A geração de resposta demo não foi apresentada como inferência OpenAI.

Na etapa anterior à conexão do gateway, foi verificado o provider `openai`. A ausência de chave produziu HTTP 503 esperado, com mensagem preservada, sem resposta inventada. A saída HTTPS da VM para OpenAI foi comprovada com HTTP 401 sem credencial, sem envio de conteúdo do tenant. Reinício manual e recuperação automática após encerramento controlado do processo da V3 foram confirmados. Não foi necessário reiniciar a VM.

Produção continuou respondendo HTTP 200 em `/health`; o painel HML anterior continuou respondendo. A regra `BreviaSupportEdgeHml`, o callback global Meta `/webhook` e os contratos `/v1/` permanecem no backend antigo, evitando alterar canais e integrações legadas nesta entrega. As demais rotas da URL HML agora são da V3.

Duas inferências reais adicionais pelo navegador HTTPS comprovaram o caminho VM → ngrok → gateway → Codex: conhecimento e imagem, persistência após recarregar, cookie seguro, layout mobile sem overflow e zero erros JavaScript. O banco registrou `codex_gateway`, modelo esperado e status `completed`, em 7,938 e 5,563 segundos. A visão também passou diretamente no gateway com uma imagem vermelha.

## WhatsApp 3861

O receptor `lumi-v3-hml-webhook` roda em `127.0.0.1:8013`, um worker, com a mesma base PostgreSQL. IIS encaminha somente `/webhooks/whatsapp` a esse serviço. Ele não oferece admin, Swagger ou OpenAPI. Ambos os serviços definem `LOCALAPPDATA` no XML WinSW: `--env-file` sozinho não substitui o valor herdado do Windows. As credenciais do canal ficam em `C:\LumiV3-HML\data\Lumi\whatsapp.env`, com ACL privada, reutilizando os valores existentes sem modificar o arquivo da Lumi anterior.

A Meta confirmou com HTTP 200 a troca do callback exclusivamente do número terminado em 3861 para `https://api-hml.lumi.brevia.company/webhooks/whatsapp`. O callback global da aplicação continua `/webhook`, no backend antigo. Não foram trocadas assinaturas globais nem o callback do outro número. O snapshot anterior está em `private\whatsapp3861-before-v3.json`; o posterior, em `private\whatsapp3861-after-v3.json`.

Na primeira mensagem real, as tentativas da Meta receberam HTTP 401 antes de entrar na inbox. O token de acesso era válido para o aplicativo, mas o App Secret copiado do ambiente antigo estava inválido (validação Graph HTTP 401/código 190). A cópia privada do segredo no projeto anterior foi validada com HTTP 200 para o mesmo aplicativo e aplicada somente à configuração da V3; o receptor foi reiniciado. O arquivo anterior foi preservado em `private\whatsapp.env.before-secret-fix`. Um teste assinado com o mesmo segredo configurado não detecta esse tipo de divergência: é necessário validar a credencial com a Meta e receber um evento real.

Passaram verificação pública de challenge, rejeição de token inválido, rejeição de POST sem assinatura e aceitação de evento vazio corretamente assinado. Esses testes não enviam mensagens. Após corrigir o segredo, o banco confirmou quatro mensagens processadas e quatro respostas com recibo `read` da Meta no número de teste 3861. Há também uma tentativa registrada como falha, que não foi reenviada automaticamente. Esses recibos comprovam o caminho real de entrada, IA e entrega, além dos testes sintéticos.

## Estância — WhatsApp 5705

Em 09/11/2026, por autorização do usuário, o número terminado em 5705 foi vinculado ao tenant existente `estancia` na V3 HML. O Phone Number ID termina em 8015. Antes ele atendia o tenant `brevia` na Lumi Spark HML, com conteúdo de demonstração da Estância. O token foi reaproveitado da configuração privada antiga; a Meta confirmou que pertence ao app **Lumi** (`799007929569712`), não ao app Rincao.

O token e o segredo específico usam as referências `ESTANCIA_WHATSAPP_TOKEN_5705` e `ESTANCIA_WHATSAPP_TOKEN_5705_APP_SECRET` no arquivo privado `data\Lumi\whatsapp.env`. O segredo da Spark foi recusado pela Meta; foi reutilizado o segredo válido desse mesmo app já presente na V3, sem alterar a Spark ou os valores dos outros canais. O cadastro foi aplicado em transação, sem mudança de schema, importação de contatos ou conversas antigas. Não houve reinício de serviço.

A Meta confirmou a alteração somente do override do telefone para `https://api-hml.lumi.brevia.company/webhooks/whatsapp`. O callback global do app continua `https://api-hml.lumi.brevia.company/webhook`, encaminhado pelo IIS à Spark na porta 4121. O override do 3861, seu vínculo com Rincão, os arquivos antigos e produção foram preservados. A migração do WhatsApp não alterou o IIS; a preparação posterior do Instagram adicionou somente a regra descrita abaixo. A V3 continua no commit `44d1a5b`.

Passaram challenge público HTTP 200, evento vazio assinado para o 5705 HTTP 200 e assinatura inválida HTTP 401. Esses eventos não enviam mensagens nem executam IA. Mais tarde em 09/11, o usuário confirmou funcionamento e a leitura do banco encontrou uma resposta entregue e duas lidas, incluindo resposta ao pedido de foto. Isso confirma o fluxo real de texto. Estância mantém OpenAI `gpt-6.1-sol` e sua chave própria; a falha anterior de créditos não impediu essas respostas. O agente não fez inferências pagas adicionais nessa conferência.

Snapshots privados: `private\estancia-5705-before-v3-20261109.json`, `private\estancia-5705-after-v3-20261109.json` e `private\whatsapp.env.before-estancia-5705-20261109`. O primeiro registra o vínculo anterior e hashes dos arquivos protegidos. Para retornar, validar primeiro o receptor e o segredo da Spark, corrigindo a credencial inválida somente com autorização; depois restaurar exclusivamente o override anterior do 5705 e confirmar recebimento. Não restaurar banco, IIS ou todo o arquivo de credenciais para desfazer esse vínculo; preservar quaisquer conversas novas. Nenhum retorno foi executado.

## Estância — Instagram testebrev pendente

O usuário confirmou `@testebrev`, citado nos testes locais da V3 com o app Lumi-V3 e vinculado naquele momento ao Rincão. A investigação encontrou somente `brevia.company` no HML Spark e nos 27 arquivos históricos com contas Instagram; produção também possui `cluberincao`. O backup sanitizado da instalação do Isaque não contém credenciais nem vínculos de canais. O usuário não possui o arquivo privado `instagram.env`, e o app Lumi-V3 não aparece entre os 15 apps disponíveis na sessão Meta consultada. Isso não prova que o app deixou de existir: o acesso correto ainda é necessário. Nenhum perfil ou callback Instagram foi alterado na Meta; nenhum vínculo Instagram foi criado no banco da VM.

O receptor foi preparado na V3 HML em 09/11/2026. A regra `LumiV3Instagram` no IIS de HML encaminha exclusivamente `webhooks/instagram` e `channels/instagram/media/[^/]+` para a porta local 8013. As regras anteriores foram comparadas e preservadas. O arquivo privado `data\Lumi\instagram.env` contém um novo `INSTAGRAM_VERIFY_TOKEN` e `INSTAGRAM_PUBLIC_BASE_URL=https://api-hml.lumi.brevia.company`, sem token de acesso do perfil ou app secret. Não houve reinício dos serviços nem mudança em produção.

Passaram challenge público Instagram HTTP 200, token de verificação incorreto HTTP 403 e mídia inválida HTTP 404. Challenge WhatsApp e painel continuaram HTTP 200. Essas verificações não validam mensagens reais, autorização do perfil ou entrega. O backup do IIS está em `C:\LumiV3-HML\backups\web.config.before-instagram-testebrev-20261109`, e os hashes e a regra adicionada estão em `private\instagram-route-20261109.json`. Para desfazer apenas a preparação, conferir o estado atual e remover somente `LumiV3Instagram`, preservando outras alterações; não restaurar o arquivo inteiro sobre alterações posteriores.

Próxima ação: obter com o responsável pela instalação original acesso ao app e credenciais válidas de `@testebrev`, ou concluir uma nova autorização desse perfil no app correto. Depois validar a identidade pela Meta, cadastrar o canal no tenant Estância em transação e configurar a entrega de eventos sem alterar os outros canais. Nenhuma migração permanece executando em segundo plano.

## Estância — conteúdo e fotos em HML

Em 09/11/2026, após comparar a V3 com a Spark, o usuário autorizou revisar o conteúdo e cadastrar fotos do parque. A V3 não tinha imagens; a Spark HML guardava textos antigos da Estância inativos dentro de Brevia, e as imagens encontradas eram da Brevia e dos fundadores. Não houve importação integral da Spark.

A operação preservou os 18 IDs de conhecimento e atualizou cinco textos, retirando valores antigos não validados e condições de compra não verificadas. Identidade e personalidade passaram a refletir o atendimento atual, sem afirmar uso exclusivo do simulador, e-commerce habilitado ou transferência automática disponível. As nove ferramentas continuaram desligadas. Foram inseridas quatro fotos da página inicial e da galeria de estrutura do site oficial, inspecionadas visualmente, validadas e normalizadas como JPEG conforme os limites do cadastro existente. Cada imagem possui nome, descrição e orientação de uso. Não são imagens ao vivo nem garantia de disponibilidade de atividades.

O plano privado `C:\LumiV3-HML\private\estancia-content-20261109\reviewed-plan.json` contém estados anterior e posterior. O diretório também guarda `photos.json`, fontes públicas, hashes e arquivos utilizados. O script operacional recebeu revisão independente, fez comparação com o estado preparado e aplicou a atualização em transação única, sem mudanças de schema. O backup anterior é `private\estancia-content-before-20261109.json`; o recibo conferido após o commit da transação é `private\estancia-content-after-20261109.json`. Dados e imagens de outros tenants, todas as ferramentas e vínculos de canais foram comparados antes/depois e permaneceram iguais. Produção não foi acessada para escrita. A atualização dos dados não exigiu reinício nem publicação de código; a documentação foi autorizada separadamente para commit e push na branch `develop`.

A conferência posterior confirmou quatro JPEGs legíveis, zero itens ativos com preços em reais antigos e os quatro IDs no catálogo produzido pela função `image_context` do código publicado. Os dois serviços HML seguem ativos. Isso valida cadastro e montagem do catálogo, sem simular escolha do modelo ou entrega no canal: o próximo teste é o usuário pedir novamente uma foto pelo WhatsApp.

Para retornar, comparar os valores atuais com o estado posterior antes de restaurar somente identidade, personalidade e os cinco conteúdos a partir do backup. Desativar somente os quatro IDs de imagem registrados no recibo, sem apagar imagens já referenciadas por mensagens. Preservar alterações posteriores, canais, ferramentas e conversas; não restaurar o banco inteiro. Nenhum retorno foi executado.

## Preservação e retorno

O SQLite de origem e seu hash foram preservados. A importação inicial criou schema e dados em transação; isso não substitui migrations futuras de colunas. `C:\LumiV3-HML\backups\initial-v3-hml.dump` é um backup inicial PostgreSQL em formato custom, verificado por listagem com `pg_restore`. O backup inicial não é uma rotina de backups periódicos nem uma prova de restauração completa.

O `web.config` anterior está em `C:\LumiV3-HML\backups\web.config.before-v3`. O arquivo `proxy-state.json` guarda hashes anterior/aplicado e o header adicionado no escopo do site. Antes de retornar o proxy, restaure o callback específico do 3861 usando o snapshot privado e um token de verificação válido do receptor anterior, e confirme o challenge/recebimento. O endpoint anterior retornou 503 na investigação; o retorno do canal não foi validado e exige recuperar esse serviço. Restaurar apenas o proxy deixaria o callback novo sem receptor. Depois de validar o canal anterior, para voltar o proxy:

```powershell
& C:\LumiV3-HML\staging\switch-hml-proxy.ps1 -Restore
```

O script recusa retorno se o `web.config` mudou desde a publicação, para não sobrescrever manutenção posterior. Não restaure o IIS inteiro: há outros sistemas na VM. O backend antigo continua disponível em `127.0.0.1:4121`; código e banco antigos não foram excluídos. O retorno do proxy não transfere mensagens novas da V3 para o banco antigo. A troca para V3 foi testada; o comando de retorno foi revisado, mas não executado na URL ativa.

Esta homologação habilita somente o canal WhatsApp solicitado. Instagram, pagamentos e ferramentas de negócio continuam desligados. O caminho atual depende do Mac; a alternativa OpenAI elimina essa dependência depois de configurada e validada com uma chave. Os XMLs instalados foram atualizados após o pacote para fixar `LOCALAPPDATA`; as cópias atuais estão em `service` e no repositório.
