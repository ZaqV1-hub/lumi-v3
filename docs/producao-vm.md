# Lumi V3 — produção na VM Rincão

Estado verificado em 07/11/2026: o painel V3 está publicado em [api.lumi.brevia.company/admin](https://api.lumi.brevia.company/admin), com PostgreSQL próprio e seleção de IA por tenant. O simulador autenticado respondeu com a OpenAI API do Rincão. A transferência do callback WhatsApp de produção ainda está pendente; publicar o painel e cadastrar o canal não comprovam recebimento ou entrega de mensagens reais nesse número.

## Instalação e rotas

Raiz `C:\LumiV3-PROD`, ambiente Python em `venv`, configuração privada em `private\prod.env` e código pela junction `current`. PostgreSQL 16 em `127.0.0.1:5441`, banco `lumi_v3_prod` e role exclusiva sem privilégio de superusuário. A base da V3 não substitui os bancos dos sistemas anteriores.

Os serviços `lumi-v3-prod` e `lumi-v3-prod-webhook` executam, respectivamente, o painel em `127.0.0.1:8014` e o receptor em `127.0.0.1:8015`. Cada serviço usa um único worker Uvicorn, conta `LocalService`, início automático, dependência `lumi-postgresql-16-prod` e recuperação configurada no WinSW. Os XMLs estão em `scripts/windows/lumi-v3-prod.xml` e `scripts/windows/lumi-v3-prod-webhook.xml`. `LOCALAPPDATA` é definido explicitamente no XML para os dados privados da V3. Os logs ficam em `C:\LumiV3-PROD\logs`, com rotação; o access log do Uvicorn está desligado.

O IIS termina HTTPS e encaminha o painel à porta 8014. As rotas `/webhooks/whatsapp`, `/webhooks/instagram` e `/channels/instagram/media/{token}` são encaminhadas ao receptor em 8015. A configuração dessas rotas não ativa canais na Meta. `/health`, `/v1/` e `/webhook` continuam no backend legado em `127.0.0.1:4321`; o painel anterior [lumi.brevia.company](https://lumi.brevia.company) continuou respondendo HTTP 200. Portanto, `/health` comprova o backend legado, não a saúde da V3. Não alterar esses contratos para testar o receptor novo.

## Release e ambientes

A release instalada é `20261107-tenant-ai-r3`, em `C:\LumiV3-PROD\releases\20261107-tenant-ai-r3`. O hash do pacote está registrado em [versionamento e publicação](versionamento-e-publicacao.md); `release-manifest.json` identifica os arquivos de código publicados. O pacote e a configuração privada são artefatos separados; não copiar segredos, banco, logs ou ambiente virtual para o repositório.

HML recebeu a mesma release, com painel/receptor em 8012/8013 e PostgreSQL em 5442. Os bancos e arquivos privados de HML e PROD permanecem separados. Rincão HML continua no Codex por gateway; Rincão PROD usa sua OpenAI API e não depende do Mac para inferência. A operação histórica de HML está em [homologação na VM](homologacao-vm.md).

## IA e acesso privado

Provider, modelo e chave são escolhidos por empresa em Configurações → Inteligência artificial, com acesso da equipe Brevia. As chaves OpenAI são cifradas com Fernet, vinculadas ao tenant, e a chave de criptografia fica no arquivo privado do ambiente. As variáveis globais `OPENAI_API_KEY`, `LUMI_PROVIDER`, `LUMI_OPENAI_MODEL` e `LUMI_CODEX_MODEL` não são usadas e foram removidas da configuração ativa. Leia [IA por tenant](ia-por-tenant.md) para preservação, remoção, migração e proteção das credenciais.

Rincão PROD preserva sua chave OpenAI original e utiliza `gpt-6-luna`, com esforço de raciocínio `low`. A chave da Estância é diferente, com modelo `gpt-6.1-sol`; a tentativa de inferência da Estância retornou HTTP 429 por falta de créditos. Não repetir chamadas da Estância até resolver o saldo. Não há fallback para a chave do Rincão ou outro provider.

O acesso privado da equipe está no Mac em `~/Library/Application Support/LumiV3-Dev/acesso-prod.txt`. Esse arquivo contém credenciais e não deve ser copiado para documentação, chat, testes ou Git. Alterar a configuração de IA pelo painel vale na próxima inferência; isso não exige reiniciar os serviços. Mudanças no arquivo de ambiente exigem reiniciar painel e receptor, preservando `LUMI_AI_SECRET_KEY`.

## WhatsApp Rincão

O número de produção terminado em **0718**, com Phone Number ID terminado em **9036**, está cadastrado no banco da V3 e vinculado ao tenant Rincão. O canal usa `RINCAO_WA_TOKEN`; a verificação do webhook usa `RINCAO_WA_TOKEN_APP_SECRET`, no arquivo privado `C:\LumiV3-PROD\data\Lumi\whatsapp.env`. As credenciais foram recuperadas do ambiente legado, sem colocar valores no código.

O aplicativo que assina o webhook do Rincão é `1027514482852149`, cujo segredo foi validado. O token de envio também foi validado, mas pertence ao aplicativo Ingressos_rincao (`1003516357903339`). A busca histórica de 07/11 confirmou esse mesmo token no banco legado `lumi` da porta 5432, tabela `TenantSecret`, referência `WHATSAPP_OWNER_PRIMARY_ACCESS_TOKEN`, com o Phone Number ID correto. A Meta retornou `type=SYSTEM_USER`, `is_valid=true`, `expires_at=0` e `data_access_expires_at=0`: já existe token de envio sem expiração programada. Essa credencial não substitui um token emitido pelo app Rincão para configurar o override no contexto dele. O emissor do token de envio não determina qual segredo verifica o webhook. Preserve essa distinção ao renovar credenciais. O endpoint administrativo de renovação copia o segredo efetivo para o novo prefixo do token; um segredo específico vazio continua desabilitado, sem herdar o global.

O receptor público passou pelo challenge HTTP 200, aceitou assinatura correta com HTTP 200 e rejeitou assinatura incorreta com HTTP 401. Esses testes foram sintéticos e não enviaram mensagens a contatos. **O callback Meta ainda não foi transferido para a V3**, e a configuração aguarda a verificação Meta pelo usuário. Não há aceite de ponta a ponta do WhatsApp de produção. Instagram não foi transferido nesta etapa.

O usuário confirmou que o app Rincão atende outros números. Seu callback global deve permanecer no legado. A transferência do 0718 deve usar o override de telefone no contexto do app Rincão, com token emitido por esse app e acesso à WABA correspondente. O token de envio existente é válido, mas pertence ao Ingressos_rincao e não deve ser usado para configurar a rota do outro aplicativo. O usuário escolheu concluir a verificação para gerar um token de usuário do sistema do app Rincão e usar somente esse aplicativo. A alternativa de transferência pelo Ingressos_rincao foi descartada; aguardar essa ação. Nenhum callback Meta de produção foi alterado.

A WABA do 0718 tem dois aplicativos inscritos. Conferir o destino e a entrega de ambos no corte; não presumir duplicação efetiva nem remover inscrições como atalho. Se houver resposta duplicada, retornar o override específico e investigar antes de liberar.

O aceite do canal depende de confirmar o callback correto na Meta e depois acompanhar uma mensagem real autorizada, o registro de entrada, a inferência do tenant e o recibo de entrega. Não interpretar cadastro do canal, HTTP 200 do challenge ou resposta no simulador como esse aceite.

## Verificações e consumo

Passaram 244 testes automatizados com SQLite e PostgreSQL isolados, em 24,982 segundos. A verificação Playwright do painel em desktop e mobile não registrou erros JavaScript. Os testes cobrem configuração de IA por tenant, isolamento de credenciais, permissões, migração, providers, consumo e proteção de assinatura por canal; transporte simulado não representa inferência real.

Foram realizadas duas inferências reais no simulador de PROD, sem erro, usando a configuração OpenAI do Rincão. O tempo médio foi de 5.016 ms. A primeira registrou 4.212 tokens de entrada e 323 de saída, antes da correção de estimativa de custo; seu custo permanece indeterminado. A segunda registrou 4.212 tokens de entrada, dos quais 4.209 em cache, e 333 de saída, com custo estimado de **US$ 0,00020889**.

A estimativa usa as [tarifas oficiais](https://developers.openai.com/api/docs/pricing) e os [metadados de cache](https://developers.openai.com/api/docs/guides/prompt-caching#monitor-cache-performance) conferidos em 07/11/2026. Ela considera leitura e escrita de cache conforme os metadados recebidos e não substitui a fatura da conta. Modelo, tier ou consumo sem tarifa completa permanecem com custo desconhecido. A UI mostra valores com seis casas decimais e identifica totais parciais: a primeira chamada não vira zero nem é incluída como custo conhecido. O valor mostrado para a segunda pode ser arredondado para US$ 0,000209.

## Preservação e retorno

O backup anterior à release está em `C:\LumiV3-PROD\backups\before-20261107-tenant-ai-r3.dump`; backups e releases anteriores foram preservados. A existência do dump não comprova restauração integral nem substitui uma rotina de backup. Preserve também a configuração privada e a chave Fernet, separadas do dump. Não restaure um banco antigo sobre conversas novas para desfazer somente uma publicação de código.

O script `scripts/windows/switch-prod-proxy.ps1` guarda o proxy anterior em `C:\LumiV3-PROD\backups\web.config.before-v3` e o estado/hashes em `proxy-state.json`. `-Restore` verifica o hash da configuração aplicada antes de restaurar e recusa sobrescrever uma mudança posterior. Execute a cópia revisada desse script em PowerShell administrativo com `-Restore` para retornar o proxy ao backend legado; não restaure o IIS inteiro nem altere outros sites da VM. O script de retorno foi revisado, mas sua execução na URL ativa não está registrada nesta entrega.

Antes do retorno, reconfirme o estado dos callbacks. No estado documentado, o WhatsApp PROD ainda está no legado. Se o callback passar a apontar para `/webhooks/whatsapp` da V3, restaurar o proxy antigo removerá essa rota e interromperá eventos: primeiro coordene o retorno do callback específico e valide o receptor antigo, ou preserve a rota necessária ao receptor V3. Não troque assinaturas globais de outros aplicativos/números como atalho.

Um retorno de código deve manter compatibilidade com a tabela `tenant_ai_settings` e com as chaves cifradas. Não reintroduza a chave de um cliente como segredo global para executar uma release anterior. O retorno do proxy ou código não transfere conversas entre bancos, desfaz chamadas OpenAI ou cancela mensagens já enviadas.
