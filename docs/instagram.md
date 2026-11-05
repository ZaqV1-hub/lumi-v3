# Instagram

O adaptador usa o mesmo atendimento do simulador e do WhatsApp: contexto e personalidade do banco, onboarding, anexos, anti-spam, ferramentas e handover. O vínculo `instagram_channels` define o tenant pelo ID do perfil receptor. Um remetente novo recebe papel `cliente`; o nome do perfil não concede permissões.

O receptor público continua em `app.whatsapp.webhook:app`, porta local 8002, com GET/POST `/webhooks/instagram`. O admin permanece privado na porta 8000. A assinatura HMAC é conferida com a chave configurada para cada perfil, antes de encaminhar mensagens. Eventos duplicados e ecos são ignorados. Há histórico de recebimento e envio; uma falha de envio não dispara repetição automática, pois a Meta pode ter recebido parte da resposta.

As credenciais ficam em `%LOCALAPPDATA%\Lumi\instagram.env`, fora do Git. Configure `INSTAGRAM_VERIFY_TOKEN`, `INSTAGRAM_PUBLIC_BASE_URL` (HTTPS do receptor), `INSTAGRAM_GRAPH_VERSION` e variáveis privadas de token/chave por integração. Para cada variável de token `TOKEN_ENV`, `TOKEN_ENV_GRAPH_HOST` escolhe exclusivamente `graph.facebook.com` (Login Unificado atual) ou `graph.instagram.com` (Login do Instagram legado). Não use tokens de um fluxo no outro. A chave de assinatura deve corresponder ao aplicativo daquele fluxo.

```powershell
python -m app.instagram.setup --tenant SLUG --profile-id ID_DO_PERFIL --token-env NOME_DA_VARIAVEL_DO_TOKEN --secret-env NOME_DA_VARIAVEL_DA_CHAVE
```

O comando recusa reassociar a outro tenant um perfil já vinculado. Ele não autoriza a conta na Meta nem assina o webhook: a autorização, os IDs, a assinatura e o envio real precisam ser verificados antes de declarar o canal conectado. Não altere o callback de um aplicativo antigo em uso. Configure um app separado para a V3.

Depois de preparar o vínculo, `/instagram-setup?tenant=ID_DO_TENANT&profile=ID_DO_PERFIL` permite colar o token do Login Unificado em um campo privado. A sessão autenticada precisa ter acesso ao tenant selecionado. O servidor consulta o perfil na Meta, exige o ID correto e só então salva a credencial no arquivo privado. O token não é devolvido na resposta nem enviado ao modelo. `/whatsapp-setup?tenant=ID_DO_TENANT&phone=ID_DO_TELEFONE` tem o mesmo fluxo para o WhatsApp. Validar o token não confirma que o webhook ou o número já estão ativos.

No Login Unificado, solicite somente `instagram_basic` e `instagram_manage_messages` para o atendimento. A Meta fornece uma configuração inicial com permissões adicionais; revise e remova anúncios, comentários e publicação antes da autorização. Para testes em desenvolvimento, adicione e aceite o perfil profissional como Testador do Instagram. O acesso a clientes fora dos papéis do app exige os requisitos de publicação e análise da Meta. Referência: [guia oficial atualizado de Login Unificado](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started).

Texto, uma imagem com legenda ou um áudio por evento entram no fluxo comum. Galerias, vídeos e outros tipos ficam registrados como não suportados. Imagens de saída recebem um endereço temporário de 15 minutos, com verificação de tenant; o banco de imagens não é publicado. O envio é limitado à janela de 24 horas após a mensagem recebida. O operador usa essa mesma janela; não há extensão automática.

O download segue até três redirecionamentos, validando HTTPS, domínio permitido da Meta e DNS público a cada etapa. Para eventos de áudio, o tipo é identificado pelo conteúdo real, inclusive quando a Meta devolve M4A como `application/octet-stream` ou `video/mp4`; a validação de contêiner, duração e tamanho continua aplicada. Uma falha de recebimento registra a etapa e o código HTTP ou tipo de erro, sem guardar URLs assinadas no erro. No atendimento automático, uma falha ao abrir o anexo é informada ao cliente; conversas assumidas por humano ou contatos bloqueados não recebem esse aviso automático.

Testes locais sem chamadas à Meta: `python -m unittest tests.test_instagram tests.test_whatsapp tests.test_incoming`. O teste ponta a ponta real depende da autorização do perfil e de uma mensagem iniciada pelo usuário.

## Receptor local e ativação do WhatsApp

`scripts/start-channels.ps1 -PythonPath CAMINHO_PYTHON` inicia somente o receptor local, na porta 8002. O parâmetro explícito `-PublicTunnel` também abre o túnel Cloudflare para essa porta. O script não baixa executáveis, não expõe a porta 8000 e recusa usar uma porta 8002 ocupada por outro serviço. Consulte `/quicktunnel` nas métricas locais da porta 20241 para obter o endereço atual; não reaproveite URLs antigas de túneis temporários.

Um telefone com código já verificado pode continuar `PENDING` e `platform_type=NOT_APPLICABLE` até o registro na API. `/whatsapp-activate?tenant=ID_DO_TENANT&phone=ID_DO_TELEFONE` permite ao operador informar o PIN de seis dígitos diretamente, usando o token privado do canal. O servidor verifica o tenant e o estado antes de registrar: um número já ativo não é registrado novamente por esse fluxo. O PIN só é enviado à Meta; não é salvo no banco nem no arquivo de configuração. O registro confirmado também não prova que o aplicativo está publicado, que o webhook está assinado ou que uma mensagem real foi entregue. Referência: [registro de telefones da Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration).

## Aviso de privacidade

`/privacy-preview` no admin local exige login da equipe Brevia. O texto para publicação está em `docs/privacy-policy.html`; a cópia de revisão está em `docs/privacy-policy-draft.html`. O responsável aprovou o aviso dos testes em 31/10/2026. A rota `/privacy` do receptor só fica disponível quando o arquivo privado `%LOCALAPPDATA%\Lumi\privacy.env` contém `LUMI_PRIVACY_PUBLISHED=true`. Nenhuma credencial aparece no aviso. Alterações materiais no tratamento ou no texto precisam de nova revisão do responsável.

A política e os callbacks precisam de um endereço HTTPS disponível. O túnel de desenvolvimento é temporário: se o endereço mudar, atualize os dois callbacks, a URL de mídia Instagram e os endereços de privacidade/exclusão cadastrados na Meta. As credenciais temporárias da Meta também precisam ser renovadas quando expirarem. O teste real só deve ser declarado concluído depois de conferir o evento recebido e a resposta enviada.

## Validação desta instalação

Em 31/10/2026, o responsável publicou o Lumi-V3 na Meta e confirmou o recebimento de respostas no WhatsApp terminado em 8561 e no Instagram `@testebrev`. Os registros locais confirmaram processamento sem erro e o tenant `rincao` nos dois atendimentos. O WhatsApp retornou confirmação de leitura; o Instagram confirmou o envio da resposta. A conta WhatsApp antiga permaneceu assinada pelo aplicativo antigo, e o Instagram `@brevia.company` não teve seu callback alterado. As credenciais e o endereço temporário atual ficam apenas na configuração privada, fora do Git.

Esse primeiro teste validou somente texto. No teste seguinte, um áudio Instagram falhou antes de ser registrado e o modelo respondeu a um pedido de imagem com um link, sem escolher a foto cadastrada. Foram ajustados o recebimento de áudio e as instruções gerais do catálogo. Um teste real do modelo, em cópia isolada do banco, associou a imagem correta à resposta; os testes automatizados também cobriram M4A com MIME genérico, redirecionamento validado e aviso de falha sem exposição da URL assinada. O reteste real de áudio e imagem nos canais permanece necessário.
# Comentários públicos

O webhook também recebe `changes` do campo `comments`, com a mesma validação HMAC e vínculo de tenant pelo perfil receptor. As respostas são publicadas em `/{comment-id}/replies`, no próprio comentário. Não inicia um direct automaticamente. As instruções do convite para continuar no direct são editáveis em Configurações → Comentários Instagram e ficam em `instagram_comment_settings`, separadas das instruções das mensagens privadas.

Esse canal faz uma única inferência por comentário, com identidade, personalidade, instruções próprias, legenda da publicação e comentário. Não recebe base de conhecimento, histórico privado, objetivos de onboarding, imagens ou contratos de ferramentas. O código não executa nenhuma tool, handover, compra ou consulta financeira a partir de um comentário. A publicação é lida na Meta e deve pertencer ao perfil autorizado antes da geração. Não há resposta de exemplo ou texto de convite fixado no código.

Cada comentário é deduplicado por perfil e ID. Comentários do próprio perfil e IDs das respostas enviadas são ignorados; há limite de 20 comentários por minuto por perfil e três por remetente. A geração e o envio possuem estado registrado. Uma falha de envio ou reinício não repete automaticamente uma publicação ambígua. Desativar a configuração impede envios preparados. O consumo da inferência entra em `model_calls`; não usa outra chamada de modelo para executar ferramentas. O histórico aparece no admin identificado como Comentário Instagram.

Ativação exige permissão de gerenciamento de comentários e assinatura do evento `comments` na Meta. O servidor verifica ambas antes de aceitar a opção ativada. As instruções podem ser salvas enquanto a permissão está pendente. Os testes simulam eventos assinados e envios; isso não substitui um teste real em publicação do perfil autorizado. O @brevia.company e o aplicativo antigo devem permanecer intactos.

Em 31/10/2026 o responsável aprovou ampliar o acesso somente no @testebrev. A configuração do Login Unificado passou a solicitar `instagram_basic`, `instagram_manage_messages` e `instagram_manage_comments`. A API confirmou a permissão concedida; os eventos `messages,comments` foram assinados no aplicativo Lumi-V3 e nesse perfil. O admin aceitou e salvou a ativação após verificar ambos os requisitos. O teste de um novo comentário real continua pendente; o agente não publicou comentário artificial para validar a integração.
